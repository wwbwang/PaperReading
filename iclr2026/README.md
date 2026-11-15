# ICLR 2026 历史快照（归档）

当前网站同时提供 ICLR 2026 和 2027；[进入 2026 论文库](http://localhost:8000/iclr/2026/)。本文保留 2026 历史快照说明，请使用该年份原始 0–10 分尺度。构建时指定 `--year 2026` 只更新该年份，保留另一年份和首页入口。

维护 ICLR 2026 主会全部公开投稿的标题、英文摘要、OpenReview 页面、PDF 链接及逐审稿人评分，包括录用、拒稿、撤稿和直接拒稿记录。

## 当前快照

截至北京时间 **2026-11-15**，已保存主会 **19,814** 篇论文和 **75,858** 条审稿评分记录。标题、摘要和论文链接无空值；**340** 篇没有评分，保留为空。记录中 **1,318** 个 `0` 分被保留，参与均分计算，不能当成缺失值。

| 快照状态 | 篇数 |
| --- | ---: |
| Poster | 5,127 |
| Oral | 224 |
| Reject | 8,345 |
| Withdraw | 5,210 |
| Desk Reject | 908 |

**当前数据来自第三方公开镜像，不是本次从 OpenReview 官方接口直接抓取的结果。** 官方接口实际返回浏览器验证错误（HTTP 403），此前探测还遇到 HTTP 429。失败信息保存在 `iclr2026/raw/last_error.json`。已抓取镜像中的全部主会记录，并逐条核对导出结果，但尚未通过官方接口确认是否覆盖其所有公开投稿。

镜像来自 [Paper Copilot paperlists](https://github.com/papercopilot/paperlists)，固定到提交 [`c1972ecffe42c402c3b840052d65a9d2159df6ae`](https://github.com/papercopilot/paperlists/commit/c1972ecffe42c402c3b840052d65a9d2159df6ae)，提交时间为 `2026-11-14T05:50:40Z`。此时间是镜像提交时间；原始采集时间未知。下载内容已与该提交的 Git LFS SHA-256 和文件大小核对。

官方回顾报告的“有效、格式合规投稿”是 19,525 篇，口径不同于镜像中的公开记录；不要把两者直接作为覆盖率的分母、分子。官方回顾也报告了 5,357 篇录用论文，镜像当前 Poster/Oral 合计 5,351 篇，差异原因尚未核实，因此不能把快照当作经官方逐篇核对的最终录用名单。参见 [ICLR 2026 审稿回顾](https://blog.iclr.cc/2026/03/31/a-retrospective-on-the-iclr-2026-review-process/)。

## 文件

| 文件 | 用途 |
| --- | --- |
| `iclr2026/papers.csv` | Excel、表格软件可直接打开的论文主表，UTF-8 BOM 编码 |
| `iclr2026/papers.jsonl` | 每行一篇论文，包含完整的 `reviews` 数组 |
| `iclr2026/reviews.csv` | 每行一位匿名审稿人的评分，以 `paper_id` 关联论文 |
| `iclr2026/manifest.json` | 来源、数量、缺失情况、范围及导出文件 SHA-256 |
| `iclr2026/validation.json` | 全量核对结果 |
| `iclr2026/raw/papercopilot.json` | 原始镜像，约 104.5 MiB，含主会及 workshop 共 22,748 条记录 |
| `iclr2026/raw/papercopilot_source.json` | 镜像固定版本、下载时间和原始文件 SHA-256 |
| `iclr2026/raw/last_error.json` | 最近一次抓取失败记录；成功导出镜像不会抹去官方访问失败记录 |
| `scripts/sync_iclr.py --year 2026` | 官方抓取、镜像抓取和标准化导出 |
| `scripts/validate_iclr.py iclr2026` | 从原始镜像到导出表的全量独立核对 |

原始镜像中额外的 2,934 条 workshop 记录不混入主会表。需要时可通过下方命令单独导出全部 track。

## 字段约定

- `id`：OpenReview forum ID，是论文主键。
- `title`、`abstract`：来源中的英文标题和摘要，未翻译、未总结。
- `paper_url`：论文讨论页；`pdf_url`：按 forum ID 构造的官方 PDF 地址。链接已保存，但未批量验证每个 PDF 是否仍可下载。
- `status`、`track`：来源的状态和分会场，保留原值。`Withdraw` 不能视为拒稿，`Poster`、`Oral` 表示镜像记录的录用状态。
- `ratings`：与 `reviews` 按位置对应的评分数组。`0` 是数值；缺失值在 JSON 中为 `null`，CSV 中为空。
- `review_count`：审稿记录数；`rating_count`：非空评分数；`rating_mean`：非空评分的简单算术平均；`rating_missing`：没有任何非空评分。
- `reviews`：逐审稿人记录，保留匿名代号、总评分以及 confidence、soundness、presentation、contribution 等字段。`confidence` 是审稿人的自报把握程度，不是本数据的可信度。
- `*_raw`：来源中的原始分值。镜像仅含数值字符串，不包含官方评分的完整文字标签。`review_id`、`review_url` 在镜像数据中为空，因为镜像没有提供 review note ID，不能杜撰。
- `retrieved_at`：本地获取并校验该来源快照的时间，使用带时区的 UTC ISO 8601 格式，不代表论文或评分修改时间。

评分是来源快照中的值，不是逐轮评分历史。ICLR 2026 在安全事件后将评审及评分回退到 rebuttal 前状态，不能将这些分数直接解释为“经过讨论的最终评分”；见上述官方回顾。

## 更新与复现

脚本仅使用 Python 3.10+ 标准库，不需要 API 密钥或第三方 Python 依赖。命令在当前仓库根目录执行。

优先从官方接口抓取全部公开主会投稿及其官方评审：

```bash
python scripts/sync_iclr.py --year 2026 --source openreview --no-env-proxy
```

脚本按 `ICLR.cc/2026/Conference/-/Submission` 分页查询，包含 `directReplies`，仅提取 `Official_Review`，不会将作者回复、公众评论或 meta-review 当作审稿评分。官方分页保存到 `raw/openreview/`，中断后可重跑以复用已下载页。完整性检查要求唯一论文数与 API 返回总数一致；该确认只覆盖访问时官方接口向当前访问者公开的记录。

重新抓取官方最新状态，忽略旧分页缓存：

```bash
python scripts/sync_iclr.py --year 2026 --source openreview --refresh --no-env-proxy
```

官方访问受阻时，显式选择镜像。首次运行会固定 Git 提交并校验 LFS 哈希，后续默认使用已校验的本地快照：

```bash
python scripts/sync_iclr.py --year 2026 --source papercopilot --no-env-proxy
python scripts/sync_iclr.py --year 2026 --source papercopilot --refresh --no-env-proxy
```

如需同时导出主会和 workshop，使用另一输出目录，避免覆盖主会表：

```bash
python scripts/sync_iclr.py --year 2026 --source papercopilot --track all --output iclr2026_all --no-env-proxy
```

`--no-env-proxy` 表示直接连接；本环境的代理曾发生 TLS 错误。如果你的网络需要系统代理，移除此选项。遇到 429 或临时服务器错误时脚本会有限重试；403 浏览器验证会记录并退出。官方抓取失败时，已有导出数据会保留。

校验主键、CSV/JSONL 一致性、逐审稿人分值、缺失值与 0 分、均分、文件校验和，以及镜像范围内的逐篇标题和摘要：

```bash
python -m unittest discover -s tests -v
python scripts/validate_iclr.py iclr2026
```

`--refresh` 会替换当前来源快照和导出表。需要保留多期版本时，使用 `--output` 指定新目录。访问政策与接口说明见 [OpenReview 官方数据获取文档](https://docs.openreview.net/how-to-guides/data-retrieval-and-modification/how-to-get-all-notes-for-submissions-reviews-rebuttals-etc)。

## 本地论文浏览网站

网站监听 **`0.0.0.0:8000`**，本机访问 [http://localhost:8000](http://localhost:8000)。远程使用时转发 8000 端口，或访问服务器地址的 8000 端口。

- 平均分按 0.5 分分档，点击柱子即可筛选对应论文，再次点击同一柱或“全部区间”取消选择。
- 区间左闭右开，末档 `[9.5, 10]` 包含 10；分档使用原始均分，不使用显示时四舍五入的两位小数。
- 单独列出无评分论文；0 分与缺失评分保持区别。
- 支持标题和摘要搜索、投稿状态筛选、均分升降序，以及每页 25 篇分页。
- 点击论文标题展开完整摘要和逐审稿人评分，提供 OpenReview 与 PDF 链接。
- 搜索和状态筛选同时影响统计及列表；分数区间只限制列表，分布图仍展示搜索和状态条件下的完整分布。
- 页面标明镜像来源、快照时间及覆盖限制，保留数据来源查看入口。手机端图表和宽表可在各自容器内横向滚动。

更新现有论文快照后，重新构建网站：

```bash
python scripts/build_iclr_web.py --year 2026
```

构建器使用已安装的 Data 仪表盘组件与 Node.js，无需安装 npm 依赖。两个年份分别生成页面并保持独立 artifact ID；首次构建请在项目根目录运行 `python scripts/build_iclr_web.py` 同时生成两年；组件版本路径可通过 `--plugin-root` 指定。网站数据是本地快照，不会在访问时自动向 OpenReview 抓取。

前台启动服务（Ctrl+C 停止）：

```bash
python scripts/serve_paperreading.py --host 0.0.0.0 --port 8000
```

本次已启动的后台服务将 PID 写入 `.runtime/paperreading.pid`，日志在 `.runtime/paperreading.log`。停止该后台服务：

```bash
kill "$(cat .runtime/paperreading.pid)"
```

服务只提供 `web/dist/` 中的构建文件，不暴露工作目录及原始镜像。支持 gzip 压缩传输；已核对解压后内容与构建文件一致。更新后重建并刷新浏览器即可，服务不必重启。

网站数据逻辑及全量快照测试：

```bash
node --test tests/iclr_web.test.mjs
```

测试涵盖边界、缺失值、0 分、筛选交集、排序、分页，以及 19,814 篇论文和逐条评分与原始导出的对应关系。浏览器与 HTTP 核验记录保存在 `.runtime/`，不作为论文数据的一部分。
