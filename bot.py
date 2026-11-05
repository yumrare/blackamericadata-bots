#!/usr/bin/env python3
"""
bot.py — Black America Data bot team (Bluesky + Nostr).

A COMPLETELY SEPARATE team from the Happy Foods push-bots fleet
(Dee's order, 2026-11-04): its own Bluesky account, its own Nostr
identity, its own repo and credentials, no intersection. It posts
articles from blackamericadata.com — 6 posts a day to Bluesky, each
mirrored to Nostr (12 posts a day total), rotating through the
800-article catalog with per-platform state so nothing ever posts
twice. Pure stdlib; the AT Protocol and Nostr primitives follow the
proven push-bots fleet implementations.

Modes:
  post            post the next unposted article to Bluesky, then
                  mirror the same text to Nostr. If a previous run
                  reached Bluesky but its Nostr mirror failed, the
                  mirror is retried first. An item is marked posted
                  on a platform only after that platform accepts it.
  post --dry      compose the next post and print it; touch nothing.
  profile-nostr   publish the Nostr kind-0 profile (name, tagline,
                  emblem, website) for this team's identity.
  npub            print the team's Nostr npub from NOSTR_PRIVATE_KEY.
  selftest        offline checks: Schnorr sign/verify round-trip,
                  bech32 round-trip, catalog + compose sanity.

Env: BSKY_HANDLE, BSKY_APP_PASSWORD (Bluesky), NOSTR_PRIVATE_KEY
(hex or nsec), NOSTR_RELAYS (optional, comma-separated).
Credentials live ONLY in this repo's GitHub secrets.
"""

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "blackamericadata-bots/1.0 (+https://blackamericadata.com)"
BASE = "https://blackamericadata.com"
TAGLINE = "The leading resource on Black American Population Data and Insights."
SECTION_TAGS = {
    "black-census": "BlackCensus",
    "black-business": "BlackBusiness",
    "black-public-health": "BlackPublicHealth",
    "black-education": "BlackEducation",
    "black-employment": "BlackEmployment",
    "black-cities": "BlackCities",
}

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(HERE, "catalog.json")
STATE_PATH = os.path.join(HERE, "state.json")


def log(msg):
    print(msg, flush=True)


def now():
    return datetime.now(timezone.utc)

