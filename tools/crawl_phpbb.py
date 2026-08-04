#!/usr/bin/env python3
"""Crawl a live phpBB (rendered from an imported DB in Docker) to raw HTML.

Worklist (which forums/topics/users exist and how they paginate) comes straight
from the database, so nothing is missed. Pages are fetched with a bot user-agent
so phpBB leaves session ids out of the markup. Saved files are named by the static
slug the converter will emit: f<id>[_s<start>], t<id>[_s<start>], u<id>, plus index.

Usage: python crawl_phpbb.py <forums|archive>
"""
import os, sys, time, subprocess, urllib.request, urllib.error

TARGET = sys.argv[1] if len(sys.argv) > 1 else "forums"
CFG = {
    "forums":  dict(db="dcbase_forums",  pfx="phpbb_",  ppp=10, tpp=25),
    "archive": dict(db="dcbase_archive",  pfx="phpbb3_", ppp=10, tpp=25),
}[TARGET]
DB, PFX, PPP, TPP = CFG["db"], CFG["pfx"], CFG["ppp"], CFG["tpp"]

BASE = "http://localhost:8080"
OUT  = rf"D:\Projekte\dcbase-forum-backup\recovery\raw_{TARGET}"
# bot UA -> phpBB omits session ids from links (clean HTML); used for forum/topic/index.
# bots are hard-blocked from memberlist.php, so profiles are fetched with a browser UA
# (session ids there are stripped by the converter).
UA_BOT   = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
UA_GUEST = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
os.makedirs(OUT, exist_ok=True)

def sql(q):
    r = subprocess.run(["docker", "exec", "dcbdb", "mysql", "-uroot", "-proot", DB,
                        "-N", "-B", "-e", q], capture_output=True, text=True)
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]

# ---- worklist from the DB ----
# type 1 = posting forum, type 0 = category (viewforum still lists its subforums)
forums = sql(f"SELECT forum_id, forum_topics_approved FROM {PFX}forums WHERE forum_type IN (0,1)")
topics = sql(f"SELECT topic_id, topic_posts_approved FROM {PFX}topics")
users  = sql(f"SELECT DISTINCT poster_id FROM {PFX}posts WHERE poster_id>1")

jobs = [("index", "/", UA_BOT)]
for fid, ntop in forums:
    pages = max(1, -(-int(ntop or 1) // TPP))
    for pg in range(pages):
        s = pg * TPP
        slug = f"f{fid}" if s == 0 else f"f{fid}_s{s}"
        jobs.append((slug, f"/viewforum.php?f={fid}" + (f"&start={s}" if s else ""), UA_BOT))
for tid, npost in topics:
    pages = max(1, -(-int(npost or 1) // PPP))
    for pg in range(pages):
        s = pg * PPP
        slug = f"t{tid}" if s == 0 else f"t{tid}_s{s}"
        jobs.append((slug, f"/viewtopic.php?t={tid}" + (f"&start={s}" if s else ""), UA_BOT))
for (uid,) in [(u[0],) for u in users]:
    jobs.append((f"u{uid}", f"/memberlist.php?mode=viewprofile&u={uid}", UA_GUEST))

print(f"[{TARGET}] forums={len(forums)} topics={len(topics)} users={len(users)} -> {len(jobs)} pages")

# ---- fetch ----
ok = fail = 0
for i, (slug, path, ua) in enumerate(jobs, 1):
    dst = os.path.join(OUT, slug + ".html")
    try:
        req = urllib.request.Request(BASE + path, headers={"User-Agent": ua})
        data = urllib.request.urlopen(req, timeout=60).read()
        open(dst, "wb").write(data)
        ok += 1
    except Exception as e:
        fail += 1
        print(f"  FAIL {slug} {path}: {e}")
    if i % 200 == 0:
        print(f"  {i}/{len(jobs)}  ok={ok} fail={fail}")
print(f"[{TARGET}] done: ok={ok} fail={fail}  -> {OUT}")
