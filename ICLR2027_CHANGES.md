# ICLR 2027 重做记录

当前网站为 PaperReading，默认只加载 ICLR 2027 主会数据。2026 数据作为历史归档保留，未混入当前网站。

本清单记录源码、数据和说明文件；可重建的 web/dist 产物与忽略目录 .runtime 的进程、日志、截图不计入源码逐行统计。脚本重命名按对应旧文件的内容差异计数。

| 文件 | 增加 | 删除 |
| --- | ---: | ---: |
| [ICLR2027_CHANGES.md](/opt/data/private/workspace/codes/paper-reading/ICLR2027_CHANGES.md:1) | +40 | -0 |
| [README.md](/opt/data/private/workspace/codes/paper-reading/README.md:1) | +52 | -97 |
| [scripts/sync_iclr.py（由 scripts/sync_iclr2026.py 重命名）](/opt/data/private/workspace/codes/paper-reading/scripts/sync_iclr.py:1) | +36 | -22 |
| [scripts/validate_iclr.py（由 scripts/validate_iclr2026.py 重命名）](/opt/data/private/workspace/codes/paper-reading/scripts/validate_iclr.py:1) | +15 | -10 |
| [scripts/build_iclr_web.py（由 scripts/build_iclr2026_web.py 重命名）](/opt/data/private/workspace/codes/paper-reading/scripts/build_iclr_web.py:1) | +37 | -18 |
| [scripts/serve_paperreading.py（由 scripts/serve_iclr2026.py 重命名）](/opt/data/private/workspace/codes/paper-reading/scripts/serve_paperreading.py:1) | +2 | -2 |
| [tests/test_sync_iclr.py（由 tests/test_sync_iclr2026.py 重命名）](/opt/data/private/workspace/codes/paper-reading/tests/test_sync_iclr.py:1) | +26 | -4 |
| [tests/iclr_web.test.mjs（由 tests/iclr2026_web.test.mjs 重命名）](/opt/data/private/workspace/codes/paper-reading/tests/iclr_web.test.mjs:1) | +45 | -26 |
| [web/src/content/dashboard/paper-data.mjs](/opt/data/private/workspace/codes/paper-reading/web/src/content/dashboard/paper-data.mjs:1) | +15 | -6 |
| [web/src/content/dashboard/DashboardContent.jsx](/opt/data/private/workspace/codes/paper-reading/web/src/content/dashboard/DashboardContent.jsx:1) | +25 | -20 |
| [web/src/data.json](/opt/data/private/workspace/codes/paper-reading/web/src/data.json:1) | +1 | -1 |
| [iclr2026/README.md](/opt/data/private/workspace/codes/paper-reading/iclr2026/README.md:1) | +138 | -0 |
| [iclr2027/manifest.json](/opt/data/private/workspace/codes/paper-reading/iclr2027/manifest.json:1) | +56 | -0 |
| [iclr2027/papers.csv](/opt/data/private/workspace/codes/paper-reading/iclr2027/papers.csv:1) | +140253 | -0 |
| [iclr2027/papers.jsonl](/opt/data/private/workspace/codes/paper-reading/iclr2027/papers.jsonl:1) | +42790 | -0 |
| [iclr2027/raw/last_error.json](/opt/data/private/workspace/codes/paper-reading/iclr2027/raw/last_error.json:1) | +7 | -0 |
| [iclr2027/raw/papercopilot.json](/opt/data/private/workspace/codes/paper-reading/iclr2027/raw/papercopilot.json:1) | +4749692 | -0 |
| [iclr2027/raw/papercopilot_source.json](/opt/data/private/workspace/codes/paper-reading/iclr2027/raw/papercopilot_source.json:1) | +13 | -0 |
| [iclr2027/reviews.csv](/opt/data/private/workspace/codes/paper-reading/iclr2027/reviews.csv:1) | +126390 | -0 |
| [iclr2027/validation.json](/opt/data/private/workspace/codes/paper-reading/iclr2027/validation.json:1) | +18 | -0 |

## 数据与验证

- 镜像主会记录 42,790 篇，评分记录 126,389 条；有评分 40,801 篇，无评分 1,989 篇。
- 标题、摘要及链接已保存；标题和摘要无缺失。镜像覆盖范围内全部记录已逐条核对。
- 固定 Git 提交及 LFS 哈希/大小校验通过；官方接口 403，官方全量覆盖仍未核实。
- 2027 总评分范围为 1–4；6 个半分区间合计 40,801 篇，末档包含 4 分。
- 8 项 Python 测试、8 项 Node.js 测试、16 项 Chromium 页面检查通过，无页面运行异常。
- 浏览器核验覆盖区间联动、Informativeness、状态交集、搜索、分页、排序、无评分入口、键盘、4 分边界，以及桌面、手机和深色模式。
- HTTP 200，首页和 2027 数据文件的 gzip 解压内容与构建 SHA-256 一致。
- 服务监听 0.0.0.0:8000，PID 保存在 .runtime/paperreading.pid。
