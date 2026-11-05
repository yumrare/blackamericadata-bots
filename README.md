# Black America Data — bot team

Automated distribution for [blackamericadata.com](https://blackamericadata.com):
**6 posts a day to Bluesky, each mirrored to Nostr — 12 posts a day** —
rotating through the site's 800-article catalog.

This team is a completely separate business system from the Happy Foods
push-bots fleet: separate Bluesky account, separate Nostr identity,
separate repo, separate credentials. No intersection.

## How it works

- `bot.py` — the engine (pure Python stdlib). Modes: `post`,
  `post --dry`, `profile-nostr`, `npub`, `selftest`.
- `catalog.json` — all 800 articles (title, URL, section, summary),
  interleaved round-robin across the six sections. Regenerate with
  `make_catalog.py` from the site's article data.
- `state.json` — per-platform rotation state, committed back by the
  workflow after each run. An article is marked posted on a platform
  only after that platform accepts the post; a failed Nostr mirror is
  retried at the start of the next run. Nothing ever posts twice.
- `.github/workflows/post.yml` — six scheduled runs a day.

## Credentials

Live ONLY in this repo's GitHub secrets: `BSKY_HANDLE`,
`BSKY_APP_PASSWORD`, `NOSTR_PRIVATE_KEY`. The Nostr private key exists
nowhere else; the local build copy was shredded after deploy.

## Post shape

Article title, a one-line hook from the article summary, the article
link, and section tags — e.g. `#BlackCities #BlackAmericaData`.
Composed to fit Bluesky's 300 characters; Nostr carries the same text.
