---
name: litreview
description: >
  自动化文献综述工作流：明确方向 → 用浏览器(kimi-webbridge)检索下载文献 → 精读吸收要点 →
  查中科院分区/影响因子(easyScholar) → 生成期刊标准字体的 Word 综述。两种触发：手动触发先用
  grill 访谈钉死方向再跑；邮件触发则按正文模板一次跑完，Word 综述作邮件附件、源 PDF 走服务器给下载链接回信。
  Use when the user wants a literature review / 文献综述 / 综述某主题 / 调研某方向的文献 /
  literature survey / review the literature on X, or mentions 自动综述, litreview, 文献调研报告.
---

# litreview — 自动化文献综述

一句话：把"我想了解某方向的文献"变成一篇**带分区标注、期刊标准字体的 Word 综述** + 源 PDF 压缩包。

## 两种模式（先判断在哪种）

| 模式 | 何时 | 第 1 步方向怎么来 | 跑法 |
|------|------|------------------|------|
| **手动模式** | 用户在 Claude/会话里直接让你做综述 | **调 grill-me** 访谈钉死方向 | 钉完后全自动跑到底 |
| **邮件模式** | 由 `email-trigger/` 经 **Kimi headless 轮值**拉起（正文已带 intake） | **解析邮件正文模板** | **一次完成、不交互**，缺字段用默认；**主题/种子/范围确有歧义则发澄清信确认** |

> 判断依据：如果当前是被 `run_job.py` 的提示词拉起、或上下文给了完整 intake → 邮件模式；否则手动模式。
> 邮件模式 = **Kimi 作为轮值执行器**独自跑完检索/下载/真精读/真实性核查/成稿，编排回信由外层。
> 铁律：默认不向请求方提问、一口气产出；**但意义不明确时（主题缺失/种子文献与主题矛盾/范围自相矛盾）写 `00_NEEDS_CLARIFY.md` 并停下，由外层发澄清信确认，不要硬跑出跑题综述**。

## 五阶段流程（两模式共用，细节见 references/workflow.md）

```
1 明确方向  →  2 检索+下载  →  3 精读吸收  →  4 分区标注  →  5 综述成稿
   grill/      kimi-webbridge   pdf 抽取+      easyScholar    build_docx
   解析邮件     +科研通兜底       结构化笔记      (缓存,2/s)      (期刊字体)
```

### 1 · 明确方向
- 手动模式：**调用 grill-me 技能**，把这些钉死：综述主题/核心问题、范围边界（物种/基因/机制）、时间窗、重点期刊分区偏好、必读种子文献、篇数规模、输出文件名。
- 邮件模式：解析正文 `键: 值`（见 `email-trigger/触发邮件模板.md`），缺主题才回澄清信。
- 产出 `00_intake.md`。

### 2 · 检索 + 下载（kimi-webbridge，见 references/sources.md）
- 先 `~/.kimi-webbridge/bin/kimi-webbridge status` 确认 daemon 健康。
- 入口：**Google Scholar 主** + **PubMed**（生物医学精准）→ 收集标题/摘要/DOI/期刊。
- 全文：出版社页 / Unpaywall / Sci-Hub 拿 PDF；拿不到的 → **科研通(ablesci.com)发求助**（异步，见 workflow.md 的轮询策略）。
- 去重：`python scripts/dedupe.py`（DOI 优先，标题 fallback）。
- 全自动不停（grill/解析定完方向后不再要确认）。PDF 存 `02_pdfs/`。

### 3 · 精读吸收（**真精读，不许脑补**）
- PDF 文本：pdfplumber / PyMuPDF(fitz)。下载后先 `file 02_pdfs/*.pdf` 验真：HTML 当 pdf 存、5KB 级 Cloudflare「Just a moment」桩文件都算失败，必须重抓；抽不出 ≥800 字正文的不得用作精读源。
- 每篇精读文献产一条**填满的**结构化笔记（`03_notes/<键>.md`）：核心问题 / 方法与证据(具体方法+剂量+时间+对照，带原文数字) / 主要发现(带数字) / 与综述主题的关系 / 证据强度 / 局限。**严禁留「待精读补充」占位**；正文每个数字都要能在某篇 `03_notes` 找到出处。
- 手动模式可选增强：调 `read-paper` 深度批注、把 PDF 入 Zotero（MCP）；可用 Workflow/子 agent 并行真读+核实。邮件模式(Kimi 轮值)默认内联结构化笔记；`read-paper` 经 `--skills-dir` 也能加载，但 **Zotero MCP 仅 Claude 会话可用**。

### 4 · 真实性核查（**强制 gate，过不了不许成稿**）
- **检索对题**：选单是否真切"要解决的问题/方法主题"，而非只匹配物种或某热点；跑题文献移出主体、至多作背景。
- **引用核查**：正文每条（作者 年）对应一篇真读过的源；**没拿到/没读的文献不得在文献表编"核心发现"**或凭空给数字；参考文献作者/年/DOI/卷页一律 crossref 核对（第一作者别想当然，文件名常与真一作不符）。
- **数字逐条核**：ID50、感染率、拷贝数、天数等具体值回原文确认存在再写，查无实据则删或改引正确出处。

