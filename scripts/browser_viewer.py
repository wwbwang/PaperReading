"""Private noVNC viewer and same-port HTTP/WebSocket proxy for PaperReading."""

import asyncio
import hmac
import json
import mimetypes
import select
import socket
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".runtime/browser-session/state.json"
COOKIE = "paperreading_browser"


def authorized(headers, token):
    cookie = SimpleCookie()
    try:
        cookie.load(headers.get("Cookie", ""))
        value = cookie[COOKIE].value if COOKIE in cookie else ""
    except CookieError:
        return False
    return hmac.compare_digest(value.encode(), token.encode())


def asset_path(root, path):
    path = unquote(urlsplit(path).path)
    if not path.startswith(("/core/", "/vendor/")) or any(part in {".", ".."} for part in path.split("/")):
        return None
    resolved = (root / path.lstrip("/")).resolve()
    return resolved if resolved.is_relative_to(root.resolve()) and resolved.is_file() else None


async def serve_viewer(token, port, vnc_port, asset_root):
    from websockets.asyncio.server import serve

    async def request(connection, request):
        parts = urlsplit(request.path)
        keys = parse_qs(parts.query).get("key", [])
        if parts.path == "/" and len(keys) == 1 and hmac.compare_digest(keys[0].encode(), token.encode()):
            response = connection.respond(HTTPStatus.SEE_OTHER, "")
            response.headers["Location"] = "/browser/"
            response.headers["Set-Cookie"] = f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/browser/"
        elif not authorized(request.headers, token):
            response = connection.respond(HTTPStatus.FORBIDDEN, "Open the private link from browser_session.py start.")
        elif parts.path == "/websockify":
            origin = urlsplit(request.headers.get("Origin", ""))
            if origin.scheme in {"http", "https"} and origin.netloc == request.headers.get("Host"):
                return None
            response = connection.respond(HTTPStatus.FORBIDDEN, "Invalid browser origin")
        elif parts.path == "/":
            response = connection.respond(HTTPStatus.OK, "")
            response.body = (ROOT / "scripts/browser_viewer.html").read_bytes()
            del response.headers["Content-Type"]
            response.headers["Content-Type"] = "text/html; charset=utf-8"
        else:
            path = asset_path(asset_root, request.path)
            response = connection.respond(HTTPStatus.OK if path else HTTPStatus.NOT_FOUND, "")
            if path:
                response.body = path.read_bytes()
                del response.headers["Content-Type"]
                response.headers["Content-Type"] = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        del response.headers["Content-Length"]
        response.headers["Content-Length"] = str(len(response.body))
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def relay(websocket):
        reader, writer = await asyncio.open_connection("127.0.0.1", vnc_port)

        async def to_vnc():
            async for message in websocket:
                if not isinstance(message, bytes):
                    await websocket.close(1003, "Binary RFB messages required")
                    return
                writer.write(message)
                await writer.drain()

        async def to_browser():
            while block := await reader.read(65536):
                await websocket.send(block)

        tasks = [asyncio.create_task(to_vnc()), asyncio.create_task(to_browser())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            await writer.wait_closed()

    return await serve(relay, "127.0.0.1", port, process_request=request,
                       subprotocols=["binary"], max_size=8 * 1024 * 1024,
                       select_subprotocol=lambda connection, protocols: "binary" if "binary" in protocols else None)


def proxy_browser(handler):
    """Proxy only the local viewer; never expose CDP or the browser profile."""
    try:
        state = json.loads(STATE.read_text())
        if state.get("phase") != "ready":
            raise ValueError("Browser is not ready")
        port = state["viewer_port"]
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Invalid viewer port")
        upstream = socket.create_connection(("127.0.0.1", port), timeout=5)
    except (OSError, ValueError, KeyError):
        handler.send_error(503, "Start the browser with python scripts/browser_session.py start")
        return
    handler.close_connection = True
    target = handler.path[len("/browser"):] or "/"
    if target.startswith("?"):
        target = "/" + target
    headers = dict(handler.headers.items())
    if headers.get("Upgrade", "").lower() != "websocket":
        headers["Connection"] = "close"
    request = f"GET {target} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
    try:
        upstream.sendall(request.encode("latin-1"))
        upstream.settimeout(None)
        # Copy raw bytes so HTTP buffering cannot consume the first RFB frame.
        while True:
            readable, _, _ = select.select([handler.connection, upstream], [], [], 60)
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                destination = upstream if source is handler.connection else handler.connection
                destination.sendall(data)
    except (ConnectionError, OSError):
        pass
    finally:
        upstream.close()
