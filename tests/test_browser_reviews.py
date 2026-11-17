"""Browser fallback pagination and private-data boundaries; no live session access."""

import json
import subprocess
import unittest
from unittest.mock import AsyncMock, patch

from scripts import browser_reviews as browser


class BrowserReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name, value in [("read_state", {"phase": "ready"}), ("alive", True)]:
            mock = patch.object(browser.browser_session, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.targets = {"targetInfos": [
            {"type": "page", "targetId": "login", "url": "https://openreview.net/login"},
            {"type": "page", "targetId": "forum", "url": "https://openreview.net/forum?id=paper"},
            {"type": "page", "targetId": "other", "url": "https://example.com/forum"},
        ]}

    async def test_pagination_counts_all_notes_not_only_public_reviews(self):
        with patch.object(browser.browser_session, "command", AsyncMock(return_value=self.targets)) as command, \
                patch.object(browser, "fetch_page", AsyncMock(side_effect=[
                    {"status": "ok", "received": 1000, "count": 1001, "notes": []},
                    {"status": "ok", "received": 1, "count": 1001, "notes": [{"id": "review"}]},
                ])) as fetch:
            pages = await browser.collect(2027, "paper")
            self.assertEqual(len(pages), 2)
            self.assertEqual(fetch.await_args_list[1].args, ("forum", 2027, "paper", 1000))
            command.assert_awaited_once_with("Target.getTargets")

    async def test_challenge_and_rate_limit_stop_without_retrying(self):
        for status in ["verification_required", "rate_limited", "invalid_response"]:
            with patch.object(browser.browser_session, "command", AsyncMock(return_value=self.targets)), \
                    patch.object(browser, "fetch_page", AsyncMock(return_value={"status": status})) as fetch:
                with self.assertRaises(browser.BrowserReviewError) as caught:
                    await browser.collect(2027, "paper")
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(fetch.await_count, 1)

    async def test_truncated_pagination_fails_without_returning_partial_data(self):
        with patch.object(browser.browser_session, "command", AsyncMock(return_value=self.targets)), \
                patch.object(browser, "fetch_page", AsyncMock(return_value={
                    "status": "ok", "notes": [], "received": 0, "count": 1,
                })):
            with self.assertRaises(browser.BrowserReviewError):
                await browser.collect(2027, "paper")

    async def test_api_errors_distinguish_verification_login_and_access_denial(self):
        captured = {}

        async def command(method, params, target):
            captured.update(params)
            return {"result": {"value": {}}}

        with patch.object(browser.browser_session, "command", command):
            await browser.fetch_page("forum", 2027, "paper", 0)
        for code, name, expected in [(403, "ChallengeRequiredError", "verification_required"),
                                      (403, "ForbiddenError", "access_denied"),
                                      (401, "TokenExpiredError", "login_required"),
                                      (429, "RateLimitError", "rate_limited")]:
            script = "globalThis.location={pathname:'/forum'};globalThis.fetch=async()=>({ok:false,status:CODE,headers:new Headers({'content-type':'application/json'}),json:async()=>({name:NAME,message:'DO NOT EXPORT'})});EXPR.then(r=>console.log(JSON.stringify(r)));"
            script = script.replace("CODE", str(code)).replace("NAME", json.dumps(name)).replace("EXPR", captured["expression"])
            result = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", script], text=True))
            self.assertEqual(result, {"status": expected})

    async def test_javascript_filters_private_data_before_leaving_browser(self):
        captured = {}

        async def command(method, params, target):
            captured.update(params)
            return {"result": {"value": {"status": "ok"}}}

        with patch.object(browser.browser_session, "command", command):
            await browser.fetch_page("forum", 2027, "paper", 0)
        note = {"id": "public", "forum": "paper", "readers": ["everyone"],
                "invitations": ["ICLR.cc/2027/Conference/Submission1/-/Official_Review"],
                "content": {"summary": {"value": "public text"},
                            "secret": {"value": "DO NOT EXPORT", "readers": ["chairs"]}}}
        notes = [note, {**note, "id": "private", "readers": ["chairs"]},
                 {**note, "id": "wrong-forum", "forum": "other"}]
        # The old challenge tab may remain after login in a different tab. The API,
        # not the old page's URL, determines whether the shared session is ready.
        script = "globalThis.location={pathname:'/challenge'};globalThis.fetch=async(url,opts)=>{if(new URL(url).searchParams.get('count')!=='true' || opts.credentials!=='include') throw Error('Invalid request');return {ok:true,status:200,headers:new Headers({'content-type':'application/json'}),json:async()=>(DATA)}};EXPR.then(r=>console.log(JSON.stringify(r)));"
        script = script.replace("DATA", json.dumps({"notes": notes, "count": 3})).replace("EXPR", captured["expression"])
        result = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", script], text=True))
        self.assertEqual(result["received"], 3)
        self.assertEqual([n["id"] for n in result["notes"]], ["public"])
        self.assertNotIn("DO NOT EXPORT", json.dumps(result))
        self.assertIn("public text", json.dumps(result))

    async def test_batch_exports_only_public_reviews_of_public_submissions(self):
        captured = {}

        async def command(method, params, target):
            captured.update(params)
            return {"result": {"value": {}}}

        with patch.object(browser.browser_session, "command", command):
            await browser.fetch_submission_page("forum", 2027, 100, 100)
        review = {"id": "review", "forum": "paper", "readers": ["everyone"],
                  "invitations": ["ICLR.cc/2027/Conference/Submission1/-/Official_Review"],
                  "content": {"summary": {"value": "public text"},
                              "secret": {"value": "PRIVATE FIELD", "readers": ["chairs"]}}}
        submission = {"id": "paper", "readers": ["everyone"],
                      "invitations": ["ICLR.cc/2027/Conference/-/Submission"],
                      "content": {"authors": {"value": "DO NOT EXPORT"}},
                      "details": {"directReplies": [review, {**review, "id": "PRIVATE REVIEW", "readers": ["chairs"]}]}}
        script = "globalThis.location={pathname:'/forum'};globalThis.fetch=async(url,opts)=>{const q=new URL(url).searchParams;if(q.get('details')!=='directReplies'||q.get('offset')!=='100'||opts.credentials!=='include')throw Error('Invalid request');return {ok:true,status:200,headers:new Headers({'content-type':'application/json'}),json:async()=>(DATA)}};EXPR.then(r=>console.log(JSON.stringify(r)));"
        payload = {"count": 1000, "notes": [submission, {**submission, "id": "PRIVATE PAPER", "readers": ["chairs"]}]}
        expression = script.replace("DATA", json.dumps(payload)).replace("EXPR", captured["expression"])
        result = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", expression], text=True))
        self.assertEqual((result["status"], result["received"]), ("ok", 2))
        self.assertEqual([paper["id"] for paper in result["papers"]], ["paper"])
        self.assertEqual([note["id"] for note in result["papers"][0]["notes"]], ["review"])
        for secret in ("PRIVATE FIELD", "PRIVATE REVIEW", "PRIVATE PAPER", "DO NOT EXPORT"):
            self.assertNotIn(secret, json.dumps(result))
        del submission["details"]
        expression = script.replace("DATA", json.dumps({"count": 1, "notes": [submission]})).replace("EXPR", captured["expression"])
        result = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", expression], text=True))
        self.assertEqual(result, {"status": "invalid_response"})


if __name__ == "__main__":
    unittest.main()
