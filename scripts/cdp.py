"""Minimal CDP client: raw WebSocket over socket, no external dependencies.

Note the failure this client has to survive: after a few hundred chrome
operations the browser starts answering `HTTP/1.1 500` to the WebSocket
handshake for new targets. `retry_ws` turns that into a bounded backoff
instead of an exception that kills a 40-minute unattended run.
"""
import base64
import json
import os
import socket
import struct
import time
import urllib.request

import config


class WS:
    def __init__(self, url, timeout=30):
        # ws://host:port/path
        rest = url.split("://", 1)[1]
        hostport, path = rest.split("/", 1)
        self.path = "/" + path
        host, port = hostport.split(":") if ":" in hostport else (hostport, 80)
        self.sock = socket.create_connection((host, int(port)), timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n") % (self.path, hostport, key)
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = self.sock.recv(4096)
            if not d:
                raise RuntimeError("handshake closed")
            buf += d
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b"101" not in head.split(b"\r\n")[0]:
            self.sock.close()
            raise RuntimeError("handshake failed: %r" % head[:200])
        self.mid = 0

    def send(self, obj):
        data = json.dumps(obj).encode()
        hdr = bytearray([0x81])
        n = len(data)
        mask = os.urandom(4)
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", n)
        hdr += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(hdr) + masked)

    def _recv_exact(self, n):
        while len(self.buf) < n:
            d = self.sock.recv(65536)
            if not d:
                raise RuntimeError("socket closed")
            self.buf += d
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        while True:
            b1, b2 = self._recv_exact(2)
            op = b1 & 0x0F
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._recv_exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._recv_exact(8))[0]
            payload = self._recv_exact(ln) if ln else b""
            if op == 0x8:
                raise RuntimeError("ws close")
            if op in (0x9, 0xA):
                continue  # ping/pong
            try:
                return json.loads(payload.decode("utf-8", "replace"))
            except ValueError:
                continue

    def call(self, method, params=None, timeout=30):
        self.mid += 1
        mid = self.mid
        self.send({"id": mid, "method": method, "params": params or {}})
        t0 = time.time()
        while time.time() - t0 < timeout:
            msg = self.recv()
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})
        raise TimeoutError(method)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def targets(port=None):
    port = port or config.PORT
    d = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:%d/json/list" % port, timeout=10).read().decode("utf-8", "replace"))
    return [t for t in d if t.get("type") == "page"]


def pick(url_filter=None, skip=()):
    pages = [t for t in targets() if not any(s in (t.get("url") or "") for s in skip)]
    if url_filter:
        for p in pages:
            if url_filter in (p.get("url") or ""):
                return p
        return None
    return pages[0] if pages else None


def page_ws(port=None, url_filter=None, skip=()):
    """(ws_url, target) for a matching page. Raises when nothing matches."""
    port = port or config.PORT
    d = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:%d/json/list" % port, timeout=10).read().decode("utf-8", "replace"))
    pages = [t for t in d if t.get("type") == "page"]
    if url_filter:
        for p in pages:
            if url_filter in (p.get("url") or "") and not any(s in (p.get("url") or "") for s in skip):
                return p["webSocketDebuggerUrl"], p
        raise RuntimeError("no page matching %r (have %d tabs)" % (url_filter, len(pages)))
    usable = [p for p in pages if not any(s in (p.get("url") or "") for s in skip)]
    if not usable:
        raise RuntimeError("no pages")
    return usable[0]["webSocketDebuggerUrl"], usable[0]


def connect(url, tries=4, base_delay=2.0):
    """WS(url) with backoff - the browser 500s on handshake when tabs pile up."""
    last = None
    for i in range(tries):
        try:
            return WS(url)
        except (RuntimeError, OSError) as e:
            last = e
            config.sleep(base_delay * (i + 1))
    raise RuntimeError("connect failed after %d tries: %s" % (tries, last))


def evaljs(ws, expr, timeout=30):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                     "awaitPromise": True, "userGesture": True}, timeout)
    res = r.get("result", {})
    if r.get("exceptionDetails"):
        return {"__error": str(r["exceptionDetails"])[:1500]}
    if res.get("subtype") == "error":
        return {"__error": res.get("description", "")[:1500]}
    return res.get("value")


def ev(ws, expr, timeout=30):
    """evaljs that raises on a page-side exception, for code that must not guess."""
    v = evaljs(ws, expr, timeout)
    if isinstance(v, dict) and "__error" in v:
        raise RuntimeError("page error: " + v["__error"][:300])
    return v


if __name__ == "__main__":
    url, info = page_ws(config.PORT)
    print("TARGET:", info.get("title"), "|", info.get("url"))
    connect(url).call("Runtime.enable")
    print("OK connected")
