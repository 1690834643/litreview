#!/usr/bin/env python3
"""
run_job.py — 单个综述任务端到端（被 dispatch.py 在后台拉起，一任务一进程=一"窗口"）。

流程：建 workdir → 构造 Kimi 提示词 → kimi -p --yolo --skills-dir 一次跑完 →
找到 04_report.docx 就回信（docx + 源 PDF 压缩包）→ 释放并发锁 → 任务移入 done。

email 模式铁律：一次完成、不交互、不追问（缺字段用合理默认）。
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state")
RUNNING = os.path.join(STATE, "running")
DONE = os.path.join(STATE, "done")
SKILL = os.path.normpath(os.path.join(HERE, ".."))


def load_config():
    for n in ("config.yaml", "config.example.yaml"):
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            return yaml.safe_load(open(p, encoding="utf-8"))
    sys.exit("缺少 config.yaml")


def safe_name(s, n=40):
    s = re.sub(r"[^\w一-鿿-]+", "_", (s or "review").strip())
    return s[:n].strip("_") or "review"


def min_words_of(task, cfg):
    it = task.get("intake", {})
    raw = it.get("words")
    if raw:
        m = re.search(r"\d+", str(raw))
        if m:
            return int(m.group(0))
    return cfg.get("review", {}).get("min_words", 8000)


def build_prompt(task, workdir, cfg):
    it = task.get("intake", {})
    ab = cfg.get("ablesci", {})
    mw = min_words_of(task, cfg)
    if ab.get("enable"):
        ablesci_line = (
            "拿不到全文的优先走**科研通(ablesci.com)求助——近实时**（中文/CNKI/付费墙首选，详见 references/sources.md 科研通节）："
            "navigate `https://www.ablesci.com/assist/create`（须已登录）→ fill `#onekey`=DOI/PMID/标题 → click「智能提取文献信息」→ "
            "**等 8–15s 确认 `#Assist-title` 已回填**（没回填别硬点发布，会被「请…」校验拦下、提交失败）→ click「立即发布」→ 记下 `assist/detail?id=<ID>`。"
            "**发布后通常几分钟内就有人上传**：每 1–3 分钟回 `https://www.ablesci.com/my/assist-my` 取回填 PDF，下进 `02_pdfs/`、精读、补进正文。"
            "等几分钟仍没人应助的才写进 `05_pending_科研通.md`（含真实 assist/detail 链接 + 时间）；"
            "外层会用 --continue 再唤起你复查回填、补进综述并重生成 04_report.docx——科研通求助的文献最终要真写进综述，不能只躺 pending。")
    else:
        ablesci_line = "拿不到全文的只在 `05_pending_科研通.md` 标缺失，不发求助。"
    fields = "\n".join(
        f"- {k}：{v}" for k, v in [
            ("综述主题", it.get("topic", "")),
            ("要解决的问题", it.get("question", "（未指定，自行从主题提炼一个核心问题，全文围绕它组织）")),
            ("范围/边界", it.get("scope", "（未指定，自行合理界定）")),
            ("时间窗", it.get("timewin", "近 10 年优先，经典奠基文献不限")),
            ("期刊分区偏好", it.get("tier", "高区/TOP 优先，但不硬删低区经典")),
            ("篇数", it.get("count", "分诊 ~60，精读 ~20")),
            ("正文字数", f"≥ {mw} 字（中文，不含文献表/参考文献）"),
            ("必读种子文献", it.get("seeds", "（无）")),
            ("备注", it.get("notes", "（无）")),
        ]
    )
    return f"""你是 litreview 的 **Kimi 轮值执行器**。**严格按 `{SKILL}/SKILL.md` 与 `references/workflow.md` 的"邮件模式（一次完成）"执行**。
你独自承担本任务的检索、下载、**逐篇真精读**、真实性核查与成稿；编排与回信由外层负责。

# 本次任务 intake
{fields}

# 工作目录（已建好，所有产物写这里）
{workdir}

# 邮件模式铁律
- 默认一次性跑完、**不向请求方提问**。但这不等于"硬跑到底"——见下"歧义处理"。
- 全程用可移植工具：kimi-webbridge（curl http://127.0.0.1:10086）搜索/下载；
  easyScholar 分区用 `python {SKILL}/scripts/easyscholar_rank.py`（带缓存、限速 2/秒）；
  去重 `dedupe.py`；PDF 文本用 pdfplumber/PyMuPDF；综述转 docx 用 `build_docx.py`（期刊标准字体）。
