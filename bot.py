#!/usr/bin/env python3
"""
bot.py — Black America Data bot team (Bluesky).

A COMPLETELY SEPARATE team from the Happy Foods push-bots fleet
(Dee's order, 2026-11-04): its own Bluesky account, its own repo
and credentials, no intersection. It posts articles from
blackamericadata.com — 10 posts a day to Bluesky, rotating through
the 800-article catalog with rotation state so nothing ever posts
twice. Pure stdlib; the AT Protocol primitives follow the proven
push-bots fleet implementations. (A Nostr mirror was built and
then removed at Dee's order, 2026-11-04 — the team is Bluesky-only.)

Modes:
  post            post the next unposted article to Bluesky. An
                  item is marked posted only after Bluesky
                  accepts it.
  post --dry      compose the next post and print it; touch nothing.
  selftest        offline checks: catalog + compose sanity.

Env: BSKY_HANDLE, BSKY_APP_PASSWORD.
Credentials live ONLY in this repo's GitHub secrets.
"""

import json
import os
import sys
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
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"xrpc {method} {url} -> HTTP {e.code}: {detail}")
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


# ------------------------------------------------------------------
# Black America Data team logic (catalog, state, compose, modes)
# ------------------------------------------------------------------

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
    st.pop("nostr", None)  # legacy key from the removed Nostr mirror
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


def mode_post(dry=False):
    catalog = load_catalog()
    st = load_state()
    item = next_unposted(catalog, st)
    if item is None:
        log("catalog exhausted: all articles posted to Bluesky")
        return 0
    text = compose(item)
    if dry:
        log(f"[dry] new post: {item['slug']}")
        log(text)
        log(f"[dry] {len(text)} chars")
        return 0
    sess = Session()
    uri = sess.post(text)
    st["bluesky"]["posted"][item["slug"]] = {
        "uri": uri, "at": now().isoformat()}
    save_state(st)
    log(f"bluesky: posted {item['slug']} -> {uri}")
    return 0


def mode_selftest():
    catalog = load_catalog()
    assert len(catalog) >= 800, f"catalog too small: {len(catalog)}"
    worst = max(len(compose(it)) for it in catalog)
    assert worst <= 300, f"compose overflow: {worst}"
    log(f"selftest OK: catalog {len(catalog)} articles; "
        f"longest post {worst} chars")
    return 0


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    dry = "--dry" in argv
    mode = args[1] if len(args) > 1 else "post"
    if mode == "post":
        return mode_post(dry=dry)
    if mode == "selftest":
        return mode_selftest()
    log(f"unknown mode: {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
