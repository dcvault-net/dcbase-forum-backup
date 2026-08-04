# DCBase forum backup

A static, read-only preservation copy of the **DCBase forums**, the phpBB community boards of
the Direct Connect (DC) network. This repository rebuilds them from a complete phpBB database
backup and serves them as a self-contained static site with the original prosilver look.

Live copy: <https://dcbforum.dcvault.net> (Cloudflare Pages)

## What this is

Two boards are preserved, each under its own URL namespace so their ids never collide:

- the old **DC++ developer forum** (`archive.dcbase.org`, 2003 to 2007) under `/dcpp_forums/`,
  with Feature Discussion, Protocol Alley, Programmer's Help and more,
- the later **forum.dcbase.org** (2007 to 2019) at the root.

Together that is about 5,500 topics and 32,000 posts. An earlier version of this archive was
reconstructed from Internet Archive snapshots (568 threads); this rebuild replaces it with the
full content from the database dump.

## How it is built

The static HTML is produced by rendering the real phpBB software, not by parsing the SQL by
hand, so bbcode, quotes, smilies and the prosilver theme come out exactly as phpBB draws them:

1. The three database dumps are imported into a throwaway MySQL in Docker.
2. A throwaway phpBB 3.2.5 (matching the dump's version) is pointed at each database.
3. `tools/crawl_phpbb.py` crawls every forum, topic (with pagination) and posting user's
   profile straight from the database work-list, so nothing is missed.
4. `tools/build_dcbase_db.py` turns the crawled HTML into the static site: it namespaces the
   two boards, keeps the original phpBB URLs, rewrites internal links, strips session ids,
   disables login/posting, marks the few unavailable links red, and generates the Cloudflare
   `_worker.js` that serves the original phpBB URLs and returns a real 404 for missing content.

Getting a guest crawl to see everything needed a few database fixes (documented in the code):
granting the guest/bot group read access to all forums, clearing the permission prefetch
cache, and recreating placeholder rows for ten posters whose user records were missing from
the backup (phpBB throws an SQL error when rendering a post by a user in no group).

## Search

Full-text search across every post is served from a Cloudflare **D1** database (SQLite FTS5).
`tools/build_search_index.py` extracts and cleans all 32,000+ posts into `search_seed.sql`; the
`/api/forum-search` route in `_worker.js` queries it and `search.html` is the UI. The D1
binding is declared in `wrangler.toml`.

## Honest gaps

- Uploaded attachment files were not part of the database dump (only their metadata), so
  attachment links are shown in red.
- 20 "moved topic" stubs and 2 broken topic rows with zero posts do not render; no post
  content is lost (moved topics live under their target thread).
- Login, posting and private messages are not functional (this is a static archive).

## Layout

- `site/` — the deployable static forum + search (Cloudflare Pages output directory).
- `tools/` — the crawl / build / search-index scripts (absolute paths from the build machine;
  adjust the constants to re-run) and `overrides_dcbase.css`.
- `wrangler.toml` — Pages config with the D1 search binding.
- The database dumps and the crawl working files (`recovery/`) are kept offline, not in git.

## License and attribution

The forum content belongs to its original authors and the DCBase community. This repository is
an independent community preservation copy and is not affiliated with the original operators of
the DCBase forums.