- {ablesci_line}

# 检索与下载优先级（先下高档次）
- **优先下载、优先精读高档次论文**：高档次论文即使与主题不完全相干，其严谨的方法学与逻辑也能帮到来信者，可作"方法学/逻辑借鉴"纳入综述。
- 本领域（农林科学）高档次判据：综合/方法学强刊（**Nature Communications、Science Advances、PNAS** 等）即算高档次；**中科院一区且 IF ≥ 5** 算高档次。用 `easyscholar_rank.py` 拿分区/IF 后据此排序，先抓高档次。
- 平衡：低档次文献只在"强相关"或"经典奠基"时才纳入；高档次的部分相干文献欢迎纳入并明确标注其方法学借鉴价值。别为凑数塞低相关低档次文献。

# 歧义处理（意义不明确就发邮件确认，别硬跑偏）
出现下列任一情况，**不要硬用默认跑出一篇可能跑题的综述**：① 主题缺失或无法解析检索；
② 必读种子文献与主题明显矛盾（如种子是性别决定 piRNA、主题却是肠道共生菌）；③ 范围/对象自相矛盾。
此时写 `00_NEEDS_CLARIFY.md`（列出歧义点 + 给请求方的 1-3 个具体确认问题 + 你的暂定理解），然后**停止**，不生成 04_report.docx。外层会据此给请求方发澄清信。仅当歧义无碍主线时才按默认继续。

# 综述写作约束（务必遵守，决定质量）
- 围绕「要解决的问题」组织全文：开头点题、中间分主题论证、结尾回应该问题。**不要写成逐篇摘要罗列**。
- 主题化整合：按机制/主题分 3-5 个轴展开，做跨文献对比与综合，而非一篇一段。
- 每篇精读文献都要在正文有**实质讨论**（核心贡献 + 方法/证据强度 + 局限），不能只出现在文献表。
- 每个论断都要有文献支撑（作者 年）；**不编造数据、结论或引用**；证据不足就明说"尚不清楚/有争议"。
- 显式写「研究空白与矛盾」(gap analysis) 一节，并指回「要解决的问题」。
- **正文 ≥ {mw} 字**（不含文献表/参考文献）。字数不够就把各主题轴、证据比较、gap 写深写透，不要凑字数。

# 写作质量约束（决定读起来像不像人写的——别写差了）
- **逻辑优先、一段一义、一句一论点**：每段首句点明本段结论，其后句句为它服务；写精瘦，不过度解释、不堆叠从句、不灌水。
- **客观第三人称**：综述给同行读，**严禁第二人称"你/你的课题"**，也别用"我们认为"式空话；改用"本综述/该方向/现有证据表明"。
- **去 AI 腔**：禁用套路口癖——滥用"不是 X 而是 Y"、"值得注意的是"、"综上所述"、表演式铺垫、空泛排比、为对仗硬凑的二元对立；判断直给、动词有力。
- **claim 有界**：用"表明/提示/可能/尚不清楚"校准强弱，不过度断言、不乱安"首次/唯一"。
- 物种名/基因名斜体；中文正文 + 英文术语；英文用 American English，正文不要英文 em-dash（—）。

# 论文真实性核查（强制，决定可信度——上一轮就栽在这里）
- **真精读，不许脑补**：每篇精读文献必须真读 PDF 全文后写 `03_notes/<键>.md`，分节填：核心问题 / 方法与证据(具体方法+剂量+时间+对照，带原文数字) / 主要发现(带数字) / 与主题关系 / 证据强度 / 局限。**严禁留「待精读补充」占位**或拿摘要/先验糊弄；正文每个数字都要能在某篇 `03_notes` 里找到出处。
- **下载真实性**：下载后用 `file 02_pdfs/*.pdf` 查类型——把 HTML 当 .pdf 存（Frontiers/BMC 网页）、或 5KB 级「Just a moment」Cloudflare 桩文件都算失败，必须用 kimi-webbridge 真实浏览器重抓；抽不出≥800 字正文的不得用作精读源。
- **检索对题**：核对选单是否真的切"要解决的问题/方法主题"，而非只匹配物种或某个热点（如别让一堆病毒学文献顶替"共生菌回补方法"）；跑题的移出主体、至多作背景。
- **引用核查**：正文每条（作者 年）必须对应一篇你真读过的源；**没拿到/没读的文献不得在文献表里编"核心发现"**，更不能凭空给具体数字；参考文献的作者/年/DOI/卷页一律以 crossref 核对（`https://api.crossref.org/works/<DOI>`），第一作者别想当然（文件名常与真一作不符）。
- **数字逐条核**：凡 ID50、感染率、拷贝数、天数等具体数值，回原文确认确实存在再写；查无实据的删除或改引正确出处。

