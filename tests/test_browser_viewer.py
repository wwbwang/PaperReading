"""Verify viewer authentication, asset isolation and HTTP/WebSocket forwarding."""

import asyncio
import functools
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from scripts.browser_viewer import serve_viewer
from scripts.serve_paperreading import DashboardHandler


class BrowserViewerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        (self.folder / "core").mkdir()
        (self.folder / "core/rfb.js").write_text("export default class RFB {}")
        (self.folder / "private.txt").write_text("PRIVATE PROFILE CONTENT")
        self.token = "test-private-access-key"
        self.vnc_received = asyncio.get_running_loop().create_future()

        async def vnc(reader, writer):
            try:
                writer.write(b"RFB 003.008\n")
                await writer.drain()
                payload = await reader.read(12)
                if not self.vnc_received.done():
                    self.vnc_received.set_result(payload)
            finally:
                writer.close()
                await writer.wait_closed()

        self.vnc = await asyncio.start_server(vnc, "127.0.0.1", 0)
        self.viewer = await serve_viewer(self.token, 0, self.vnc.sockets[0].getsockname()[1], self.folder)
        viewer_port = self.viewer.sockets[0].getsockname()[1]
        state = self.folder / "state.json"
        state.write_text(json.dumps({"phase": "ready", "viewer_port": viewer_port}))
        self.state_patch = patch("scripts.browser_viewer.STATE", state)
        self.state_patch.start()
        self.logs = []
        logs = self.logs

        class QuietHandler(DashboardHandler):
            def log_message(self, format, *args):
                logs.append(format % args)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(self.folder)))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.http.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.cookie = {"Cookie": "paperreading_browser=" + self.token}

    async def asyncTearDown(self):
        await asyncio.to_thread(self.http.shutdown)
        self.http.server_close()
        self.thread.join(timeout=2)
        self.state_patch.stop()
        self.viewer.close()
        await self.viewer.wait_closed()
        self.vnc.close()
        await self.vnc.wait_closed()
        self.temporary.cleanup()

    async def get(self, path, cookie=False):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        headers = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nConnection: close\r\n"
        if cookie:
            headers += "Cookie: " + self.cookie["Cookie"] + "\r\n"
        writer.write((headers + "\r\n").encode())
        await writer.drain()
        try:
            payload = await asyncio.wait_for(reader.read(), timeout=5)
        finally:
            writer.close()
            await writer.wait_closed()
        head, body = payload.split(b"\r\n\r\n", 1)
        return int(head.split()[1]), head.decode(), body

    async def test_no_key_cannot_access_viewer_or_assets(self):
        for path in ["/browser/", "/browser/core/rfb.js", "/browser/?key=wrong", "/browser/?key=a&key=b"]:
            status, headers, body = await self.get(path)
            self.assertEqual(status, 403, path)
            self.assertNotIn(self.token.encode(), body)

    async def test_private_link_sets_cookie_and_removes_key_from_url(self):
        status, headers, body = await self.get("/browser/?key=" + self.token)
        self.assertEqual(status, 303)
        self.assertIn("Location: /browser/", headers)
        self.assertIn("HttpOnly; SameSite=Strict; Path=/browser/", headers)
        self.assertIn("Cache-Control: no-store", headers)
        self.assertEqual(body, b"")
        status, headers, body = await self.get("/browser/", cookie=True)
        self.assertEqual(status, 200)
        self.assertIn(b"./core/rfb.js", body)
        self.assertEqual(headers.lower().count("content-length:"), 1)
        self.assertEqual(headers.lower().count("content-type:"), 1)
        self.assertNotIn(self.token.encode(), body)

    async def test_asset_traversal_and_profile_files_are_hidden(self):
        status, _, body = await self.get("/browser/core/rfb.js", cookie=True)
        self.assertEqual(status, 200)
        self.assertIn(b"class RFB", body)
        for path in ["/browser/private.txt", "/browser/core/../private.txt", "/browser/core/%2e%2e/private.txt"]:
            status, _, body = await self.get(path, cookie=True)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"PRIVATE PROFILE CONTENT", body)

    async def test_websocket_requires_cookie_and_same_origin(self):
        for headers, origin in [({}, self.origin), (self.cookie, "https://untrusted.example")]:
            with self.assertRaises(InvalidStatus) as caught:
                async with connect(f"ws://127.0.0.1:{self.port}/browser/websockify", additional_headers=headers,
                                   origin=origin, subprotocols=["binary"], proxy=None):
                    self.fail("Unauthorized WebSocket accepted")
            self.assertEqual(caught.exception.response.status_code, 403)

    async def test_real_bidirectional_rfb_through_paperreading_port(self):
        async with connect(f"ws://127.0.0.1:{self.port}/browser/websockify", additional_headers=self.cookie,
                           origin=self.origin, subprotocols=["binary"], proxy=None) as websocket:
            self.assertEqual(await asyncio.wait_for(websocket.recv(), 5), b"RFB 003.008\n")
            await websocket.send(b"RFB 003.008\n")
            self.assertEqual(await asyncio.wait_for(self.vnc_received, 5), b"RFB 003.008\n")

    async def test_redirect_does_not_log_access_key(self):
        status, _, _ = await self.get("/browser?key=" + self.token)
        self.assertEqual(status, 302)
        self.assertTrue(self.logs)
        self.assertNotIn(self.token, "\n".join(self.logs))

    async def test_novnc_can_connect_without_a_websocket_subprotocol(self):
        async with connect(f"ws://127.0.0.1:{self.port}/browser/websockify", additional_headers=self.cookie,
                           origin=self.origin, proxy=None) as websocket:
            self.assertIsNone(websocket.subprotocol)
            self.assertEqual(await asyncio.wait_for(websocket.recv(), 5), b"RFB 003.008\n")
            await websocket.send(b"RFB 003.008\n")
            self.assertEqual(await asyncio.wait_for(self.vnc_received, 5), b"RFB 003.008\n")


if __name__ == "__main__":
    unittest.main()
