# easyscholar.md — 分区/影响因子接口

## 接口
`GET https://www.easyscholar.cc/open/getPublicationRank?secretKey=<KEY>&publicationName=<期刊名>`
- `secretKey` 存 `~/.config/easyscholar/key.txt`（repo 外，已 gitignore），脚本自动读，**不要硬编码进代码**。
- **限速约 2 次/秒**；超了返回 `code: 40006 请求频繁`。脚本 `easyscholar_rank.py` 已做 0.6s throttle + 指数退避重试。

## 返回结构（实测）
```
{"code":200,"msg":"SUCCESS","data":{"officialRank":{"all":{...}}, "customRank":{...}}}
```
`data.officialRank.all` 关键字段（其余高校自定义分区 swjtu/xju/cug/scu/cpu/hhu 忽略）：

| 字段 | 含义 | 例 |
|------|------|----|
| `sciUp` | **中科院分区升级版·大类** | 农林科学1区 |
| `sciUpSmall` | 中科院·小类 | 昆虫学1区/生化与分子生物学2区 |
| `sciUpTop` | 中科院 TOP 标记 | 农林科学TOP |
| `sciBase` | 中科院基础版·大类 | 农林科学2区 |
| `sciif` | **最新影响因子** | 3.7 |
| `sciif5` | 5 年 IF | 4.1 |
| `sci` | **JCR 分区** | Q1 |
| `jci` | Journal Citation Indicator | 1.25 |
| `esi` | ESI 学科 | 植物与动物科学 |

## 综述里怎么用（后置标注 + 前置软筛，grill 决策）
1. **逐篇标注**：文献对比表每行写 `中科院大类(+TOP) · JCR · IF`，用 `sciUp`/`sciUpTop`/`sci`/`sciif`。
2. **定"高水平论文范围"**：综述单列一节，把 1区/TOP 的代表作挑出来分级讨论。
3. **前置软筛**：检索排序时高区加权优先，但**不硬删低区/老牌专业期刊的经典文献**（会漏奠基工作）。

## 脚本用法
```bash
python scripts/easyscholar_rank.py "Insect Science" "Molecular Ecology"   # 直接查
python scripts/easyscholar_rank.py --file journals.txt --out ranks.json   # 批量→JSON
python scripts/easyscholar_rank.py --list                                  # 看缓存已知名单
python scripts/easyscholar_rank.py --no-live "X"                           # 只用缓存
```
- **缓存**：`~/.cache/easyscholar/cache.json`，查过的不再走接口（省限速额度）。期刊名大小写/末尾点号自动归一。
- 期刊名尽量用全称；缩写（如 "GBE"）可能匹配不到，匹配失败会标 error，换全称重试。