# 必须产出（缺一不可，文件名严格一致）
1. `00_intake.md` —— 记下本次 intake（含"要解决的问题"）与最终检索式
2. `02_pdfs/` 下载到的源 PDF（含科研通后续回填的）；`03_notes/<键>.md` —— 每篇精读文献一条**填满的** grounded 笔记（见上"真精读"，空模板视为未完成）
3. `04_report.docx` —— 中文正文+英文术语的综述，**必须用** `python {SKILL}/scripts/build_docx.py <你的综述>.md -o 04_report.docx --title "<题>"` 生成（含文献对比表，每篇标 IF/中科院分区）。**文件名必须正好是 04_report.docx**，**正文 ≥ {mw} 字**。
4. `sources.zip` —— `python {SKILL}/scripts/zip_pdfs.py 02_pdfs --outdir . --max-mb 100000`（打成一个包；外层会上传服务器给下载链接，不必拆卷）
5. `email_body.md` —— 回信正文：3-5 句总览 + 文献表摘要 + 高水平论文范围（分区分级）。**不要写"附件含 PDF"**，源 PDF 由外层上传服务器后在正文追加下载链接。
6. 若有缺口：`05_pending_科研通.md`

完成后停止。回信由外层脚本负责，你不用发邮件。
"""


def main():
    if len(sys.argv) < 2:
        sys.exit("用法: run_job.py <task.json>")
    task_path = sys.argv[1]
    task = json.load(open(task_path, encoding="utf-8"))
    cfg = load_config()

    for d in (RUNNING, DONE):
        os.makedirs(d, exist_ok=True)
    # task_path 已是 running/<id>.json（dispatch claim 时移入），它的存在即占一个并发槽

    try:
        topic = task.get("intake", {}).get("topic", "review")
        base_dir = (cfg.get("output") or {}).get("base_dir")
        if not base_dir:
            sys.exit("config 缺 output.base_dir（综述产物落盘目录）")
        # workdir 名带 task id 短码：避免同日同主题的不同任务撞同一目录、互相覆盖
        wd = os.path.join(os.path.expanduser(base_dir),
                          f"{safe_name(topic)}_{datetime.now().strftime('%Y%m%d')}_{task['id'][:8]}")
        for sub in ("", "01_search", "02_pdfs", "03_notes"):
            os.makedirs(os.path.join(wd, sub), exist_ok=True)
        json.dump(task, open(os.path.join(wd, "00_task.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

        prompt = build_prompt(task, wd, cfg)
        open(os.path.join(wd, "00_kimi_prompt.txt"), "w", encoding="utf-8").write(prompt)

        execu = cfg.get("execution") or {}
        kimi = os.path.expanduser(execu.get("kimi_bin") or "")
        sd = os.path.expanduser(execu.get("skills_dir") or "")
        if not kimi or not sd:
            sys.exit("config 缺 execution.kimi_bin 或 execution.skills_dir")
        # config.toml 已 yolo=true；-p 模式禁止再带 --auto/--yolo，故默认空
        flags = execu.get("kimi_flags") or []
        model = execu.get("kimi_model")
        budget = execu.get("job_timeout_sec", 14400)
        max_rounds = execu.get("max_rounds", 5)
        ab = cfg.get("ablesci", {})
        mw = min_words_of(task, cfg)
        CONTINUE = (
            "继续完成上面的文献综述任务，严格按 litreview skill 邮件模式（一次完成、不提问）。"
            "**先复查科研通(ablesci.com)有没有回填的全文：有就下载进 02_pdfs/、精读、补进正文和文献表。**"
            f"确保正文 ≥ {mw} 字、每篇精读文献正文都有实质讨论、围绕「要解决的问题」组织，"
            "直到 02_pdfs/ 有 PDF、04_report.docx、sources.zip、email_body.md 全部产出且达字数再停。")

        def report_done():
            return os.path.exists(os.path.join(wd, "04_report.docx"))

        poll_interval = ab.get("poll_interval_sec", 600)
        pending_path = os.path.join(wd, "05_pending_科研通.md")

        log = open(os.path.join(wd, "00_kimi_run.log"), "w", encoding="utf-8")
        t0 = time.time()
        # resume 循环：-p 跑完没出 docx 就 --continue 续跑，受总预算约束。
        # 科研通是异步的：-p 进程不能自己 sleep 6h，改由本循环跨轮复查——
        # 有 pending 就歇 poll_interval 再 --continue，让下一轮 Kimi 复查回填。
        for rnd in range(max_rounds):
            remaining = budget - (time.time() - t0)
            if remaining < 60:
                log.write(f"\n[run_job] 预算耗尽，停在第 {rnd} 轮\n"); break
            if rnd == 0:
                cmd = [kimi, "-p", prompt, *flags, "--skills-dir", sd]
            else:
                cmd = [kimi, "-p", CONTINUE, "--continue", *flags, "--skills-dir", sd]
            if model:
                cmd += ["-m", model]
            log.write(f"\n===== round {rnd} (剩余 {int(remaining)}s) =====\n"); log.flush()
            try:
                subprocess.run(cmd, cwd=wd, stdout=log, stderr=subprocess.STDOUT,
                               timeout=remaining)
            except subprocess.TimeoutExpired:
                log.write("\n[run_job] 本轮超时\n")
            if report_done():
                log.write(f"\n[run_job] 第 {rnd} 轮已产出 04_report.docx，完成\n"); break
            # 没出报告：若科研通有 pending 且还有预算，歇一会让下一轮复查回填
            if ab.get("enable") and os.path.exists(pending_path) and rnd < max_rounds - 1:
                nap = min(poll_interval, max(0, budget - (time.time() - t0) - 60))
                if nap > 0:
                    log.write(f"\n[run_job] 科研通有 pending，歇 {int(nap)}s 再复查\n"); log.flush()
                    time.sleep(nap)

        # 循环结束仍没有正好叫 04_report.docx：若 Kimi 产了别名 docx（命名漂移），取最大的采用
        if not report_done():
            others = sorted((f for f in os.listdir(wd) if f.lower().endswith(".docx")),
                            key=lambda f: -os.path.getsize(os.path.join(wd, f)))
            if others:
                os.replace(os.path.join(wd, others[0]), os.path.join(wd, "04_report.docx"))
                log.write(f"\n[run_job] 采用 Kimi 产出的 {others[0]} 作为 04_report.docx\n")
        log.close()

        # 回信：判据与循环一致（看 04_report.docx）
        sys.path.insert(0, HERE)
        import send_result
        clarify_path = os.path.join(wd, "00_NEEDS_CLARIFY.md")
        if not report_done() and os.path.exists(clarify_path):
            # Kimi 判定主题/种子/范围有歧义，主动停下：给请求方发澄清信，不发跑偏的综述
            cl_body = open(clarify_path, encoding="utf-8").read()
            log_clar = (f"# 综述任务需确认\n\n收到你的综述请求（主题：{topic}），但有一处需先确认再开工：\n\n"
                        f"{cl_body}\n\n请回复本邮件确认或更正，我据此重新检索撰写。")
            send_result.send_clarify(task, body=log_clar)
        else:
            if not report_done():
                open(os.path.join(wd, "email_body.md"), "w", encoding="utf-8").write(
                    f"# 综述任务未完成\n\n主题：{topic}\n\nKimi 跑完未产出 04_report.docx，请看 `00_kimi_run.log`。"
                    f"耗时 {int(time.time()-t0)}s。")
            send_result.send_result(task, wd)

    finally:
        # 不管成败，移出 running → done，释放并发槽（避免卡死占槽）
        try:
            os.replace(task_path, os.path.join(DONE, os.path.basename(task_path)))
        except OSError:
            pass


if __name__ == "__main__":
    main()