### 5 · 分区标注 + 下载优先级（先高档次）
- 对每个期刊跑 `python scripts/easyscholar_rank.py "<期刊名>"` → 中科院大类/小类/TOP、JCR、IF。
- **带缓存**：查过的进 `~/.cache/easyscholar/cache.json`，只查新的；接口**限速 2 次/秒**（脚本已 throttle+退避）。
- 用法：① 文献表每篇标 IF/分区 ② 定"高水平论文范围"（挑代表作、分级）③ **检索/下载阶段先抓高档次**。
- **下载优先高档次**：高档次论文即使主题不完全相干，其严谨方法学/逻辑也能帮到来信者，可作"方法学借鉴"纳入。农林科学高档次判据：**Nature Communications / Science Advances / PNAS** 等综合·方法学强刊即算；**中科院一区且 IF ≥ 5** 算。先抓高档次；低档次仅"强相关"或"经典奠基"才纳入，别为凑数塞低相关低档次。

### 6 · 综述成稿
- **写作质量（别写差）**：逻辑优先、一段一义、一句一论点，写精瘦不灌水；**严禁第二人称"你/你课题"**，用客观第三人称；去 AI 腔（不滥用"不是X而是Y"/"值得注意的是"/表演式铺垫/空泛排比）；claim 用"表明/提示/可能"校准；英文 American English、正文不用英文 em-dash；物种/基因名斜体。
- 写 Markdown 综述：中文正文 + 英文术语；主题化叙述 + gap 分析 + **文献对比表**（含 IF/分区，见 references/report-template.md）。
- 转 Word：`python scripts/build_docx.py review.md -o 04_report.docx --title "<题>"` —— **期刊标准字体**（正文 Times New Roman + 宋体；标题 黑体；表格五号；行距 1.5）。
- 源 PDF 压缩：`python scripts/zip_pdfs.py 02_pdfs --outdir . --max-mb 100000` → `sources.zip`（打一个包）。邮件模式由 `send_result.py` 投递：**服务器是可选的**——`delivery.pdf_via: server` 上传换 https 下载链接（需配 host/ssh/域名），`pdf_via: none`（或服务器未配齐）则源 PDF 仅留本地 `sources.zip`、回信只带 Word 附件不含链接。
- 邮件模式额外写 `email_body.md`（回信正文）+ `05_pending_科研通.md`（缺口）。

## 工具映射（编排，不重造轮子）
| 环节 | 用什么 |
|------|--------|
| 明确方向(手动) | **grill-me** 技能 |
| 浏览器检索/下载/科研通 | **kimi-webbridge**（curl `127.0.0.1:10086`） |
| 分区/IF | `scripts/easyscholar_rank.py`（easyScholar API + 缓存） |
| 去重 | `scripts/dedupe.py` |
| PDF 文本 | pdfplumber / PyMuPDF |
| 深读(可选,手动) | **read-paper** 技能 |
| 文献入库(可选,手动) | **Zotero MCP** |
| 综述转 docx | `scripts/build_docx.py`（+ pandoc） |
| 源 PDF 压缩 | `scripts/zip_pdfs.py` |
| 邮件触发/回信 | `email-trigger/`（IMAP 轮询 + Kimi 派发 + email-sender） |

## 落盘
每个综述一个目录：`/path/to/lit_reviews/<主题>_<日期>/`
含 `00_intake.md · 01_search/ · 02_pdfs/ · 03_notes/ · 04_report.docx · sources.zip · 05_pending_科研通.md`。

## 邮件触发系统（无人值守）
见 `email-trigger/`：WSL 系统 cron 每几分钟轮询 QQ 邮箱 → 命中 `[综述]`前缀+暗号 的邮件 →
起 Kimi headless job（并发≤3）→ 跑完整流程 → Word 综述作邮件附件、源 PDF 上传服务器（nginx `/litdl/` → `https://<域名>/litdl/<随机token>/`）给下载链接回信（**服务器可选，见上**）。
安装：`bash email-trigger/install_cron.sh 5`（WSL 还需 `sudo service cron start`）。配置：复制 `config.example.yaml`→`config.yaml` 按需改。给同门：`email-trigger/触发邮件模板.md`。
依赖技能（需一起装）：**kimi-webbridge**（必需，检索下载）、**email-sender**（邮件模式必需，邮箱凭据）、**grill-me**（手动模式钉方向）、**read-paper**（可选深读）。

## 铁律（CLAUDE.md 对齐）
- **真精读**：每篇精读文献必有填满的 `03_notes`，正文数字回原文有据；空模板/脑补=未完成。
- **报 done 前核对产出内容**：摘真实文献条目、确认 docx 能开、分区数字来自接口而非编造、引用元数据 crossref 核过。
- **真实性核查 gate**（详见 §4 与 `run_job.py` 提示词的"真实性核查"段）：检索对题、引用全部对应真读源、没读的不编核心发现、具体数值逐条核。
- **歧义不硬跑**：主题/种子/范围确有矛盾就写 `00_NEEDS_CLARIFY.md` 停下发澄清信，别跑出跑题综述。
- **回信抄送**：`config.yaml` 的 `reply.cc`（默认 your-email@example.com）每封回信/澄清信都抄送，管理员才知道发了什么。
- 中文对话直接表达，学术英文 American English、不用 em-dash。
- 别把低相关文献硬塞进综述；"高水平论文范围"用真实分区数据界定。
