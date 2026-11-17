# 当前机器的持久浏览器

PaperReading 在 node02 上运行一个有界面的 Chromium。用户通过现有网站端口中的 noVNC 窗口登录；agent 通过本机 CDP 操作同一个浏览器。两条通道指向同一个持久配置目录，不需要连接用户另一台电脑。

## 使用

```bash
python scripts/browser_session.py status
python scripts/browser_session.py start
```

`start` 返回 `/browser/?key=...`。在**当前已打开的 PaperReading 地址**保留主机和转发端口，只替换这个路径。第一次打开后，服务设置仅限 `/browser/` 的 HttpOnly、SameSite Cookie，并跳转到不含密钥的 `/browser/`。不要把私有链接分享给其他人。

用户在画面里的 Chrome 登录 OpenReview。完成后再恢复 agent 操作，避免在输入密码期间截图或读取页面。登录状态保留在 `.runtime/browser-session/profile`；关闭查看网页不退出浏览器。

```bash
# 只列出任务相关的 OpenReview 标签页。
python scripts/browser_session.py tabs

# 确认同一个标签页的地址与可见正文，不读取输入框值。
python scripts/browser_session.py read --target <targetId>

# 打开论文页，保留已登录会话。
python scripts/browser_session.py open --url 'https://openreview.net/forum?id=<forumId>'

# 必要时运行存于私有目录中的页面表达式，仅允许 OpenReview 标签页。
python scripts/browser_session.py evaluate --target <targetId> --file .runtime/page-expression.js

# 停止服务，保留登录目录；重新 start 可恢复。
python scripts/browser_session.py stop
```

`read` 只说明页面可读取。它不证明已登录，更不证明已获得审稿正文。需要分别确认登录后的页面状态和实际返回的公开 Official_Review；未公开的评审不会进入网站数据。`scripts/review_text.py` 的 HTTP 请求失败后，会调用 `scripts/browser_reviews.py`，在持久浏览器内请求公开 notes；不会把 Cookie、密码或令牌复制给 Python。验证页由用户完成操作，再重试网站中的评价获取。

批量正文同步使用 `python scripts/sync_review_text.py --year 2027 2026 --page-size 250`，复用同一会话，按官方投稿分页并过滤公开评审。用相同命令恢复断点，追加 `--status` 查看两年的进度；遇到验证或限流会记录原因并停止，不继续请求。分页原始公开评审、数据库结果与进度均留在本地，网页自动读取已完成批次。

## 环境安装

当前环境已提供 Xvfb、xauth 和可运行的 Chromium。Python 需 3.12+，浏览器默认使用已验证的 `/root/.cache/ms-playwright/chromium-1124/chrome-linux/chrome`，也可设置 `PAPERREADING_CHROME` 为其他兼容二进制。

```bash
python -m pip install -r requirements-browser.txt
python scripts/setup_browser.py
```

安装脚本将 Ubuntu 仓库的 x11vnc 及所需库解包到 `.runtime/browser-tools/root`，不更改系统包；noVNC 固定为 1.6.0，下载后校验 SHA-256。它需要宿主提供 `apt-get`、`dpkg-deb`、`Xvfb` 和 `xauth`。新环境缺少这些前置条件时按实际错误处理，不能仅凭本机安装成功就认定其他系统也兼容。

noVNC 使用[官方 RFB 接口](https://github.com/novnc/noVNC/blob/v1.6.0/docs/API.md)。本方案创建独立、持久的任务配置目录，因此不依赖默认 Chrome 配置目录的调试开关；Chrome 默认配置目录另有[官方远程调试限制](https://developer.chrome.com/blog/remote-debugging-port)。

## 故障定位

| 现象 | 检查与恢复 |
| --- | --- |
| 没有浏览器控制工具 | 先用本项目 CLI 检查本机 CDP，不以工具列表代替连接检查。 |
| `/browser/` 返回 403 | 用 `start` 输出的私有入口重新建立访问 Cookie。不要删除浏览器配置。 |
| `/browser/` 返回 503 | `status` 检查是否 ready，再查 `.runtime/browser-session/session.log`。 |
| 页面显示画面连接断开 | 点“重新连接”；检查 `vnc.log`、`chrome.log` 和 `display.log`。 |
| 启动失败或端口占用 | 查看日志；9226、5906、8765 是专用的本机端口。不要结束不属于本任务的进程。 |
| Chrome 页面要求登录/验证 | 在同一个查看窗口交给用户操作，不用新的临时浏览器替换会话。 |
| 刚取得正文后又出现 `verification_required` | 已取得的正文继续从缓存读取。验证可能再次触发；在同一浏览器登录账号后再重试，不把历史验证成功当作当前仍有效。网站提示中提供 `/browser/` 入口，不包含访问密钥。 |
| 浏览器可访问，HTTP 抓取器仍失败 | 网站会尝试浏览器路径，成功结果的 `transport` 为 `browser`。若仍失败，检查 `/api/reviews` 的 `browser_status`；页面可读不代表 API 已通过验证。 |

CDP、VNC 和 noVNC 仅监听 `127.0.0.1`；对外只有网站原来的端口。WebSocket 需要访问 Cookie 且 Origin 与 Host 一致。配置目录、访问密钥、X11 授权及运行日志位于 Git 忽略的私有目录，目录权限 0700，进程创建文件默认 0600；不要将这些内容放入网页静态目录。

## 已验证的边界

- 在当前 node02 启动持久 Chromium，CDP 可列出并读取 OpenReview 登录页。
- 通过 PaperReading 同一个 8000 端口访问 noVNC，双向传输真实 RFB 帧。
- 自动测试验证未授权访问、目录越界、跨 Origin 连接被拒绝，入口密钥不写入访问日志。
- 2026-11-15 用户完成浏览器验证后，实际通过浏览器接口取得 ICLR 2027 `U1ObEVC4A7`、`001PJNwZiT` 和 ICLR 2026 `00HNN8O7Ni` 的公开审稿正文，共 10 条，结果的 `transport` 为 `browser`。这证明公开正文可读，不用于推断用户登录身份；仍不读取或导出凭据。
- 同日用户确认完成账号登录后，首次获取 `002z9w7Cev` 成功；随后从网站点击此前未缓存的 `004w3yx1Yp`，也成功取得 3 条正文。两个年份共 5 篇、16 条评价通过 79 项真实网页检查，包含匿名代号、原始正文逐段一致、来源链接、同一控件折叠与共享请求；另核验移动端无页面横向溢出。验证记录位于 `.runtime/review-real-verification.json` 和 `.runtime/review-cold-verification.json`。这不保证登录永不失效，后续失败仍按上表恢复。
