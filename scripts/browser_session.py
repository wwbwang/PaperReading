#!/usr/bin/env python3
"""Persistent local browser with an authenticated viewer on PaperReading's port."""

import argparse
import asyncio
import fcntl
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.browser_viewer import serve_viewer

RUNTIME = ROOT / ".runtime/browser-session"
TOOLS = ROOT / ".runtime/browser-tools"
STATE = RUNTIME / "state.json"
CDP_PORT, VNC_PORT, VIEWER_PORT = 9226, 5906, 8765


def read_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(STATE)


def alive(state):
    try:
        command = Path(f"/proc/{int(state['pid'])}/cmdline").read_bytes().split(b"\0")
        return str(Path(__file__).resolve()).encode() in command and b"_run" in command
    except (OSError, KeyError, ValueError):
        return False


def browser_json(route):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{CDP_PORT}{route}", timeout=3) as response:
        return json.load(response)


def dependencies():
    candidates = [os.environ.get("PAPERREADING_CHROME"), shutil.which("google-chrome"),
                  "/root/.cache/ms-playwright/chromium-1124/chrome-linux/chrome"]
    chrome = next((p for p in candidates if p and Path(p).is_file()), None)
    vnc = shutil.which("x11vnc") or str(TOOLS / "root/usr/bin/x11vnc")
    assets = TOOLS / "noVNC-1.6.0"
    missing = [name for name in ["Xvfb", "xauth"] if not shutil.which(name)]
    if not chrome:
        missing.append("Chrome (or PAPERREADING_CHROME)")
    if not Path(vnc).is_file():
        missing.append("x11vnc")
    if not (assets / "core/rfb.js").is_file():
        missing.append("noVNC 1.6.0")
    try:
        import websockets
    except ImportError:
        missing.append("websockets (see requirements-browser.txt)")
    if missing:
        raise RuntimeError("Missing: " + ", ".join(missing) + ". Run scripts/setup_browser.py first.")
    return chrome, vnc, assets


