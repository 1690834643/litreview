# workflow.md — 五阶段详细步骤

## 阶段 1 · 明确方向

### 手动模式 intake 清单（用 grill-me 逐项钉死）
1. **综述主题 / 题目**（必须）—— 一句话能复述的方向。
2. **要解决的问题**（强烈建议）—— 这篇综述要回答的核心问题，全文围绕它组织、首尾呼应。留空则自行从主题提炼。
3. **范围边界** —— 物种 / 基因 / 机制 / 方法的纳入与排除。
4. **时间窗** —— 默认近 10 年优先，奠基性老文献不设限。
5. **重点期刊分区偏好** —— 软筛阈值（如"1区/TOP 优先"），不是硬过滤。
6. **篇数规模** —— 默认分诊 ~60、精读 ~20。
7. **正文字数** —— 默认 ≥ 8000 字（config `review.min_words` / 邮件 `字数:` 可改）。
8. **必读种子文献** —— 用户已知一定要纳入的（DOI/题名）。
9. **输出** —— 文件名 / 落盘目录（默认 Desktop/lit_reviews/<主题>_<日期>/）。

写成 `00_intake.md`。

### 邮件模式
解析正文 `键: 值`（中英冒号都认），字段别名见 `email-trigger/poll_inbox.py` 的 `KEY_ALIASES`。
**只有"主题"缺失才回澄清信**；其余字段缺就用上面默认。绝不追问。

## 阶段 2 · 检索 + 下载

1. `~/.kimi-webbridge/bin/kimi-webbridge status` 确认 daemon `running:true & extension_connected:true`，否则读 kimi-webbridge skill 的 references/operations.md。
2. **构造检索式**：从主题抽关键词 + 同义词 + 物种/基因别名，组布尔式。
3. **广撒网分诊**（Google Scholar + PubMed）：抓 标题/作者/年/期刊/DOI/摘要 → 合并 → `dedupe.py` 去重 → 按相关性×分区粗排，留前 N（intake 篇数）。
4. **拿全文 PDF**：优先出版社 OA / Unpaywall（`https://api.unpaywall.org/v2/<DOI>?email=your-email@example.com`）→ 出版社页（机构登录态）→ Sci-Hub 兜底。存 `02_pdfs/`，文件名 `<第一作者><年>_<短题>.pdf`。
5. **科研通兜底**（见下）。

### 科研通(ablesci.com)异步兜底
- 拿不到全文的 DOI → 用 kimi-webbridge 登录态到科研通发"求助"。
- **轮询等回填**：每 `poll_interval_sec`（默认 600s）查一次"我的求助"是否已有人上传 PDF；
  最多等 `max_wait_sec`（默认 6h）。期间**先把已有全文的精读+综述做着**，别空等。
- **回填后必须真正用上**：新到的 PDF → 下载进 `02_pdfs/` → 精读出笔记 → **补进综述正文与文献表** → 重生成 `04_report.docx` 和 `sources.zip`。科研通求助的文献最终要写进综述，不能只躺在 pending 里。
  （邮件模式下这一步由 run_job 的 resume 循环跨轮驱动：有 pending 就歇 poll_interval 再 `--continue` 唤起复查。）
- 超时仍没到 → 留在 `05_pending_科研通.md`（DOI + 求助链接 + 状态），综述先出，对应文献在表里标"全文待补"。**绝不无限等。**

## 阶段 3 · 精读吸收

- 文本提取：`pdfplumber`（版面规整）或 `fitz`(PyMuPDF)（兜底）。扫描件无文本层 → 标注"仅摘要"。
- 每篇一条结构化笔记（`03_notes/<id>.md`），字段：
  `核心问题 / 数据与方法 / 主要发现(2-4句,非照抄摘要) / 与本综述主题的关系 / 证据强度 / 局限`。
- 手动模式可选：`read-paper` 深批注；Zotero MCP 入库（建以主题命名的 collection）。邮件/Kimi 模式默认用内联笔记；`read-paper` 经 `--skills-dir` 可加载，但 Zotero MCP 仅 Claude 会话可用（Kimi 跳过入库）。

## 阶段 4 · 分区标注

- 收集所有命中文献的**期刊名** → `python scripts/easyscholar_rank.py --file journals.txt --out ranks.json`。
- 字段含义见 `easyscholar.md`。重点取：`sciUp`(中科院大类)、`sciUpSmall`(小类)、`sciUpTop`(TOP)、`sciif`(IF)、`sci`(JCR Q)。
- **缓存**：脚本自动只查新期刊；`--list` 看已知名单。**限速 2 次/秒**已内置。
- 用途三层：① 文献表逐篇标注 ② "高水平论文范围"= 挑高区/TOP 代表作并在综述里分级 ③ 检索阶段排序加权（高区优先，但不硬删）。

## 阶段 5 · 综述成稿

- 结构见 `report-template.md`。中文正文 + 英文术语。
- **写作约束（决定质量）**：
  - 围绕「要解决的问题」组织：开头点题、中间分主题论证、结尾回应。**不要逐篇摘要罗列。**
  - 主题化整合：3-5 个主题轴，跨文献对比综合，而非一篇一段。
  - 每篇精读文献正文都有**实质讨论**（贡献 + 方法/证据强度 + 局限），不能只在文献表里。
  - 每个论断有引用（作者 年）；**不编造数据/结论/引用**；证据不足明说有争议。
  - 显式 `研究空白与矛盾` 一节，指回「要解决的问题」。
  - **正文 ≥ min_words 字**（默认 8000，不含表/参考文献）；不够就把主题轴和 gap 写深，不灌水。
- `build_docx.py` 转 Word（期刊标准字体）。校对：表格渲染对、斜体物种名/基因名、IF/分区数字与 ranks.json 一致。
- `zip_pdfs.py` 打包源 PDF。
- 邮件模式补 `email_body.md`（3-5 句总览 + 文献表摘要 + 高水平范围 + pending）。

## 完成前自检（CLAUDE.md 铁律）
- [ ] docx 能打开、表格/字体正常
- [ ] **正文字数达标**（≥ min_words，不含表/参考文献）
- [ ] 全文围绕「要解决的问题」，有显式 gap 分析并回应该问题
- [ ] 每篇精读文献在正文都有实质讨论（不只在表里）
- [ ] 文献表每篇 IF/分区来自 easyScholar（非编造），与 ranks.json 对得上
- [ ] 必读种子文献都纳入了
- [ ] **科研通已回填的全文已下载、精读并写进正文**（不是只留在 pending）
- [ ] pending 清单如实列出仍没拿到的全文
- [ ] 综述结论有文献支撑，没有悬空断言