def xrpc(method, url, token=None, data=None, content_type="application/json"):
    body = None
    headers = {"User-Agent": UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        body = bytes(data) if isinstance(data, (bytes, bytearray)) else json.dumps(data).encode()
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


class Session:
    def __init__(self):
        self.handle = os.environ["BSKY_HANDLE"]
        s = xrpc("POST", "https://bsky.social/xrpc/com.atproto.server.createSession",
                 data={"identifier": self.handle, "password": os.environ["BSKY_APP_PASSWORD"]})
        self.token, self.did = s["accessJwt"], s["did"]

    def post(self, text, embed=None):
        facets = build_facets(text)
        rec = {"$type": "app.bsky.feed.post", "text": text,
               "createdAt": now().isoformat().replace("+00:00", "Z"), "langs": ["en"]}
        if facets:
            rec["facets"] = facets
        if embed:
            rec["embed"] = embed
        out = xrpc("POST", "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                   token=self.token,
                   data={"repo": self.did, "collection": "app.bsky.feed.post", "record": rec})
        return out.get("uri", "")

    def upload(self, img, mime):
        return xrpc("POST", "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                    token=self.token, data=img, content_type=mime)["blob"]


def build_facets(text):
    """Link facets for URLs and tag facets for #hashtags in the text."""
    facets = []
    import re
    for m in re.finditer(r"https?://[^\s]+", text):
        u = m.group(0).rstrip(".,)")
        facets.append({"index": {"byteStart": len(text[:m.start()].encode()),
                                 "byteEnd": len(text[:m.start()].encode()) + len(u.encode())},
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": u}]})
    for m in re.finditer(r"#(\w+)", text):
        facets.append({"index": {"byteStart": len(text[:m.start()].encode()),
                                 "byteEnd": len(text[:m.end()].encode())},
                       "features": [{"$type": "app.bsky.richtext.facet#tag",
                                      "tag": m.group(1)}]})
    return facets


NOSTR_RELAYS = ("wss://relay.damus.io", "wss://nos.lol",
                "wss://relay.nostr.band", "wss://relay.primal.net")

# secp256k1 domain parameters + BIP-340 Schnorr, pure stdlib.
_SP = 2**256 - 2**32 - 977
_SN = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_SG = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
       0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _sp_add(Pt, Qt):
    if Pt is None:
        return Qt
    if Qt is None:
        return Pt
    if Pt[0] == Qt[0] and Pt[1] != Qt[1]:
        return None
    if Pt == Qt:
        lam = 3 * Pt[0] * Pt[0] * pow(2 * Pt[1], _SP - 2, _SP) % _SP
    else:
        lam = (Qt[1] - Pt[1]) * pow(Qt[0] - Pt[0], _SP - 2, _SP) % _SP
    x = (lam * lam - Pt[0] - Qt[0]) % _SP
    return (x, (lam * (Pt[0] - x) - Pt[1]) % _SP)


def _sp_mul(k, Pt):
    R = None
    while k:
        if k & 1:
            R = _sp_add(R, Pt)
        Pt = _sp_add(Pt, Pt)
        k >>= 1
    return R


def _b32(i):
    return i.to_bytes(32, "big")


def _tagged_hash(tag, msg):
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + msg).digest()


def _lift_x(x):
    if x >= _SP:
        raise ValueError("x out of range")
    y_sq = (pow(x, 3, _SP) + 7) % _SP
    y = pow(y_sq, (_SP + 1) // 4, _SP)
    if pow(y, 2, _SP) != y_sq:
        raise ValueError("x is not on the curve")
    return (x, y if y % 2 == 0 else _SP - y)


def _schnorr_sign(msg32, sk_bytes, aux32):
    """BIP-340 Schnorr signature over a 32-byte message."""
    d0 = int.from_bytes(sk_bytes, "big")
    if not 1 <= d0 < _SN:
        raise ValueError("bad secret key")
    Pt = _sp_mul(d0, _SG)
    d = d0 if Pt[1] % 2 == 0 else _SN - d0
    t = _b32(d ^ int.from_bytes(_tagged_hash("BIP0340/aux", aux32), "big"))
    rand = _tagged_hash("BIP0340/nonce", t + _b32(Pt[0]) + msg32)
    k0 = int.from_bytes(rand, "big") % _SN
    if k0 == 0:
        raise RuntimeError("BIP-340 nonce failure (never in practice)")
    Rt = _sp_mul(k0, _SG)
    k = k0 if Rt[1] % 2 == 0 else _SN - k0
    e = int.from_bytes(
        _tagged_hash("BIP0340/challenge", _b32(Rt[0]) + _b32(Pt[0]) + msg32),
        "big") % _SN
    return _b32(Rt[0]) + _b32((k + e * d) % _SN)


def _schnorr_verify(msg32, pub_hex, sig):
    try:
        Pt = _lift_x(int(pub_hex, 16))
    except ValueError:
        return False
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    if r >= _SP or s >= _SN:
        return False
    e = int.from_bytes(
        _tagged_hash("BIP0340/challenge", sig[:32] + bytes.fromhex(pub_hex)
                     + msg32), "big") % _SN
    Rt = _sp_add(_sp_mul(s, _SG), _sp_mul(_SN - e, Pt))
    return Rt is not None and Rt[1] % 2 == 0 and Rt[0] == r


_BECH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    chk = 1
    gen = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= gen[i]
    return chk


def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for v in data:
        acc = (acc << frombits) | v
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def _bech32_hrp_expand(hrp):
    """BIP-173 HRP expansion: high 3 bits of each char, a zero, then
    the low 5 bits. (Bug caught 2026-10-21 by njump's validator: the
    first cut fed raw ord() values into the polymod — self-consistent
    for round-trips but rejected by every real bech32 checker.)"""
    return ([ord(c) >> 5 for c in hrp] + [0]
            + [ord(c) & 31 for c in hrp])


def bech32_encode(hrp, data_bytes):
    """BIP-173 bech32 (Nostr NIP-19 uses it for npub/nsec)."""
    data = _convertbits(data_bytes, 8, 5)
    values = _bech32_hrp_expand(hrp) + data
    poly = _bech32_polymod(values + [0] * 6) ^ 1
    checksum = [(poly >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_BECH[d] for d in data + checksum)


def bech32_decode(s):
    s = s.strip().lower()
    pos = s.rfind("1")
    hrp = s[:pos]
    data = [_BECH.index(c) for c in s[pos + 1:]]
    if _bech32_polymod(_bech32_hrp_expand(hrp) + data) != 1:
        raise ValueError("bad bech32 checksum")
    return hrp, bytes(_convertbits(data[:-6], 5, 8, pad=False))


def nostr_enabled():
    return bool(os.environ.get("NOSTR_PRIVATE_KEY"))


def _nostr_keys():
    """(secret key bytes, x-only pubkey hex) from NOSTR_PRIVATE_KEY,
    which may be 64-char hex or an nsec."""
    raw = os.environ["NOSTR_PRIVATE_KEY"].strip()
    if raw.startswith("nsec1"):
        _, sk = bech32_decode(raw)
    else:
        sk = bytes.fromhex(raw)
    if len(sk) != 32:
        raise ValueError("NOSTR_PRIVATE_KEY must be 32 bytes (hex or nsec)")
    Pt = _sp_mul(int.from_bytes(sk, "big"), _SG)
    return sk, "%064x" % Pt[0]


def nostr_npub():
    _, pub = _nostr_keys()
    return bech32_encode("npub", bytes.fromhex(pub))


def _nostr_event(kind, content, tags=None):
    """Build + sign a Nostr event (NIP-01). Returns the event dict."""
    sk, pub = _nostr_keys()
    created = int(now().timestamp())
    tags = tags or []
    ser = json.dumps([0, pub, created, kind, tags, content],
                     ensure_ascii=False, separators=(",", ":"))
    eid = hashlib.sha256(ser.encode("utf-8")).digest()
    return {"id": eid.hex(), "pubkey": pub, "created_at": created,
            "kind": kind, "tags": tags, "content": content,
            "sig": _schnorr_sign(eid, sk, os.urandom(32)).hex()}


def _ws_tcp(host, port, timeout):
    """TCP connection to host:port, honoring the standard *_proxy
    env vars via an HTTP CONNECT tunnel when one is configured
    (Nova's VM egresses through a proxy; GitHub Actions does not, and
    there this is a plain direct connection). urllib gets this for
    free; a raw socket must ask."""
    proxies = urllib.request.getproxies()
    no_proxy = [h.strip() for h in proxies.get("no", "").split(",")]
    proxy = None
    if host not in no_proxy:
        proxy = proxies.get("https") or proxies.get("all")
    if not proxy:
        return socket.create_connection((host, port), timeout=timeout)
    pm = urllib.parse.urlparse(proxy)
    sock = socket.create_connection(
        (pm.hostname, pm.port or 3128), timeout=timeout)
    lines = [f"CONNECT {host}:{port} HTTP/1.1", f"Host: {host}:{port}"]
    if pm.username:
        cred = base64.b64encode(
            f"{urllib.parse.unquote(pm.username)}:"
            f"{urllib.parse.unquote(pm.password or '')}".encode()).decode()
        lines.append(f"Proxy-Authorization: Basic {cred}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("proxy closed during CONNECT")
        buf += chunk
    if b" 200" not in buf.split(b"\r\n")[0]:
        raise ConnectionError(
            f"proxy CONNECT failed: {buf.splitlines()[0]!r}")
    return sock


class _WS:
    """Minimal WebSocket client (RFC 6455) — just enough to publish
    one event and read the relay's OK. Client frames are masked as
    the spec requires."""

    def __init__(self, url, timeout=10):
        m = urllib.parse.urlparse(url)
        host = m.hostname
        port = m.port or (443 if m.scheme == "wss" else 80)
        path = m.path or "/"
        if m.query:
            path += "?" + m.query
        raw = _ws_tcp(host, port, timeout)
        if m.scheme == "wss":
            raw = ssl.create_default_context().wrap_socket(
                raw, server_hostname=host)
        self.sock = raw
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            f"User-Agent: {UA}\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("relay closed during handshake")
            buf += chunk
        head, _, self.buf = buf.partition(b"\r\n\r\n")
        if b" 101" not in head.split(b"\r\n")[0]:
            raise ConnectionError(
                f"relay handshake failed: {head.splitlines()[0]!r}")

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        ln = len(payload)
        if ln < 126:
            head = bytes([0x80 | opcode, 0x80 | ln])
        elif ln < 65536:
            head = bytes([0x80 | opcode, 0xFE]) + struct.pack(">H", ln)
        else:
            head = bytes([0x80 | opcode, 0xFF]) + struct.pack(">Q", ln)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(head + mask + masked)

    def send_text(self, text):
        self._send_frame(1, text.encode("utf-8"))

    def _read_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("relay closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv_msg(self, timeout):
        self.sock.settimeout(timeout)
        frag = b""
        while True:
            b0, b1 = self._read_exact(2)
            fin, op = b0 & 0x80, b0 & 0x0F
            ln = b1 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._read_exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._read_exact(8))[0]
            if b1 & 0x80:
                self._read_exact(4)
            payload = self._read_exact(ln) if ln else b""
            if op == 9:  # ping -> pong, keep waiting
                self._send_frame(10, payload)
                continue
            if op == 8:
                raise ConnectionError("relay closed the socket")
            frag += payload
            if fin:
                return frag.decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass


def nostr_relays():
    raw = os.environ.get("NOSTR_RELAYS", "").strip()
    if raw:
        return tuple(r.strip() for r in raw.split(",") if r.strip())
    return NOSTR_RELAYS


def nostr_publish(ev):
    """Publish one signed event to every configured relay; returns
    how many accepted it. Raises if none did."""
    ok = 0
    errors = []
    for url in nostr_relays():
        ws = None
        try:
            ws = _WS(url)
            ws.send_text(json.dumps(["EVENT", ev]))
            deadline = time.time() + 10
            while time.time() < deadline:
                arr = json.loads(ws.recv_msg(max(1.0, deadline - time.time())))
                if arr and arr[0] == "OK" and arr[1] == ev["id"]:
                    if len(arr) > 2 and arr[2]:
                        ok += 1
                    else:
                        errors.append(
                            f"{url}: rejected "
                            f"({arr[3] if len(arr) > 3 else 'no reason'})")
                    break
        except Exception as e:  # noqa: BLE001 — try the next relay
            errors.append(f"{url}: {e}")
        finally:
            if ws is not None:
                ws.close()
    if ok == 0:
        raise RuntimeError("no relay accepted the event ("
                           + "; ".join(errors) + ")")
    return ok



# ------------------------------------------------------------------
# Black America Data team logic (catalog, state, compose, modes)
# ------------------------------------------------------------------

def post_nostr_note(text):
    """Publish one kind-1 note with the team's Nostr identity.
    Returns the event id. No footer rule — a BAD post carries its
    own article link."""
    ev = _nostr_event(1, text)
    got = nostr_publish(ev)
    log(f"  nostr: accepted by {got} relay(s)")
    return ev["id"]


def load_catalog():
    with open(CATALOG_PATH) as f:
        return json.load(f)


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            st = json.load(f)
    else:
        st = {}
    st.setdefault("bluesky", {"posted": {}})
    st.setdefault("nostr", {"posted": {}})
    return st


def save_state(st):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def compose(item):
    """Post text for one article, sized for Bluesky (<=300 chars):
    title, one-line hook from the summary, link, section tag."""
    tag = SECTION_TAGS.get(item["section"], "BlackAmericaData")
    tail = f"\n\n{item['url']}\n\n#{tag} #BlackAmericaData"
    head = item["title"]
    hook = " ".join(item["summary"].split())
    text = f"{head}\n\n{hook}{tail}"
    if len(text) > 297:
        room = 297 - len(head) - len(tail) - 2 - 1  # hook + ellipsis
        hook = hook[:max(room, 0)].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        text = f"{head}\n\n{hook}{tail}"
    return text


def next_unposted(catalog, st):
    posted = st["bluesky"]["posted"]
    for item in catalog:
        if item["slug"] not in posted:
            return item
    return None


def pending_mirror(catalog, st):
    """Oldest item posted to Bluesky whose Nostr mirror is missing."""
    by_slug = {it["slug"]: it for it in catalog}
    for slug in st["bluesky"]["posted"]:
        if slug not in st["nostr"]["posted"] and slug in by_slug:
            return by_slug[slug]
    return None


def mode_post(dry=False):
    catalog = load_catalog()
    st = load_state()
    item = pending_mirror(catalog, st) if nostr_enabled() else None
    mirroring = item is not None
    if item is None:
        item = next_unposted(catalog, st)
    if item is None:
        log("catalog exhausted: all articles posted to Bluesky")
        return 0
    text = compose(item)
    if dry:
        log(f"[dry] {'mirror-only' if mirroring else 'new post'}: "
            f"{item['slug']}")
        log(text)
        log(f"[dry] {len(text)} chars")
        return 0
    if not mirroring:
        sess = Session()
        uri = sess.post(text)
        st["bluesky"]["posted"][item["slug"]] = {
            "uri": uri, "at": now().isoformat()}
        save_state(st)
        log(f"bluesky: posted {item['slug']} -> {uri}")
    if not nostr_enabled():
        log("nostr: no key configured — Bluesky-only run, mirror skipped")
        return 0
    ev_id = post_nostr_note(text)
    st["nostr"]["posted"][item["slug"]] = {
        "id": ev_id, "at": now().isoformat()}
    save_state(st)
    log(f"nostr: posted {item['slug']} -> {ev_id}")
    return 0


def mode_profile_nostr(dry=False):
    _, pub = _nostr_keys()
    profile = {
        "name": "Black America Data",
        "about": TAGLINE,
        "picture": f"{BASE}/assets/emblem.webp",
        "website": BASE,
        "display_name": "Black America Data",
    }
    if dry:
        log(f"[dry] kind-0 for {bech32_encode('npub', bytes.fromhex(pub))}")
        log(json.dumps(profile, indent=1))
        return 0
    ev = _nostr_event(0, json.dumps(profile, ensure_ascii=False))
    got = nostr_publish(ev)
    log(f"nostr profile: accepted by {got} relay(s); "
        f"npub {bech32_encode('npub', bytes.fromhex(pub))}")
    return 0


def mode_selftest():
    # Schnorr sign/verify round-trip on a throwaway key.
    sk = bytes(range(1, 33))
    os.environ["NOSTR_PRIVATE_KEY"] = sk.hex()
    _, pub = _nostr_keys()
    msg = hashlib.sha256(b"blackamericadata-bots selftest").digest()
    sig = _schnorr_sign(msg, sk, b"\x07" * 32)
    assert _schnorr_verify(msg, pub, sig), "schnorr verify failed"
    # bech32 round-trip
    enc = bech32_encode("npub", bytes.fromhex(pub))
    hrp, raw = bech32_decode(enc)
    assert hrp == "npub" and raw.hex() == pub, "bech32 round-trip failed"
    # Catalog + compose sanity
    catalog = load_catalog()
    assert len(catalog) >= 800, f"catalog too small: {len(catalog)}"
    worst = max(len(compose(it)) for it in catalog)
    assert worst <= 300, f"compose overflow: {worst}"
    log(f"selftest OK: schnorr + bech32 round-trip; catalog "
        f"{len(catalog)} articles; longest post {worst} chars")
    return 0


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    dry = "--dry" in argv
    mode = args[1] if len(args) > 1 else "post"
    if mode == "post":
        return mode_post(dry=dry)
    if mode == "profile-nostr":
        return mode_profile_nostr(dry=dry)
    if mode == "npub":
        log(nostr_npub())
        return 0
    if mode == "selftest":
        return mode_selftest()
    log(f"unknown mode: {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
