#!/usr/bin/env python3
"""Install browser viewer assets under .runtime without modifying system packages."""

import hashlib
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".runtime/browser-tools"
NOVNC_URL = "https://codeload.github.com/novnc/noVNC/tar.gz/refs/tags/v1.6.0"
NOVNC_SHA256 = "5066103959ef4e9b10f37e5a148627360dd8414e4cf8a7db92bdbd022e728aaa"


def main():
    missing = [name for name in ["Xvfb", "xauth", "apt-get", "dpkg-deb"] if not shutil.which(name)]
    if missing:
        raise SystemExit("Install these host prerequisites first: " + ", ".join(missing))
    debs = TOOLS / "debs"
    debs.mkdir(parents=True, exist_ok=True)
    if not (TOOLS / "root/usr/bin/x11vnc").is_file():
        subprocess.run(["apt-get", "download", "x11vnc", "libvncserver1", "libvncclient1", "liblzo2-2", "libxtst6"], cwd=debs, check=True)
        for package in debs.glob("*.deb"):
            subprocess.run(["dpkg-deb", "-x", str(package), str(TOOLS / "root")], check=True)
    archive = TOOLS / "novnc-v1.6.0.tar.gz"
    if not archive.is_file():
        with urllib.request.urlopen(NOVNC_URL, timeout=45) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != NOVNC_SHA256:
            raise SystemExit("noVNC download checksum mismatch")
        archive.write_bytes(payload)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != NOVNC_SHA256:
        raise SystemExit("Cached noVNC checksum mismatch")
    with tarfile.open(archive) as source:
        source.extractall(TOOLS, filter="data")
    print("Viewer assets ready. Python dependency: python -m pip install -r requirements-browser.txt")
    print("Start: python scripts/browser_session.py start")


if __name__ == "__main__":
    main()
