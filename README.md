# litreview — 自动化文献综述 skill

把"我想了解某方向的文献"变成一篇**带中科院分区标注、期刊标准字体的 Word 综述** + 源 PDF 压缩包。

适用于 Claude Code / Kimi Code 等支持 skill（`--skills-dir`）的 agent CLI。检索、下载、**逐篇真精读**、查分区、成稿全自动；可挂邮件触发，同门发一封邮件即得一篇综述。

> 这是一个个人科研工具的脱敏开源版。所有真实邮箱 / 服务器 / 暗号 / 路径已替换为占位符，本地真实配置（`config.yaml`）和运行态（`state/`）已被 `.gitignore` 排除。

## 它怎么工作（5 阶段 + 真实性核查）

```
1 明确方向 → 2 检索+下载 → 3 真精读 → 4 真实性核查 → 5 分区标注/下载优先级 → 6 成稿
  grill/解析    kimi-webbridge   pdf抽取+      强制gate      easyScholar          build_docx
  邮件          +科研通近实时     结构化笔记     (引用/数字)    (先抓高档次)          (期刊字体)
```

- **主题化综述**，不是逐篇摘要罗列；带 gap 分析 + 文献对比表（每篇标 IF/分区）。
- **真精读**：每篇精读文献产一条填满的结构化笔记（`03_notes/`），正文每个数字都能回溯到原文；严禁空模板脑补。
- **真实性核查（强制）**：正文每条引用对应真读过的源；没读的不编"核心发现"；参考文献作者/DOI/卷页一律 crossref 核对；ID50/感染率/天数等数值逐条回原文核实。
- **下载优先高档次**：高档次论文即便主题不完全相干，其严谨方法学/逻辑也有借鉴价值。农林科学里 Nature Communications / Science Advances / PNAS 等、以及中科院一区且 IF≥5 算高档次，优先抓。
- **写作质量约束**：逻辑优先、一段一义、客观第三人称、去 AI 腔、claim 有界、英文 American English 不用 em-dash。

## 两种触发模式

| 模式 | 何时 | 跑法 |
|------|------|------|
| **手动** | 在 agent 会话里直接让它做综述 | 先用 `grill-me` 访谈钉死方向，再全自动跑到底 |
| **邮件** | `email-trigger/` 经 cron + Kimi headless 轮值拉起 | 解析邮件正文模板，一次跑完；主题/种子/范围有歧义则回澄清信 |

## 安装

```bash
# 放进 agent 的 skills 目录
git clone <this-repo> ~/.claude/skills/litreview   # Kimi 用 ~/.kimi-code 或对应 skills 目录

# Python 依赖
pip install python-docx pdfplumber pymupdf pyyaml requests
# 系统依赖：pandoc（docx 转换）
```

### 依赖的外部能力
- **kimi-webbridge**（必需）：用用户真实浏览器+登录态检索/下载，过 Cloudflare/付费墙。守护进程在 `http://127.0.0.1:10086`。
- **easyScholar API key**（必需，查分区/IF）：写入 `~/.config/easyscholar/key.txt` 或环境变量 `EASYSCHOLAR_KEY`（**不入库**）。
- **email-sender skill**（仅邮件模式）：提供 QQ 邮箱 IMAP/SMTP 凭据；`config.yaml` 的 `mailbox.creds_from` 指向它。
- **科研通账号**（可选兜底）：浏览器需登录 ablesci.com；中文/CNKI/付费墙文献求助近实时。
- 一台带证书域名 + nginx 静态目录的服务器（可选，仅用于邮件模式把源 PDF 换成下载链接）。

## 邮件触发部署（无人值守）

```bash
cd email-trigger
cp config.example.yaml config.yaml      # 改成你的真实值（token/邮箱/服务器/路径）
bash install_cron.sh 5                   # 每 5 分钟轮询一次；WSL 记得 sudo service cron start
```

`config.yaml`（**绝不提交**）关键项见 `config.example.yaml` 注释：触发暗号 `secret_token`、并发数、Kimi 路径、产物落盘目录、回信抄送 `reply.cc`、源 PDF 服务器投递、科研通开关。

流程：cron → `dispatch.py` 轮询邮箱（命中 `[综述]`前缀 + 暗号）→ `run_job.py` 起 Kimi headless 跑完整流程 → Word 综述作邮件附件、源 PDF 上传服务器换 https 下载链接回信（并抄送管理员）。给同门的发信说明见 `email-trigger/触发邮件模板.md`。

## 下载方法（按优先级，端点经实测）

1. 出版社 OA 直链：Frontiers `/<DOI>/pdf`、PLoS `file?id=<DOI>&type=printable`、Nature OA `/<id>.pdf`。
2. OA 聚合：Unpaywall API、**Europe PMC**（`fullTextXML` 精读够用，反爬最友好）。
3. PMC（新域名 `pmc.ncbi.nlm.nih.gov`，多需真浏览器）。
4. Sci-Hub 兜底。
5. **kimi-webbridge 真浏览器**（过 Cloudflare/付费墙/MDPI）：`navigate`/`snapshot`(取 `@e` ref)/`fill`/`click`/`evaluate`。
6. **科研通求助（近实时）**：登录后 `assist/create` → 填 DOI/PMID/标题 → 智能提取（须回填成功才能提交）→ 立即发布 → 几分钟后到 `my/assist-my` 取回填 PDF。

详见 `references/sources.md`，含反爬/限流的具体等待时长。

## 目录结构

```
SKILL.md                 # 主入口：流程/铁律/工具映射
references/
  sources.md             # 检索与下载（含 kimi-webbridge 动作、科研通流程、反爬等待）
  workflow.md            # 两模式细节
  report-template.md     # 综述 docx 结构 + 文献对比表
  easyscholar.md         # 分区接口说明
scripts/
  build_docx.py          # md → 期刊标准字体 docx（pandoc + python-docx 模板）
  easyscholar_rank.py    # 期刊 → 中科院分区/IF（带缓存，key 从库外读）
  dedupe.py / zip_pdfs.py
email-trigger/
  dispatch.py poll_inbox.py run_job.py send_result.py
  install_cron.sh  config.example.yaml  触发邮件模板.md
assets/journal_reference.docx
```

## 安全说明

- `config.yaml`（真实 token/服务器/SSH/邮箱凭据）与 `state/`（含真实邮件 message-id/主题/日志）已被 `.gitignore` 排除，**切勿提交**。
- easyScholar key、邮箱授权码均从库外路径/环境变量读取，不写进代码。
- 部署到公开仓库前请再 `grep` 一遍自己的真实信息。

## 许可

MIT。本工具编排现成能力（kimi-webbridge / easyScholar / pandoc / email-sender），不重造轮子；请遵守各数据源与出版社的使用条款，文献求助按平台规范、勿滥用。
