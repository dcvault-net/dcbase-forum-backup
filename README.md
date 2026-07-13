# DCBase forum backup

A static, read-only preservation copy of the **DCBase forum** (`forum.dcbase.org`), the
phpBB community forum of the Direct Connect (DC) network. The forum ran on phpBB with the
prosilver style; this repository reconstructs it from Internet Archive snapshots and serves
it as a self-contained static site with the original look.

Live copy: <https://dcbforum.dcvault.net> (Cloudflare Pages)

## What this is

The forum was captured by the Wayback Machine between 2012 and 2025. Because phpBB renders
server-side, the archived HTML contains the real posts. Each thread here uses its newest
genuine capture; Cloudflare error and phpBB "General Error" pages are filtered out and the
next good capture is used instead.

The reconstruction keeps the original prosilver appearance: the theme CSS and images were
recovered from the archive and are served locally. Session ids (`sid`) are stripped, internal
links are rewritten to the static files, and interactive functions (login, search, posting)
are disabled.

## Honest gaps

- Threads, forums or users that were never archived are shown in red with a "Not archived"
  tooltip.
- Only the newest good capture of each thread is kept, so a handful of very late posts on
  actively growing threads may be missing.
- Interactive features (login, search, posting, private messages) are not functional.

## Layout

- `site/` — the deployable static forum (Cloudflare Pages output directory, no build step).
- `raw/` — pristine originals pulled from the Wayback Machine (the actual backup) plus the
  build manifests (`*.json`).
- `tools/` — the Python scripts used to enumerate, download (sid-normalized, error-aware) and
  reconstruct the forum. They use absolute paths from the original build machine; adjust the
  `RAW`/`SITE` constants to re-run.

## Content stats

568 threads, 54 forums, 108 member profiles, 15 attachments, and the full prosilver theme.
Original phpBB URLs (`viewtopic.php?f=10&t=227`, etc.) are redirected to the static files.

## License and attribution

The forum content belongs to its original authors and the DCBase community. This repository
is an independent community preservation copy and is not affiliated with the original
operators of `forum.dcbase.org`.
