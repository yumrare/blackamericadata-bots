#!/usr/bin/env python3
"""Build catalog.json for the Black America Data bot team from the
site's article data (~/workspace/black-american-data/site/data/).

Each entry: {slug, title, url, section (tab slug), section_label,
summary}. Entries are interleaved round-robin across the six content
tabs so consecutive posts rotate sections instead of draining one
tab at a time.
"""
import glob
import json
import os

SITE_DATA = os.path.expanduser("~/workspace/black-american-data/site/data")
BASE = "https://blackamericadata.com"

LABELS = {
    "black-census": "Black Census",
    "black-business": "Black Business",
    "black-public-health": "Black Public Health",
    "black-education": "Black Education",
    "black-employment": "Black Employment",
    "black-cities": "Black Cities",
}


def main():
    per_tab = {}
    for path in sorted(glob.glob(os.path.join(SITE_DATA, "articles-*.json"))):
        for a in json.load(open(path)):
            tab = a["tab"]
            per_tab.setdefault(tab, []).append({
                "slug": a["slug"],
                "title": a["title"],
                "url": f"{BASE}/{a['slug']}.html",
                "section": tab,
                "section_label": LABELS.get(tab, tab),
                "summary": a["summary"],
            })
    tabs = sorted(per_tab, key=lambda t: LABELS[t])
    catalog = []
    i = 0
    while any(i < len(per_tab[t]) for t in tabs):
        for t in tabs:
            if i < len(per_tab[t]):
                catalog.append(per_tab[t][i])
        i += 1
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "catalog.json")
    with open(out, "w") as f:
        json.dump(catalog, f, indent=1, ensure_ascii=False)
    counts = {t: len(per_tab[t]) for t in tabs}
    print(f"catalog: {len(catalog)} articles; per-tab {counts} -> {out}")


if __name__ == "__main__":
    main()
