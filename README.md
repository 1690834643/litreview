# litreview — 自动化文献综述 skill

把"我想了解某方向的文献"变成一篇**带中科院分区标注、期刊标准字体的 Word 综述** + 源 PDF 压缩包。

适用于 Claude Code / Kimi Code 等支持 skill（`--skills-dir`）的 agent CLI。检索、下载、**逐篇真精读**、查分区、成稿全自动；可挂邮件触发，同门发一封邮件即得一篇综述。

> 这是个人科研工具的脱敏开源版：真实邮箱/服务器/暗号/路径已替换为占位符；本地真实配置（`config.yaml`）与运行态（`state/`）已被 `.gitignore` 排除，**切勿提交**。

## 工作流（5 阶段 + 真实性核查）

```
1 明确方向 → 2 检索+下载 → 3 真精读 → 4 真实性核查 → 5 分区/下载优先级 → 6 成稿
  grill/解析    kimi-webbridge   pdf抽取+      强制gate      easyScholar         build_docx
  邮件          +科研通近实时     结构化笔记     (引用/数字)    (先抓高档次)         (期刊字体)
```

- **主题化综述**，非逐篇摘要罗列；带 gap 分析 + 文献对比表（每篇标 IF/分区）。
- **真精读**：每篇精读文献产一条填满的 `03_notes/`，正文每个数字可回溯原文；禁空模板脑补。
- **真实性核查（强制）**：每条引用对应真读过的源；没读的不编"核心发现"；参考文献作者/DOI/卷页 crossref 核对；数值逐条回原文。
- **下载优先高档次**：高档次论文即便主题不完全相干，其严谨方法学/逻辑也有借鉴价值。农林科学里 Nature Communications / Science Advances / PNAS、以及中科院一区且 IF≥5 算高档次。
- **写作质量约束**：逻辑优先、一段一义、客观第三人称、去 AI 腔、claim 有界、英文 American English 不用 em-dash。

## 两种触发模式

| 模式 | 何时 | 跑法 |
|------|------|------|
| **手动** | 在 agent 会话里直接让它做综述 | 先用 `grill-me` 访谈钉死方向，再全自动跑到底 |
| **邮件** | `email-trigger/` 经 cron + Kimi headless 拉起 | 解析邮件正文模板一次跑完；主题/种子/范围有歧义则回澄清信 |

## 需要一起安装的 skills

litreview 只做编排，能力来自这些**配套 skill / 服务**（按需安装到 agent 的 skills 目录）：

| Skill / 能力 | 必需性 | 用途 | 手动模式 | 邮件模式 |
|---|---|---|---|---|
| **litreview**（本仓库） | ✅ 必需 | 主工作流 | ✅ | ✅ |
| **kimi-webbridge** | ✅ 必需 | 真实浏览器检索/下载（过 Cloudflare/付费墙），守护进程 `http://127.0.0.1:10086` | ✅ | ✅ |
| **easyScholar**（API，非 skill） | ✅ 必需 | 期刊→中科院分区/IF；需 key（见下） | ✅ | ✅ |
| **email-sender** | 邮件模式必需 | 提供 IMAP/SMTP 邮箱凭据 | — | ✅ |
| **grill-me** | 手动推荐 | 访谈钉死综述方向 | ✅ | — |
| **read-paper** | 可选 | 深度批注增强 | 可选 | — |
| **科研通账号**（ablesci.com） | 可选兜底 | 浏览器登录后求助中文/CNKI/付费墙文献（近实时） | 可选 | 可选 |
| 一台带证书域名 + nginx 的服务器 | **可选** | 仅邮件模式把源 PDF 换 https 下载链接；不要也行（见"上传服务器是可选的"） | — | 可选 |

> Claude Code 装到 `~/.claude/skills/<name>/`；Kimi Code 装到对应 skills 目录（`config.yaml` 的 `execution.skills_dir`）。

## 安装

```bash
# 1) 放进 agent 的 skills 目录
git clone <this-repo> ~/.claude/skills/litreview      # Kimi 用其 skills 目录

# 2) 系统依赖（docx 转换用 pandoc）
sudo apt-get install -y pandoc       # Debian/Ubuntu
# brew install pandoc                # macOS

# 3) Python 依赖（建议 Python ≥ 3.8）
pip install python-docx pdfplumber pymupdf pyyaml requests

# 4) easyScholar key（查分区/IF，必需；不入库）
mkdir -p ~/.config/easyscholar
echo "你的_secretKey" > ~/.config/easyscholar/key.txt    # 或 export EASYSCHOLAR_KEY=...
```

