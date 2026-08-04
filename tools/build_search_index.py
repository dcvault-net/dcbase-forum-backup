#!/usr/bin/env python3
"""Extract every visible post from both forum DBs, clean the phpBB bbcode/markup to
plain text, and emit a D1/SQLite FTS5 seed file (recovery/search_seed.sql).

Each row carries enough to link a hit to the exact rendered page + post anchor:
  ns ('' newer / 'd' archive), forum_id, topic_id, post_id, start (page offset), title, poster, post_time, body.
"""
import os, re, html, subprocess

REC = r"D:\Projekte\dcbase-forum-backup\recovery"
OUT = os.path.join(REC, "search_seed.sql")
PPP = 10  # posts per page (matches the crawl / phpBB config)

FORUMS = [("",  "dcbase_forums",  "phpbb_"),
          ("d", "dcbase_archive", "phpbb3_")]

def mysql(db, q):
    r = subprocess.run(["docker", "exec", "dcbdb", "mysql", "-uroot", "-proot", db, "-N", "-B", "-e", q],
                       capture_output=True, text=True)
    # mysql --batch escapes \t \n \\ in field values; unescape after splitting on real tabs
    def unesc(s): return s.replace("\\t", "\t").replace("\\n", "\n").replace("\\\\", "\\")
    rows = []
    for line in r.stdout.split("\n"):
        if line == "" and rows:  # trailing
            continue
        if "\t" not in line and not line:
            continue
        parts = line.split("\t")
        rows.append([unesc(p) for p in parts])
    return [row for row in rows if len(row) > 1]

def clean(t):
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)   # phpBB smiley / magic-url markers
    t = re.sub(r"\[[^\]]*\]", " ", t)               # bbcode tags incl. :uid and =params
    t = re.sub(r"<[^>]+>", " ", t)                  # any stray html
    t = html.unescape(t)                            # &#58; &quot; &amp; ...
    t = t.replace("\x00", " ")
    return re.sub(r"\s+", " ", t).strip()

def sqlstr(s):
    return "'" + s.replace("'", "''") + "'"

rows_out = []
for ns, db, pfx in FORUMS:
    q = (f"SELECT p.post_id, p.topic_id, t.forum_id, t.topic_title, "
         f"COALESCE(NULLIF(p.post_username,''), u.username, CONCAT('user', p.poster_id)) AS poster, "
         f"p.post_time, p.post_text "
         f"FROM {pfx}posts p "
         f"JOIN {pfx}topics t ON t.topic_id = p.topic_id "
         f"LEFT JOIN {pfx}users u ON u.user_id = p.poster_id "
         f"WHERE p.post_visibility = 1 AND t.topic_visibility = 1 AND t.topic_moved_id = 0 "
         f"ORDER BY p.topic_id, p.post_time, p.post_id")
    rows = mysql(db, q)
    # assign per-topic post position -> page start offset
    pos = {}
    n = 0
    for r in rows:
        post_id, topic_id, forum_id, title, poster, post_time, post_text = (r + [""] * 7)[:7]
        idx = pos.get(topic_id, 0); pos[topic_id] = idx + 1
        start = (idx // PPP) * PPP
        body = clean(post_text)[:4000]   # cap long code dumps; plenty for full-text recall
        if not body and not title:
            continue
        rows_out.append((ns, forum_id, topic_id, post_id, start, title, poster, post_time, body))
        n += 1
    print(f"ns {ns!r}: {n} posts extracted from {db}")

# sample cleaning quality
print("\n--- sample cleaned bodies ---")
for r in rows_out[:2] + rows_out[-2:]:
    print(f"  [{r[0]}t{r[2]} p{r[3]} start={r[4]}] {r[6]}: {r[8][:120]}")

# write FTS5 seed
with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("DROP TABLE IF EXISTS search;\n")
    fh.write("CREATE VIRTUAL TABLE search USING fts5("
             "title, body, ns UNINDEXED, forum_id UNINDEXED, topic_id UNINDEXED, "
             "post_id UNINDEXED, start UNINDEXED, poster UNINDEXED, post_time UNINDEXED, "
             "tokenize='porter unicode61');\n")
    BATCH = 50
    cols = "(title, body, ns, forum_id, topic_id, post_id, start, poster, post_time)"
    for i in range(0, len(rows_out), BATCH):
        chunk = rows_out[i:i + BATCH]
        vals = []
        for ns, forum_id, topic_id, post_id, start, title, poster, post_time, body in chunk:
            vals.append("(" + ",".join([
                sqlstr(title), sqlstr(body), sqlstr(ns), str(int(forum_id or 0)),
                str(int(topic_id)), str(int(post_id)), str(int(start)),
                sqlstr(poster), str(int(post_time or 0))]) + ")")
        fh.write(f"INSERT INTO search {cols} VALUES\n" + ",\n".join(vals) + ";\n")

print(f"\ntotal posts: {len(rows_out)}")
print(f"seed written: {OUT} ({os.path.getsize(OUT)//1024} KB)")
