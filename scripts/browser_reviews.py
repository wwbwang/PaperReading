"""Read public review notes inside the existing browser, without exporting credentials."""

import asyncio
import json
from urllib.parse import urlsplit

from websockets.exceptions import WebSocketException

from scripts import browser_session


class BrowserReviewError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


async def fetch_page(target, year, paper_id, offset):
    return await fetch_public_page(target, year, {"forum": paper_id, "offset": offset, "limit": 1000}, paper_id)


async def fetch_submission_page(target, year, offset, limit):
    return await fetch_public_page(target, year, {
        "invitation": f"ICLR.cc/{year}/Conference/-/Submission", "details": "directReplies",
        "offset": offset, "limit": limit, "sort": "number:asc",
    })


async def fetch_public_page(target, year, query, paper_id=None):
    # Filter before data leaves Chrome, including field-level reader restrictions.
    expression = """(async () => {
      if (location.pathname === '/login') return {status: 'login_required'};
      const [year, params, forum] = ARGS;
      try {
        const query = new URLSearchParams({...params, count: true});
        const response = await fetch('https://api2.openreview.net/notes?' + query, {
          credentials: 'include', headers: {Accept: 'application/json'}, signal: AbortSignal.timeout(25000)
        });
        if (response.status === 429) return {status: 'rate_limited'};
        if (response.status === 401) return {status: 'login_required'};
        if (response.status === 403) {
          if (!(response.headers.get('content-type') || '').includes('application/json'))
            return {status: 'verification_required'};
          const error = await response.json();
          return {status: ['ChallengeRequiredError', 'HumanVerificationRequiredError'].includes(error.name)
            ? 'verification_required' : 'access_denied'};
        }
        if (!response.ok) return {status: 'unavailable'};
        if (!(response.headers.get('content-type') || '').includes('application/json'))
          return {status: 'verification_required'};
        const data = await response.json();
        if (!Array.isArray(data.notes) || !Number.isInteger(data.count) || data.count < 0)
          return {status: 'invalid_response'};
        const reviews = (items, id) => items.filter(n => n.forum === id && !n.ddate &&
          n.readers?.includes('everyone') && n.invitations?.some(i =>
            i.startsWith(`ICLR.cc/${year}/Conference/`) && i.endsWith('/-/Official_Review')))
          .map(n => ({id:n.id, forum:n.forum, readers:n.readers, invitations:n.invitations,
            signatures:n.signatures, mdate:n.mdate, content:Object.fromEntries(
              Object.entries(n.content || {}).filter(([, v]) =>
                !v || typeof v !== 'object' || !v.readers || v.readers.includes('everyone')))}));
        if (forum) return {status: 'ok', notes: reviews(data.notes, forum), count: data.count, received: data.notes.length};
        const submissions = data.notes.filter(n => !n.ddate && n.readers?.includes('everyone') &&
          n.invitations?.includes(`ICLR.cc/${year}/Conference/-/Submission`));
        if (submissions.some(n => !Array.isArray(n.details?.directReplies))) return {status:'invalid_response'};
        const papers = submissions.map(n => ({id:n.id, notes:reviews(n.details.directReplies, n.id)}));
        return {status:'ok', papers, count:data.count, received:data.notes.length};
      } catch { return {status: 'unavailable'}; }
    })()""".replace("ARGS", json.dumps([year, query, paper_id]))
    result = await browser_session.command("Runtime.evaluate", {
        "expression": expression, "returnByValue": True, "awaitPromise": True,
    }, target)
    if result.get("exceptionDetails"):
        raise BrowserReviewError("unavailable", "浏览器未能读取公开评审接口。")
    return result.get("result", {}).get("value", {})


async def task_target(year, paper_id=None):
    state = browser_session.read_state()
    if not browser_session.alive(state) or state.get("phase") != "ready":
        raise BrowserReviewError("browser_unavailable", "当前机器的持久浏览器未运行，请先启动浏览器。")
    targets = (await browser_session.command("Target.getTargets"))["targetInfos"]
    # Never inspect or navigate the user's login tab. Reuse a task forum/challenge tab.
    target = next((t["targetId"] for t in targets if t["type"] == "page"
                   and urlsplit(t["url"]).hostname == "openreview.net"
                   and (urlsplit(t["url"]).path in ("/forum", "/challenge")
                        or t["url"] == f"https://openreview.net/group?id=ICLR.cc/{year}/Conference")), None)
    if target is None:
        target = (await browser_session.command("Target.createTarget", {
            "url": (f"https://openreview.net/forum?id={paper_id}" if paper_id
                    else f"https://openreview.net/group?id=ICLR.cc/{year}/Conference"),
        }))["targetId"]
        # Let normal navigation settle; never click or automate a verification challenge.
        await asyncio.sleep(2)
    return target


def check_status(page):
    status = page.get("status", "invalid_response")
    if status in ("verification_required", "login_required"):
        raise BrowserReviewError(status, "请在当前机器的私有浏览器中完成 OpenReview 验证或登录，再重试。在其他电脑登录不会同步到这里。")
    if status == "rate_limited":
        raise BrowserReviewError(status, "OpenReview 正在限流，请稍后重试。")
    if status == "access_denied":
        raise BrowserReviewError(status, "OpenReview 拒绝读取公开评审，当前未取得正文。")
    if status != "ok":
        raise BrowserReviewError(status, "浏览器暂时无法读取 OpenReview 的公开评审接口。")


async def collect(year, paper_id):
    target = await task_target(year, paper_id)
    pages, offset = [], 0
    for _ in range(100):
        page = await fetch_page(target, year, paper_id, offset)
        check_status(page)
        pages.append(page)
        offset += page["received"]
        if offset >= page["count"]:
            return pages
        if not page["received"]:
            break
    raise BrowserReviewError("invalid_response", "OpenReview 评审分页未完整返回，未缓存部分结果。")


def retrieve_pages(year, paper_id):
    return run(collect(year, paper_id))


def retrieve_submission_page(year, offset, limit=50):
    async def read():
        target = await task_target(year)
        page = await fetch_submission_page(target, year, offset, limit)
        check_status(page)
        return page
    return run(read())


def run(operation):
    try:
        return asyncio.run(operation)
    except BrowserReviewError:
        raise
    except (OSError, RuntimeError, ValueError, TimeoutError, ImportError, KeyError, WebSocketException) as error:
        raise BrowserReviewError("browser_unavailable", "无法连接当前机器的持久浏览器，请检查浏览器服务后重试。") from error
