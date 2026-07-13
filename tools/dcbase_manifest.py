#!/usr/bin/env python3
"""Build the download manifest for the dcbase phpBB forum, sid-normalized."""
import json, urllib.parse, collections, os

SCR = os.path.dirname(os.path.abspath(__file__))
RAW = r"D:\Projekte\dcbase-forum-backup\raw"
os.makedirs(RAW, exist_ok=True)
d = json.load(open(os.path.join(SCR, "dcbase_all.json")))[1:]

def q_of(u):
    pr = urllib.parse.urlparse(u.replace('&amp;', '&'))
    q = urllib.parse.parse_qs(pr.query); q.pop('sid', None)
    return pr.path, q

# candidates keyed by (type, id) -> list of (ts, original_url, length)
cand = collections.defaultdict(list)
pmap_votes = collections.Counter()   # (post_id, topic_id) co-occurrence
for orig, ts, sc, ln, dg in d:
    if sc != '200':
        continue
    path, q = q_of(orig)
    L = int(ln) if (ln or '').isdigit() else 0
    if 'viewtopic.php' in path:
        isprint = q.get('view', [''])[0] == 'print'
        t = q.get('t', [None])[0]; p = q.get('p', [None])[0]; start = q.get('start', ['0'])[0]
        if p and t:
            pmap_votes[(p, t)] += 1
        if t:
            key = ('topic_print', (t, start)) if isprint else ('topic', (t, start))
            cand[key].append((ts, orig, L))
        elif p:
            cand[('post', p)].append((ts, orig, L))
    elif 'viewforum.php' in path:
        f = q.get('f', [None])[0]; start = q.get('start', ['0'])[0]
        if f:
            cand[('forum', (f, start))].append((ts, orig, L))
    elif path in ('/', '/index.php', '/app.php', '/app.php/'):
        cand[('index', 'home')].append((ts, orig, L))
    elif 'memberlist.php' in path and q.get('mode', [''])[0] == 'viewprofile' and 'u' in q:
        cand[('profile', q['u'][0])].append((ts, orig, L))
    elif 'download/file.php' in path:
        aid = q.get('id', [None])[0]
        if aid:
            cand[('attachment', aid)].append((ts, orig, L))
    elif '/styles/' in path or '/assets/' in path or '/images/' in path:
        cand[('asset', urllib.parse.unquote(path))].append((ts, orig, L))

for k in cand:
    cand[k].sort(reverse=True)  # newest first

# resolve post -> topic (majority vote)
pmap = {}
best = {}
for (p, t), n in pmap_votes.items():
    if p not in best or n > best[p]:
        best[p] = n; pmap[p] = t

def out_name(typ, key):
    if typ == 'topic':
        t, s = key; return f"topics/t{t}.html" if s == '0' else f"topics/t{t}_s{s}.html"
    if typ == 'topic_print':
        t, s = key; return f"topics/print/t{t}_p{s}.html"
    if typ == 'forum':
        f, s = key; return f"forums/f{f}.html" if s == '0' else f"forums/f{f}_s{s}.html"
    if typ == 'index': return "index.html"
    if typ == 'profile': return f"profiles/u{key}.html"
    if typ == 'attachment': return f"attachments/a{key}"
    if typ == 'post': return None  # permalinks resolved via pmap, not downloaded
    if typ == 'asset': return "assets" + key  # keep path
    return None

manifest = {"items": [], "pmap": pmap}
counts = collections.Counter()
for (typ, key), caps in cand.items():
    if typ == 'post':
        continue
    on = out_name(typ, key)
    if on is None:
        continue
    manifest["items"].append({
        "type": typ, "key": key, "file": on,
        "html": typ in ('topic', 'topic_print', 'forum', 'index', 'profile'),
        "candidates": [[ts, url] for ts, url, L in caps[:8]],   # up to 8 fallbacks
    })
    counts[typ] += 1

json.dump(manifest, open(os.path.join(RAW, "manifest.json"), "w", encoding="utf-8"), indent=1)
print("manifest items by type:")
for t, n in counts.most_common():
    print(f"  {n:5}  {t}")
print(f"\npost->topic map entries: {len(pmap)}")
print(f"total items to fetch: {len(manifest['items'])}")
