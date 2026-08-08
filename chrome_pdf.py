"""Headless Chrome PDF rendering over the DevTools Protocol.

The book is paginated in the browser by Paged.js, which needs an unbounded amount of
real time to lay out. Chrome's ``--print-to-pdf`` command line prints as soon as the
load event fires, and ``--virtual-time-budget`` expires in real milliseconds while
pagination is still running, so both silently truncate the book. The only reliable
signal is asking the page itself whether it has finished, which requires a DevTools
session. This module keeps that plumbing self-contained and dependency free.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"

ASSET_SOURCES = {
    "paged.polyfill.js": "https://unpkg.com/pagedjs@0.4.3/dist/paged.polyfill.js",
    "mermaid.min.js": "https://unpkg.com/mermaid@11/dist/mermaid.min.js",
    "eb-garamond-400-normal.woff2": "https://cdn.jsdelivr.net/npm/@fontsource/eb-garamond@5/files/eb-garamond-latin-400-normal.woff2",
    "eb-garamond-400-italic.woff2": "https://cdn.jsdelivr.net/npm/@fontsource/eb-garamond@5/files/eb-garamond-latin-400-italic.woff2",
    "eb-garamond-600-normal.woff2": "https://cdn.jsdelivr.net/npm/@fontsource/eb-garamond@5/files/eb-garamond-latin-600-normal.woff2",
    "eb-garamond-600-italic.woff2": "https://cdn.jsdelivr.net/npm/@fontsource/eb-garamond@5/files/eb-garamond-latin-600-italic.woff2",
    "inter-400-normal.woff2": "https://cdn.jsdelivr.net/npm/@fontsource/inter@5/files/inter-latin-400-normal.woff2",
    "inter-600-normal.woff2": "https://cdn.jsdelivr.net/npm/@fontsource/inter@5/files/inter-latin-600-normal.woff2",
}


def chrome_path() -> str | None:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("chrome") or shutil.which("msedge") or shutil.which("google-chrome")


def ensure_assets() -> Path:
    """Download the renderer assets once into assets/ and return that directory."""
    ASSETS.mkdir(exist_ok=True)
    missing = {name: url for name, url in ASSET_SOURCES.items() if not (ASSETS / name).exists()}
    if not missing:
        return ASSETS
    print(f"Downloading {len(missing)} rendering asset(s) into {ASSETS.relative_to(ROOT)}/ (one time only)")
    for name, url in missing.items():
        target = ASSETS / name
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                payload = response.read()
        except Exception as error:  # noqa: BLE001 - surfaced with actionable context
            raise RuntimeError(
                f"Could not download {name} from {url}. The first build needs network access; "
                f"afterwards the file is cached in {ASSETS}. Original error: {error}"
            ) from error
        target.write_bytes(payload)
        print(f"  {name} ({len(payload) // 1024} KB)")
    return ASSETS


class WebSocket:
    """Minimal RFC 6455 client, enough to talk to a local DevTools endpoint."""

    def __init__(self, url: str, timeout: float = 600) -> None:
        parsed = urlparse(url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        self.sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {parsed.hostname}:{parsed.port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("DevTools closed the connection during the handshake")
            buffer += chunk
        header, _, rest = buffer.partition(b"\r\n\r\n")
        if b" 101 " not in header.split(b"\r\n")[0] + b" ":
            raise RuntimeError(f"WebSocket handshake rejected: {header.splitlines()[0]!r}")
        self.buffer = rest

    def _read(self, count: int) -> bytes:
        while len(self.buffer) < count:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError("DevTools closed the connection")
            self.buffer += chunk
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def send(self, text: str) -> None:
        payload = text.encode()
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload)))

    def recv(self) -> str:
        chunks: list[bytes] = []
        while True:
            first, second = self._read(2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(length)
            if opcode == 0x8:
                raise ConnectionError("DevTools closed the connection")
            if opcode == 0x9:  # ping; DevTools does not expect a pong from us
                continue
            chunks.append(payload)
            if final:
                break
        return b"".join(chunks).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Browser:
    """A headless Chrome instance with one attached page session."""

    def __init__(self, binary: str) -> None:
        self.profile = Path(tempfile.mkdtemp(prefix="book-pdf-"))
        self.process = subprocess.Popen(
            [
                binary,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--remote-debugging-port=0",
                f"--user-data-dir={self.profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.ws = WebSocket(self._endpoint())
        self.message_id = 0
        self.session = self._attach()

    def _endpoint(self) -> str:
        port_file = self.profile / "DevToolsActivePort"
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("The browser exited before opening a DevTools endpoint")
            if port_file.exists():
                lines = port_file.read_text(encoding="utf-8").splitlines()
                if len(lines) >= 2:
                    return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
            time.sleep(0.05)
        raise RuntimeError("The browser did not expose a DevTools endpoint within 60 seconds")

    def _attach(self) -> str:
        target = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        return self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]

    def call(self, method: str, params: dict | None = None) -> dict:
        self.message_id += 1
        message: dict = {"id": self.message_id, "method": method, "params": params or {}}
        if getattr(self, "session", None):
            message["sessionId"] = self.session
        self.ws.send(json.dumps(message))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("id") != self.message_id:
                continue  # an event or another command's reply
            if "error" in reply:
                raise RuntimeError(f"{method} failed: {reply['error']}")
            return reply.get("result", {})

    def evaluate(self, expression: str) -> object:
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"]
            text = detail.get("exception", {}).get("description") or detail.get("text")
            raise RuntimeError(f"Page script failed: {text}")
        return result.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self.session = None
            self.call("Browser.close")
        except Exception:  # noqa: BLE001 - best effort shutdown
            self.process.kill()
        finally:
            self.ws.close()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
            shutil.rmtree(self.profile, ignore_errors=True)


def render_pdf(
    url: str,
    pdf_options: dict,
    ready_expression: str = "window.__pagedDone === true",
    collect: str | None = None,
    timeout: float = 900,
) -> tuple[bytes, object]:
    """Load ``url``, wait until the page reports itself finished, then print it.

    Returns the PDF bytes and, when ``collect`` is given, the value of that
    expression evaluated after pagination (used to read the heading page map).
    """
    binary = chrome_path()
    if binary is None:
        raise RuntimeError("Chrome or Edge was not found; the PDF needs one of them to render.")
    browser = Browser(binary)
    try:
        browser.call("Page.enable")
        browser.call("Page.navigate", {"url": url})
        deadline = time.time() + timeout
        while not browser.evaluate(ready_expression):
            failure = browser.evaluate("window.__pagedError || ''")
            if failure:
                raise RuntimeError(f"Pagination failed in the browser: {failure}")
            if time.time() > deadline:
                raise TimeoutError(f"The document did not finish paginating within {timeout:.0f}s")
            time.sleep(0.2)
        collected = browser.evaluate(collect) if collect else None
        response = browser.call("Page.printToPDF", pdf_options)
        return base64.b64decode(response["data"]), collected
    finally:
        browser.close()
