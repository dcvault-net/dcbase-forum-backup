#!/usr/bin/env python3
"""Download the dcbase phpBB forum from Wayback: newest real capture per item,
with error-page detection + fallback, resumable, polite retry."""
import json, os, time, urllib.request, urllib.error, collections

RAW = r"D:\Projekte\dcbase-forum-backup\raw"
manifest = json.load(open(os.path.join(RAW, "manifest.json"), encoding="utf-8"))
items = manifest["items"]

# index print-view candidates by (t,start) for topic fallback
print_by_key = {}
for it in items:
    if it["type"] == "topic_print":
        print_by_key[tuple(it["key"])] = it["candidates"]

def fetch(ts, url):
    for u in (url, url.replace('&amp;', '&')):
        req = urllib.request.Request(f"http://web.archive.org/web/{ts}id_/{u}",
                                     headers={"User-Agent": "Mozilla/5.0 (archival research)"})
        try:
            return urllib.request.urlopen(req, timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                continue
            raise
    raise urllib.error.HTTPError(url, 404, "not found", None, None)

def fetch_retry(ts, url, tries=4):
    for a in range(tries):
        try:
            return fetch(ts, url)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            time.sleep(2.5 * (a + 1))
        except Exception:
            time.sleep(2.5 * (a + 1))
    return None

def is_real(data):
    low = data[:20000].decode('utf-8', 'replace').lower()
    if 'general error</title>' in low or '<title>general error' in low: return False
    if 'attention required' in low or 'checking your browser' in low or 'cf-browser-verification' in low: return False
    if 'cf-error-details' in low: return False
    if any(m in low for m in ('class="postbody"', 'class="post ', 'id="p', 'class="content"',
                              'class="forumbg"', 'class="topiclist"', 'class="forabg"')):
        return True
    return False

filemap = {}
failures = []
stats = collections.Counter()
prog = os.path.join(RAW, "_progress.json")
if os.path.exists(prog):
    saved = json.load(open(prog, encoding="utf-8"))
    filemap = saved.get("filemap", {}); failures = saved.get("failures", [])

def save():
    json.dump({"filemap": filemap, "failures": failures},
              open(prog, "w", encoding="utf-8"), indent=1)

def dest(rel):
    p = os.path.join(RAW, *rel.split("/")); os.makedirs(os.path.dirname(p), exist_ok=True); return p

order = {"index": 0, "forum": 1, "topic": 2, "profile": 3, "asset": 4, "attachment": 5, "topic_print": 9}
items.sort(key=lambda it: (order.get(it["type"], 8), it["file"]))

t0 = time.time(); n = 0; total = sum(1 for it in items if it["type"] != "topic_print")
for it in items:
    if it["type"] == "topic_print":
        continue
    n += 1
    key = f'{it["type"]}:{it["key"]}'
    fp = dest(it["file"])
    if key in filemap and os.path.exists(fp):
        stats["skip"] += 1; continue
    got = False
    cands = list(it["candidates"])
    if it["type"] == "topic":
        cands += print_by_key.get(tuple(it["key"]), [])   # print fallback
    for ts, url in cands:
        data = fetch_retry(ts, url)
        if data is None:
            continue
        if it["html"] and not is_real(data):
            stats["err_page"] += 1; continue
        open(fp, "wb").write(data)
        filemap[key] = {"file": it["file"], "ts": ts, "bytes": len(data)}
        stats["ok"] += 1; got = True; break
        time.sleep(0.15)
    if not got:
        failures.append({"type": it["type"], "key": it["key"], "file": it["file"]})
        stats["fail"] += 1
    if n % 25 == 0:
        save()
        el = time.time() - t0
        print(f"[{n}/{total}] ok={stats['ok']} skip={stats['skip']} fail={stats['fail']} "
              f"errpg={stats['err_page']} | {el:.0f}s", flush=True)
    time.sleep(0.4)

save()
json.dump(filemap, open(os.path.join(RAW, "filemap.json"), "w", encoding="utf-8"), indent=1)
json.dump(failures, open(os.path.join(RAW, "failures.json"), "w", encoding="utf-8"), indent=1)
print(f"\nDONE ok={stats['ok']} skip={stats['skip']} fail={stats['fail']} errpg={stats['err_page']} "
      f"in {time.time()-t0:.0f}s")
print(f"failures (will be red-marked): {len(failures)}")