手动模式装好上面即可用：在会话里说"用 litreview 综述 XXX 方向"。

## 邮件触发部署（无人值守，可选）

```bash
cd email-trigger
cp config.example.yaml config.yaml      # 改成你的真实值；config.yaml 已被 .gitignore
bash install_cron.sh 5                   # 每 5 分钟轮询一次
```

`config.yaml` 关键项见 `config.example.yaml` 注释：触发暗号 `secret_token`、并发数、`execution.kimi_bin`/`skills_dir`（`which kimi` 查路径）、`mailbox.creds_from`（指向已部署的 email-sender 配置）、产物落盘 `output.base_dir`、回信抄送 `reply.cc`、源 PDF 投递 `delivery`、科研通开关。

### WSL 下启动 cron

WSL 默认 cron 服务可能没起。`install_cron.sh` 末尾若提示 ⚠️：

```bash
sudo service cron start          # 启动（WSL 一次启动后会持续运行，不必每次重复）
sudo service cron status         # 验证
crontab -l | grep litreview      # 确认任务已装
```

### 上传服务器是可选的

`delivery.pdf_via` 决定源 PDF 怎么给用户：
- `server`：上传到远程 nginx 静态目录，回信给 https 下载链接（需配齐 `host/ssh_*/remote_dir/base_url`）。
- `none`（或服务器字段没配齐）：**不上传**，源 PDF 仅本地存于 `output.base_dir/<任务>/sources.zip`，回信只带 Word 附件、不含链接。**没有服务器就用 `none`**，功能照常（缺字段时代码也会自动降级为不投递，不报错）。

流程：cron → `dispatch.py` 轮询邮箱（命中 `[综述]`前缀 + 暗号）→ `run_job.py` 起 Kimi headless 跑完整流程 → Word 综述作邮件附件、源 PDF 按 `pdf_via` 投递、回信并抄送 `reply.cc`。给同门的发信说明见 `email-trigger/触发邮件模板.md`。

## 下载方法（按优先级，端点经实测）

1. 出版社 OA 直链：Frontiers `/<DOI>/pdf`、PLoS `file?id=<DOI>&type=printable`、Nature OA `/<id>.pdf`。
2. OA 聚合：Unpaywall API、**Europe PMC**（`fullTextXML` 精读够用，反爬最友好）。
3. PMC（新域名 `pmc.ncbi.nlm.nih.gov`，多需真浏览器）。
4. Sci-Hub 兜底。
5. **kimi-webbridge 真浏览器**（过 Cloudflare/付费墙/MDPI）：`navigate`/`snapshot`(取 `@e` ref)/`fill`/`click`/`evaluate`；`references/sources.md` 有"出版社页下载实操（一步步可照做）"的完整 curl 示例。
6. **科研通求助（近实时）**：登录后 `assist/create` → 填 DOI/PMID/标题 → 智能提取（须回填成功才能提交）→ 立即发布 → 几分钟后到 `my/assist-my` 取回填 PDF。

详见 `references/sources.md`，含反爬/限流的具体等待时长。

## 目录结构

```
SKILL.md                 # 主入口：流程/铁律/工具映射
references/
  sources.md             # 检索与下载（kimi-webbridge 动作、出版社下载实操、科研通流程、反爬等待）
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

- `config.yaml`（真实 token/服务器/SSH/邮箱凭据）与 `state/`（含真实邮件 message-id/主题/日志）已被 `.gitignore` 排除。
- easyScholar key、邮箱授权码均从库外路径/环境变量读取，不写进代码。
- 配置缺字段时代码给友好报错并降级，不会泄露或崩溃；部署到公开仓库前请再 `grep` 一遍自己的真实信息。

## 许可

MIT License（详见 [LICENSE](LICENSE)）。本工具编排现成能力（kimi-webbridge / easyScholar / pandoc / email-sender），请遵守各数据源与出版社的使用条款；文献求助按平台规范、勿滥用。
