# PaperReading

需要用户登录或网页验证时，可使用[当前机器的持久浏览器](docs/browser-session.md)：运行 `python scripts/browser_session.py start`，从现有网站端口进入返回的私有路径。用户与 agent 操作同一个浏览器，登录状态可保留。

Git 保存应用源码、测试、数据来源记录和校验报告。原始下载、论文 CSV/JSONL、审稿 CSV、构建产物及运行缓存保留在本地，不纳入提交。新检出目录需先按下文同步两个年份的数据，再构建网站；历史快照的来源 URL 和 SHA-256 记录在各年份的 `raw/papercopilot_source.json` 中。

论文库监听 `0.0.0.0:8000`，按会议和年份进入，当前提供 **ICLR 2026、2027**。

| 页面 | 地址 | 论文数 | 原始评分尺度 |
| --- | --- | ---: | --- |
| 入口首页 | [PaperReading](http://localhost:8000/) | — | — |
| ICLR 2026 | [进入 2026](http://localhost:8000/iclr/2026/) | 19,814 | 0–10 |
| ICLR 2027 | [进入 2027](http://localhost:8000/iclr/2027/) | 42,790 | 1–4 |

远程环境转发 8000 端口。两个年份都有标题/摘要搜索、关键词展示与模糊查询、状态筛选、评分分布、分页、摘要和审稿评分；页面顶部可切换年份或返回首页。NeurIPS、CVPR、ICML 在首页标为待收录。

## 加载优化

旧版必须先下载约 97 MB 的完整 2027 数据（gzip 后 28.07 MB），包括所有摘要与详细评分，才能显示页面。现在分成三个部分：

- 首页是独立静态 HTML/CSS，合计约 3 KB 压缩内容，不请求论文数据。
- 年份页面先加载所有论文的标题、状态、评分与均分，保留完整分布和列表；2027 数据压缩后约 2.14 MB，2026 约 0.98 MB。
- 关键词标签按当前页批量读取（最多 25 篇），不把全部关键词塞进首屏，也不为展示标签下载摘要。
- 展开论文时才加载对应详情分片，每个年份按 ID 哈希分成 256 片，同一页面共享请求，并仅缓存最近 16 片。全文摘要及详细评分保留完整。

标题与摘要搜索使用本地 SQLite，只返回匹配 ID，不向 OpenReview 发请求，不下载全部摘要；查询参数绑定，保持字面子串匹配。搜索、详情均显示加载或失败状态并支持重试；中止过期搜索，避免快速输入混入旧结果。全文搜索需要本项目的 Python 服务，不能用普通静态服务替代。

HTML/CSS 使用 ETag 重新验证，带内容哈希的评分快照和详情分片使用一年 immutable 缓存；所有公开 JSON/HTML/CSS 提供 gzip。SQLite 搜索文件禁止直接通过 HTTP 下载。

## Keywords 与标题模糊查询

“对应论文”上方新增 **搜索当前筛选结果**：在当前年份、顶部标题/摘要查询、Keywords、状态和均分共同选中的全部论文中，进一步搜索标题或摘要，覆盖所有分页。结果内搜索仅更新列表、匹配数量及分页，保留当前分布与统计以便比较；修改筛选设置后，搜索词继续作用于新的范围。“清除结果内搜索”仅清空该搜索，“重置筛选”清空所有条件。输入后立即标记为查询中并隐藏旧结果，等待 200 ms 再发起本地索引查询，过期请求会被取消；支持失败重试，不批量下载摘要。搜索失败显示范围不可用，响应结构异常显示错误，不作为零篇结果。

列表标题下和展开详情中展示作者原始关键词，点击任意标签即可筛选。**Keywords / 标题模糊查询** 输入框默认“都查（Keywords + 标题）”，也可选择“只查 Keywords”或“只查标题”。支持部分词匹配，例如 `diff` 匹配 `diffusion`；忽略大小写、全角/半角差异，连字符和下划线视作分隔符。多个词按 AND 匹配，词序不限；“都查”时每个词可出现在标题或关键词任一字段中，不搜索摘要，例如 `agent multi` 可匹配 `Multi-Agent`。这里的模糊查询指部分词匹配，不提供拼写纠错或语义扩展。

该模糊查询可与标题/摘要搜索、投稿状态、均分选择及结果内搜索组合；切换查询范围自动重新查询并回到第一页，重置筛选恢复“都查”。点击关键词标签会把词填入模糊查询框，沿用当前查询范围。关键词取自两个年份已固定版本的 Paper Copilot 原始镜像，按 forum ID 关联，构建前核验 SHA-256；保留作者拼写，不从摘要推断关键词。目前 62,604 篇主会记录均有关键词。原始论文导出不改写，关键词在网站构建时加入本地索引。

`/api/keywords` 仅返回当前年份、当前数据版本中指定论文的关键词，每次最多 25 篇；`/api/search` 的 `keywords` 参数在本地 SQLite 中检索，`keyword_scope` 可选 `both`（默认）、`keywords`、`title`；标题与关键词均预先建立归一化字段，不请求外部服务。翻页和搜索会中止过期关键词请求，失败时可重试。

## 审稿评价正文

评分表在匿名审稿人名字前提供折叠箭头：点击箭头或名字才请求该论文的公开评审，按匿名审稿人代号匹配，在该评分行下方跨列显示概述、优点、不足、问题等原文，再次点击同一名字收起。不设置单独的“具体评价”列或“收起评价”按钮。只提取公开 `Official_Review`，作者回复、公众评论和 meta-review 不会混入；网页按纯文本展示原文，不执行其中的 HTML。正文采集时间单独标注，不覆盖原有评分快照。

**目前尚未取得评价正文。** 已确认现有两个公开镜像仅包含评分和评价字数，OpenReview API 以及浏览器访问均要求验证。失败时入口显示“未取得正文”和 OpenReview 链接，不生成评价、不把字数当正文。该状态不代表论文没有评审。

抓取器使用官方公开接口，成功数据写入 `iclr<year>/review_text/<forum-id>.json`，原始响应保存在 `raw/review_text/`。网站按需加载并缓存六小时；403 或 HTTP 200 返回浏览器验证 HTML 时暂停远程请求十五分钟，429 后暂停一分钟，避免反复触发限制。验证问题解决后可直接重试；也可导入从 OpenReview 获取的公开 notes JSON。

```bash
python scripts/review_text.py --year 2027 --paper-id U1ObEVC4A7
python scripts/review_text.py --year 2027 --paper-id U1ObEVC4A7 --input /path/to/public-notes.json
```

导入数据仍要求 forum、年份及公开可见标记匹配。服务的 `/api/reviews` 只接受当前年份和快照中存在的论文，不接受任意外部网址。正文与首页数据独立，保持现有首屏加载速度。

## 当前数据

截至北京时间 **2026-11-15**，已获取 Paper Copilot 公开镜像中的全部 **42,790** 篇主会记录，保存标题、完整英文摘要、OpenReview 页面、PDF 链接以及 **126,389** 条逐审稿人评分。

| 项目 | 数量 |
| --- | ---: |
| 主会投稿 | 42,790 |
| 有评分论文 | 40,801 |
| 无评分论文 | 1,989 |
| 审稿评分记录 | 126,389 |
| 标题或摘要缺失 | 0 |
| Active · 审稿中 | 37,452 |
| Withdraw · 撤稿 | 3,627 |
| Desk Reject · 直接拒稿 | 1,711 |

**ICLR 2027 使用原始 1–4 分尺度，本项目不将其换算成十分制。** 2027 网站按实际出现的 **33 个精确均分**分别画柱，不再按 0.5 分分档。以评分总和/有效评分人数约分作为类别键，所有均分用两位小数标注（如 `2.33`、`2.00`），按数值从小到大等距展示；相同均分跨评分人数合并，显示舍入不会影响计数或筛选。搜索、状态筛选后保留完整均分轴，当前没有论文的均分显示零计数。缺失评分保持 `null`，不作为零分参与平均；无评分论文有独立入口。2026 保留半分区间展示。

目前仍在审稿讨论阶段，`Active` 不是录用决定，评分可能更新。评分表保留 Rating、Confidence、Soundness、Presentation 和 **Informativeness**；2027 快照没有提供 Contribution，不显示虚构的数值。

**覆盖限制：当前来源是第三方公开镜像。** 本次 OpenReview 官方接口探测遇到 HTTP 429，正式抓取返回 HTTP 403 浏览器验证错误，记录在 `iclr2027/raw/last_error.json`。已逐条核对镜像范围内的完整导出，尚未通过官方接口核实是否覆盖所有公开投稿，不能把镜像数量当成官方确认总数。

来源固定到 [Paper Copilot 提交 2a56c85](https://github.com/papercopilot/paperlists/commit/2a56c85a36140b68be4510bc504d169d29a16b05)，提交时间 `2026-11-15T00:15:56Z`。已校验此固定提交的 Git LFS SHA-256 与文件大小；镜像实际采集时间未知。评分可能是该镜像采集时的快照值，不是逐轮评分历史。参见 [ICLR 2027 官方审稿指南](https://iclr.cc/Conferences/2027/ReviewerGuidelines)。

## 数据文件

| 文件 | 内容 |
| --- | --- |
| `iclr2027/papers.csv` | Excel 可直接打开的论文主表，UTF-8 BOM 编码 |
| `iclr2027/papers.jsonl` | 每行一篇论文，包含逐条审稿评分 |
| `iclr2027/reviews.csv` | 每行一位匿名审稿人的分值，通过 `paper_id` 关联论文 |
| `iclr2027/manifest.json` | 年份、尺度、来源、数量、缺失情况及文件校验和 |
| `iclr2027/validation.json` | 原始镜像到导出的全量核对结果 |
| `iclr2027/raw/papercopilot.json` | 原始公开镜像，210,916,864 字节 |
| `iclr2027/raw/papercopilot_source.json` | 固定版本、下载时间及 SHA-256 |

`id` 是 OpenReview forum ID；`paper_url` 是讨论页，`pdf_url` 是按 forum ID 构造的官方 PDF 地址，尚未逐篇验证可下载性。`ratings` 与 `reviews` 按位置对应，`rating_mean` 为非空总评分的算术平均。镜像没有提供 review note ID，因此 `review_id`、`review_url` 保持为空；匿名审稿人代号不代表真实身份。`retrieved_at` 是本地获取时间，不是评分修改时间。

**2026 数据独立保存在 `iclr2026/`，并在 `/iclr/2026/` 提供浏览。** 历史快照说明见 [iclr2026/README.md](iclr2026/README.md)。两个年份独立构建评分尺度、来源、详情与搜索库，并校验来源年份和评分范围。

## 抓取、更新与运行

抓取和服务脚本使用 Python 3.10+ 标准库；网站构建使用环境已安装的 Data 仪表盘组件和 Node.js，不需要安装 npm 依赖或提供 API 密钥。以下命令在项目根目录执行。抓取器默认年份为 **2027**；网站构建默认同时生成 **2026 和 2027**。

优先尝试官方公开接口：

```bash
python scripts/sync_iclr.py --year 2027 --source openreview --no-env-proxy
```

官方抓取按 `ICLR.cc/2027/Conference/-/Submission` 分页获取全部状态，提取 `directReplies` 中的 `Official_Review`；不会把作者回复、公众评论或 meta-review 当作审稿评分。缓存位于该年份的 `raw/openreview/`，可重跑续取；`--refresh` 忽略旧缓存。只有唯一论文数与 API 报告总数一致时才标记官方公开范围核对成功。

官方受限时，显式获取镜像并全量核对：

```bash
python scripts/sync_iclr.py --year 2027 --source papercopilot --refresh --no-env-proxy
python scripts/validate_iclr.py iclr2027
python scripts/build_iclr_web.py
```

不加 `--refresh` 时使用已校验的本地镜像。`--no-env-proxy` 表示直接连接；网络需要系统代理时移除此参数。429 和临时服务器错误会有限重试；403 会记录后退出，不覆盖已有导出。

默认构建两个年份和首页；之后只更新其中一年可运行 `python scripts/build_iclr_web.py --year 2027`（或 `2026`），另一年份仍保留。新工作目录先运行完整构建。每年拥有独立稳定的 artifact ID，2027 保留原 ID。构建插件位置变化时可通过 `--plugin-root` 指定安装目录。抓取器的 `--output` 可指定另一数据目录保存额外快照。

构建生成 `web/dist/index.html`、`catalog.json`、`iclr/<year>/` 和 `data/iclr/<year>/<snapshot-hash>/`。前者是会议/年份入口，年份目录是标准 Data 仪表盘，数据目录包含详情分片和只读搜索库。原始论文导出没有删减；`web/src/data.json` 只保存最后构建年份的精简首屏数据。

前台启动服务，Ctrl+C 停止：

```bash
python scripts/serve_paperreading.py --host 0.0.0.0 --port 8000
```

本次运行中的后台服务 PID 位于 `.runtime/paperreading.pid`，日志位于 `.runtime/paperreading.log`。只停止该服务：

```bash
kill "$(cat .runtime/paperreading.pid)"
```

服务仅提供 `web/dist/` 的公开文件及 `/api/search`、`/api/keywords`、`/api/reviews`，不暴露工作目录、原始镜像和 SQLite 文件。搜索严格按会议、年份和数据版本隔离；访问网站不会自动向 OpenReview 请求数据。更新网站数据后重建并刷新即可，修改服务脚本后须重启服务。

## 网站使用与验证

点击分布柱筛选对应论文，再次点击同一柱或“全部均分”（2026 为“全部区间”）取消选择。搜索标题和摘要、Keywords 模糊查询、投稿状态筛选会同时更新统计和列表；均分或区间选择只限制列表，保留完整分布以供比较。列表支持均分升降序，每页 25 篇；展开标题可查看完整摘要、逐审稿人评分及论文链接。手机端宽表和分布图在各自容器内滚动。

```bash
python -m unittest discover -s tests -v
node --test tests/iclr_web.test.mjs tests/paper-loader.test.mjs
```

测试覆盖两个年份的全部 62,604 篇论文及逐条评分对照、精简首屏与详情的完整性、首屏体积限制、评分边界、0 分与缺失值、筛选分页、全部原始关键词与搜索索引的逐条对照、关键词部分词/多词匹配、组合搜索、按页读取和年份隔离及 HTTP 缓存。浏览器和 HTTP 核验记录保存在忽略目录 `.runtime/`，与论文数据分开。
