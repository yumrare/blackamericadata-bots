# Black America Data — bot team

Automated distribution for [blackamericadata.com](https://blackamericadata.com):
**10 posts a day to Bluesky**, rotating through the site's 800-article
catalog. A Nostr mirror is built into the engine and activates
automatically if a `NOSTR_PRIVATE_KEY` secret is set; until then the
team runs Bluesky-only (owner's call, 2026-11-04).

This team is a completely separate business system from the Happy Foods
push-bots fleet: separate Bluesky account, separate Nostr identity,
separate repo, separate credentials. No intersection.

- Bluesky: [@healthandfittness.bsky.social](https://bsky.app/profile/healthandfittness.bsky.social)
  (display name "Black America Data")
- Nostr identity (reserved, not yet wired): npub1eyhd2j70sdwk37jvsrzy8g7lplqs0lsxfyuk9zvcscpem0800qassmnnwp

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
- `.github/workflows/post.yml` — ten scheduled runs a day.

## Credentials

Live ONLY in this repo's GitHub secrets: `BSKY_HANDLE`,
`BSKY_APP_PASSWORD`, and `NOSTR_PRIVATE_KEY` (when wired).

## Post shape

Article title, a one-line hook from the article summary, the article
link, and section tags — e.g. `#BlackCities #BlackAmericaData`.
Composed to fit Bluesky's 300 characters; Nostr carries the same text.
