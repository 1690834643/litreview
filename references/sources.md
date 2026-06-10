# sources.md — 用 kimi-webbridge 检索与下载

全程用 kimi-webbridge（curl `http://127.0.0.1:10086/command`）驱动**用户真实浏览器+登录态**，
这样能过机构付费墙、不被 Scholar 限流。先 `~/.kimi-webbridge/bin/kimi-webbridge status` 确认健康。

调用范式（详见 kimi-webbridge skill 的 references/operations.md）：
```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"navigate","args":{"url":"<URL>","newTab":true},"session":"litreview"}'
# 然后 snapshot 读可访问性树、click/fill 交互、evaluate 取结构化数据
```
**给每个综述任务用独立 session 名**（如 `litreview-<id>`），并发互不干扰。

## 检索入口

### Google Scholar（主入口，覆盖广）
- `https://scholar.google.com/scholar?q=<检索式>&hl=en`
- snapshot 取每条的 标题/作者/年/来源；点 "All N versions" 或 "[PDF]" 找免费全文。
- 翻页 `&start=10/20/...`。注意限流：失败就降速、换 session。

### PubMed（生物医学精准 + 干净元数据）
- 检索：`https://pubmed.ncbi.nlm.nih.gov/?term=<检索式>`
- 元数据更规整（DOI/PMID/期刊全称）。也可走 eutils（无需浏览器）：
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=<...>&retmode=json`
  → `efetch.fcgi?db=pubmed&id=<PMIDs>&retmode=xml` 拿题录。

## 拿全文 PDF（按优先级，端点经实测，2026-06）

铁律：**下完必校验是真 PDF**——首字节 `%PDF`、大小 > ~40 KB、能抽出 > 800 字正文。HTML 网页存成 `.pdf`、或 ~5 KB 的 Cloudflare「Just a moment…」拦截页都算失败。命名 `<第一作者><年>_<短题>.pdf`，存 `02_pdfs/`。

**Tier 1 — 出版社 OA 直链（纯 HTTP，最快，✅实测可用）**
- Frontiers：`https://www.frontiersin.org/articles/<DOI>/pdf` ✅
- PLoS：`https://journals.plos.org/<刊>/article/file?id=<DOI>&type=printable` ✅
- Nature 系 OA（`s41…`）：`https://www.nature.com/articles/<id>.pdf` ✅
- **MDPI**：`…/pdf` 直拉 **403**（❌实测）→ 走 Tier 5 真浏览器。
- 各源之间 sleep 2–4 s。

**Tier 2 — OA 聚合 API**
- Unpaywall：`https://api.unpaywall.org/v2/<DOI>?email=your-email@example.com` → `best_oa_location.url_for_pdf`（每次 ≥ 0.5 s；个别 DOI 未索引会 404）。
- **Europe PMC（反爬最友好，强烈优先）**：先 `…/search?query=DOI:"<DOI>"&format=json&resultType=core` 取 `pmcid`，再
  - 正文 XML（**精读够用，比解析 PDF 干净**）：`https://www.ebi.ac.uk/europepmc/webservices/rest/<PMCID>/fullTextXML` ✅实测
  - PDF：`…/<PMCID>/fullTextPDF`（部分 OA 才有，常 404，拿不到就用 XML 读）。

**Tier 3 — PMC（域名已迁移，且需浏览器）**
- 新域名 `https://pmc.ncbi.nlm.nih.gov/articles/<PMCID>/pdf/`（旧 `www.ncbi.nlm.nih.gov/pmc/…` 已 404）。
- ❌实测：urllib 直拉报 `SSL: UNEXPECTED_EOF` 或返回中转 HTML → 改 Tier 5 真浏览器。

**Tier 4 — Sci-Hub 兜底**：镜像 `sci-hub.se/.st/.ru/.wf` + `/<DOI>`，取页面 `iframe`/`embed` 的 `.pdf`。新文献/Cloudflare 失败率高，失败即转 Tier 5/6。