async def command(method, params=None, target=None):
    """Use the persisted browser, never launch a replacement for a failed command."""
    from websockets.asyncio.client import connect
    state = read_state()
    if not alive(state) or state.get("phase") != "ready":
        raise RuntimeError("Browser is not running. Run: python scripts/browser_session.py start")
    version = browser_json("/json/version")
    async with connect(version["webSocketDebuggerUrl"], proxy=None, max_size=16 * 1024 * 1024) as websocket:
        counter = 0

        async def call(name, values=None, session=None):
            nonlocal counter
            counter += 1
            message = {"id": counter, "method": name, "params": values or {}}
            if session:
                message["sessionId"] = session
            await websocket.send(json.dumps(message))
            async with asyncio.timeout(30):
                while True:
                    result = json.loads(await websocket.recv())
                    if result.get("id") == counter:
                        if "error" in result:
                            raise RuntimeError(result["error"].get("message", "CDP request failed"))
                        return result.get("result", {})

        if target:
            targets = (await call("Target.getTargets"))["targetInfos"]
            selected = next((t for t in targets if t["targetId"] == target and t["type"] == "page"), None)
            if not selected or urlsplit(selected["url"]).hostname != "openreview.net":
                raise ValueError("Select an OpenReview page from the tabs command")
            session = (await call("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
            return await call(method, params, session)
        return await call(method, params)


async def supervise():
    chrome, vnc, assets = dependencies()
    lock = (RUNTIME / "session.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    for port in [CDP_PORT, VNC_PORT, VIEWER_PORT]:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    display = next(n for n in range(90, 110) if not Path(f"/tmp/.X{n}-lock").exists())
    token_file = RUNTIME / "access-key"
    token = token_file.read_text().strip() if token_file.exists() else secrets.token_urlsafe(32)
    token_file.write_text(token + "\n")
    authority = RUNTIME / "Xauthority"
    subprocess.run(["xauth", "-f", str(authority), "add", f":{display}", ".", secrets.token_hex(16)], check=True)
    env = os.environ.copy()
    env.update(DISPLAY=f":{display}", XAUTHORITY=str(authority))
    libraries = [TOOLS / "root/usr/lib/x86_64-linux-gnu", TOOLS / "root/lib/x86_64-linux-gnu"]
    env["LD_LIBRARY_PATH"] = ":".join([*(str(p) for p in libraries), env.get("LD_LIBRARY_PATH", "")])
    state = {"pid": os.getpid(), "phase": "starting", "display": display,
             "cdp_port": CDP_PORT, "viewer_port": VIEWER_PORT}
    save_state(state)
    children, logs = [], []
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in [signal.SIGTERM, signal.SIGINT]:
        loop.add_signal_handler(sig, stopped.set)

    def launch(name, args):
        log = (RUNTIME / f"{name}.log").open("a")
        logs.append(log)
        child = subprocess.Popen(args, env=env, stdout=log, stderr=log)
        children.append(child)
        return child

    try:
        launch("display", ["Xvfb", f":{display}", "-screen", "0", "1280x900x24", "-nolisten", "tcp", "-auth", str(authority)])
        for _ in range(100):
            if Path(f"/tmp/.X11-unix/X{display}").exists():
                break
            if children[0].poll() is not None:
                raise RuntimeError("Xvfb failed; see display.log")
            await asyncio.sleep(0.1)
        launch("vnc", [vnc, "-display", f":{display}", "-auth", str(authority), "-localhost", "-noipv6",
                       "-rfbport", str(VNC_PORT), "-nopw", "-forever", "-shared", "-noxdamage"])
        profile = RUNTIME / "profile"
        launch("chrome", [chrome, "--no-sandbox", "--disable-dev-shm-usage", "--no-first-run",
                          "--no-default-browser-check", "--disable-save-password-bubble",
                          "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={CDP_PORT}",
                          f"--user-data-dir={profile}", "--window-size=1280,900", "--window-position=0,0",
                          "https://openreview.net/login"])
        for _ in range(150):
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A browser process exited; see the session logs")
            try:
                await asyncio.to_thread(browser_json, "/json/version")
                with socket.create_connection(("127.0.0.1", VNC_PORT), timeout=1):
                    pass
                break
            except OSError:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError("Browser startup timed out")
        async with await serve_viewer(token, VIEWER_PORT, VNC_PORT, assets):
            state["phase"] = "ready"
            save_state(state)
            while not stopped.is_set():
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("A browser process exited; restart the session")
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=1)
                except TimeoutError:
                    pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    await asyncio.to_thread(child.wait, timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    await asyncio.to_thread(child.wait)
        for log in logs:
            log.close()
        state["phase"] = "stopped"
        save_state(state)
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status", "tabs", "open", "read", "evaluate", "_run"])
    parser.add_argument("--url", default="https://openreview.net/login")
    parser.add_argument("--target")
    parser.add_argument("--file", type=Path, help="JavaScript expression file, evaluated only on an OpenReview tab")
    args = parser.parse_args()
    os.umask(0o077)
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME.chmod(0o700)
    state = read_state()
    if args.action == "_run":
        asyncio.run(supervise())
    elif args.action == "start":
        dependencies()
        if not alive(state):
            with (RUNTIME / "session.log").open("a") as log:
                child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_run"],
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            for _ in range(30):
                state = read_state()
                if alive(state):
                    break
                if child.poll() is not None:
                    raise RuntimeError("Browser startup failed; see .runtime/browser-session/session.log")
                time.sleep(0.1)
        print(json.dumps({"phase": state.get("phase"), "message": "Use status to verify startup",
                          "viewer": "/browser/?key=" + (RUNTIME / "access-key").read_text().strip()}, ensure_ascii=False))
    elif args.action == "status":
        result = {"running": alive(state), "phase": state.get("phase", "not-started")}
        if result["running"] and result["phase"] == "ready":
            result["browser"] = browser_json("/json/version")["Browser"]
            result["openreview_tabs"] = [t["id"] for t in browser_json("/json")
                                         if t.get("type") == "page" and urlsplit(t.get("url", "")).hostname == "openreview.net"]
        print(json.dumps(result))
    elif args.action == "stop":
        if alive(state):
            os.kill(state["pid"], signal.SIGTERM)
            for _ in range(100):
                if not alive(read_state()):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Still stopping; check status before restarting")
        print("Stopped; the login profile is preserved.")
    elif args.action == "tabs":
        result = asyncio.run(command("Target.getTargets"))
        print(json.dumps([t for t in result["targetInfos"] if t["type"] == "page"
                          and urlsplit(t["url"]).hostname == "openreview.net"], ensure_ascii=False))
    elif args.action == "open":
        parts = urlsplit(args.url)
        if parts.scheme != "https" or parts.hostname != "openreview.net" or parts.username or parts.password or parts.port:
            raise ValueError("Only https://openreview.net URLs are allowed")
        print(json.dumps(asyncio.run(command("Target.createTarget", {"url": args.url}))))
    else:
        if not args.target:
            parser.error("--target is required; use tabs to find an OpenReview page")
        if args.action == "evaluate" and not args.file:
            parser.error("evaluate requires --file")
        expression = args.file.read_text() if args.action == "evaluate" else "({url:location.href,title:document.title,text:document.body.innerText.slice(0,5000)})"
        result = asyncio.run(command("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}, args.target))
        if result.get("exceptionDetails"):
            raise RuntimeError("Page evaluation failed")
        print(json.dumps(result.get("result", {}).get("value"), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, TimeoutError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
