# Black America Data — bot team

Automated distribution for [blackamericadata.com](https://blackamericadata.com):
**10 posts a day to Bluesky**, rotating through the site's 800-article
catalog.

This team is a completely separate business system from the Happy Foods
push-bots fleet: separate Bluesky account, separate repo, separate
credentials. No intersection. (A Nostr mirror was built on 2026-11-04
and removed the same day at the owner's order — the team is
Bluesky-only.)

- Bluesky: [@healthandfittness.bsky.social](https://bsky.app/profile/healthandfittness.bsky.social)
  (display name "Black America Data")

## How it works

- `bot.py` — the engine (pure Python stdlib). Modes: `post`,
  `post --dry`, `selftest`.
- `catalog.json` — all 800 articles (title, URL, section, summary),
  interleaved round-robin across the six sections. Regenerate with
  `make_catalog.py` from the site's article data.
- `state.json` — rotation state, committed back by the workflow after
  each run. An article is marked posted only after Bluesky accepts
  the post. Nothing ever posts twice.
- `.github/workflows/post.yml` — ten scheduled runs a day.

## Credentials

Live ONLY in this repo's GitHub secrets: `BSKY_HANDLE`,
`BSKY_APP_PASSWORD`.

## Post shape

Article title, a one-line hook from the article summary, the article
link, and section tags — e.g. `#BlackCities #BlackAmericaData`.
Composed to fit Bluesky's 300 characters.