**Tier 5 — kimi-webbridge 真浏览器（过 Cloudflare/付费墙/PMC，✅动作实测可用）**
用用户真实登录态。核心动作（POST `http://127.0.0.1:10086/command`，`{"action":..,"args":..,"session":"litreview-<id>"}`）：
- `navigate {url,newTab}`、`snapshot`（取可访问性树 + `@e` 元素 ref）、`fill {selector,value}`、`click {selector}`（`@e` ref 或 CSS）、`evaluate {code}`、`screenshot`（用 skill 的 `scripts/screenshot.sh` 存盘，别直接调 API）。
- 定位元素：先 `snapshot` 拿 `@e` ref，再对 ref 做 `click`/`fill`（比 `evaluate` 改 `.value` 可靠，能触发框架事件）。
- `evaluate` 的 code 是**表达式**，不能有顶层 `return`；要 await 用 async IIFE：`(async()=>{ …; return x; })()`。
- 下 PDF 两法：① navigate 到 PDF 链接，浏览器自动下到 `~/Downloads`（再 `mv` 进 `02_pdfs/`）；② 同源 `evaluate` 跑 `fetch(URL,{credentials:'include'})→blob→<a download>.click()`（绕 CORS）。

**Tier 6 — 科研通求助（近实时，中文/CNKI/付费墙首选；见下）**

## 科研通(ablesci.com) 求助 —— 近实时，发了等上传即可（流程实测 2026-06）

> **求助几乎是实时的**：发布后通常几分钟内就有人应助上传，**不是异步等几小时**。正确做法＝"发起 → 等几分钟 → 取回填 PDF"，**不是**直接甩进 pending 不管。中文文献（CNKI 的《昆虫知识》《植物保护》等）、付费墙文献，科研通常比 Sci-Hub 靠谱。

**前提：浏览器须登录 ablesci**（本机已登录为「your-username」）。`navigate` 到 `assist/create` 后看页面是否出现用户名即可确认；未登录只能写 pending。

**发求助（实测表单 + 关键门槛）**：
- `navigate https://www.ablesci.com/assist/create`，`snapshot` 取 ref。实测：「智能提取文献信息」按钮 ＝ 文本含 `智能提取`、「立即发布」按钮文本 ＝ `立即发布`。
- `fill #onekey` ＝ DOI/PMID/标题 → `click` 智能提取按钮 → **等 8–15 s**。
- ⚠️ **必须等智能提取成功回填 `#Assist-title`（和 `#Assist-doi`）后才能提交**：科研通服务端校验文献真实存在，靠"智能提取"回填隐藏元数据。**实测**：若只用 `fill`/`evaluate` 硬填 doi/title 跳过智能提取、或智能提取没回填就点「立即发布」，会被「请…」校验拦下、提交失败（不扣分）。
- 智能提取成功后：`#Assist-point`（悬赏积分）默认 10，`Assist[type]`（文献类型，默认 type=1 期刊）→ `click` 立即发布 → 记下跳转的求助详情 URL `https://www.ablesci.com/assist/detail?id=<ID>`（这才是真求助链接，别在 pending 里填首页占位）。多篇用页面「批量求助 beta」。
- 若智能提取反复回填失败（如出版社元数据源没命中该 DOI），不要硬提交：把该文留给 `05_pending_科研通.md`，或换标题/PMID 重试。

**取件（近实时）**：每 1–3 分钟 `navigate https://www.ablesci.com/my/assist-my`（我的求助）或该 `assist/detail?id=<ID>` 页，看「已应助/有附件」→ 下载 PDF 进 `02_pdfs/`，校验后精读补 `03_notes` 与正文。期间别空等，先做已有全文。几分钟仍无人应助再落 `05_pending`（含真实 `assist/detail` 链接 + 时间），交后续 `--continue` 轮次复查。

## 反爬 / 限流 / 礼貌等待（具体时长）
- **API 类**（Unpaywall/crossref/Europe PMC/eutils）：每次 ≥ 0.3–1 s；crossref 带 `mailto=` 进礼貌池。
- **出版社页**：每次 2–5 s + 少量随机抖动。
- **Google Scholar**：每查 5–10 s、翻页别超几页；**出验证码立即停**，转 PubMed/eutils 或真浏览器。
- **遇 403/429/Cloudflare**：指数退避（5→15→30 s），仍不行换 kimi-webbridge 真浏览器或换 `session` 名。
- **大文件/多连接**：下完校验 md5/大小，段损坏重试自愈（参照 aria2 经验）。
- **科研通**：智能提取后等 8–15 s 再提交；取件轮询 1–3 min/次；别短时间连发大量求助（按规范、省积分）。
- 不在日志里留任何登录凭据/cookie。
