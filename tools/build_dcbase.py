#!/usr/bin/env python3
"""Reconstruct the dcbase phpBB forum as a static site, original prosilver look."""
import os, re, json, shutil, ast, urllib.parse, collections
from bs4 import BeautifulSoup

RAW  = r"D:\Projekte\dcbase-forum-backup\raw"
SITE = r"D:\Projekte\dcbase-forum-backup\site"
SCR  = os.path.dirname(os.path.abspath(__file__))
filemap = json.load(open(os.path.join(RAW, "filemap.json"), encoding="utf-8"))
pmap = json.load(open(os.path.join(RAW, "manifest.json"), encoding="utf-8"))["pmap"]

# archived id sets
topics, forums, profiles, topic_pages = set(), set(), set(), set()
for k in filemap:
    typ, rest = k.split(":", 1)
    key = ast.literal_eval(rest) if rest.startswith(("[", "(")) else rest
    if typ == "topic": topics.add(key[0]); topic_pages.add((key[0], key[1]))
    elif typ == "forum": forums.add(key[0])
    elif typ == "profile": profiles.add(key)

# attachments: detect type, copy with extension, build id->filename map
attach = {}
MAGIC = [(b"\x89PNG", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF8", "gif"),
         (b"%PDF", "pdf"), (b"PK\x03\x04", "zip")]
os.makedirs(SITE, exist_ok=True)

def topic_file(t, start="0"):
    return f"t{t}.html" if start in ("0", 0) else f"t{t}_s{start}.html"
def forum_file(f, start="0"):
    return f"f{f}.html" if start in ("0", 0) else f"f{f}_s{start}.html"

INERT_PHP = ("posting.php", "ucp.php", "search.php", "mcp.php", "report.php",
             "cron.php", "feed.php", "memberlist.php", "faq.php", "style.php")
stats = collections.Counter()

# every historical base URL the forum lived at -> normalized to a bare phpBB path
_FB = ["forum.dcbase.org", "www.forum.dcbase.org",
       "www.dcbase.org/forums", "dcbase.org/forums",
       "www.dcbase.org/forum", "dcbase.org/forum",
       "www.dcbase.org/legacy_dcpp_forums", "dcbase.org/legacy_dcpp_forums"]
FORUM_BASES = tuple(f"{s}{b}/" for b in _FB for s in ("https://", "http://", "//"))

def canon(path, q, frag=""):
    """Canonical original-style phpBB URL (root-relative, sid-free)."""
    parts = [f"{k}={q[k][0]}" for k in ("f", "t", "p", "mode", "u", "start") if k in q]
    return "/" + path + ("?" + "&".join(parts) if parts else "") + frag

def resolve(href):
    """-> ('ok',url) | ('red',url) | ('inert',) | ('keep',url)
    Archived phpBB links keep their ORIGINAL URL form; the worker serves the
    static content there so the address bar stays authentic."""
    if not href or href.startswith(("#", "mailto:", "javascript:")):
        return ("keep", href)
    h = href.replace("&amp;", "&").strip()
    for pre in FORUM_BASES:
        if h.startswith(pre): h = h[len(pre):]; break
    if h.startswith(("http://", "https://", "//")):
        return ("keep", href)              # other external (incl. dcbase.org wiki/homepage)
    h = h[2:] if h.startswith("./") else h
    h = h.lstrip("/")
    path = h.split("?")[0].split("#")[0]
    frag = ("#" + h.split("#", 1)[1]) if "#" in h else ""
    q = urllib.parse.parse_qs(h.split("?", 1)[1].split("#")[0]) if "?" in h else {}
    q.pop("sid", None); q.pop("view", None)
    if path in ("", "index.php", "app.php"):
        return ("ok", "/")
    if path == "viewtopic.php":
        t = q.get("t", [None])[0]; p = q.get("p", [None])[0]; start = q.get("start", ["0"])[0]
        if t:
            arch = (t in topics) if start == "0" else ((t, start) in topic_pages)
            return ("ok" if arch else "red", canon(path, q, frag))
        if p:
            pt = pmap.get(p)
            if not frag: frag = f"#p{p}"
            return ("ok" if (pt and pt in topics) else "red", canon(path, q, frag))
        return ("inert",)
    if path == "viewforum.php":
        f = q.get("f", [None])[0]
        if f:
            return ("ok" if f in forums else "red", canon(path, q))
        return ("inert",)
    if path == "memberlist.php" and q.get("mode", [""])[0] == "viewprofile":
        u = q.get("u", [None])[0]
        if u:
            return ("ok" if u in profiles else "red", canon(path, q))
        return ("inert",)
    if path == "download/file.php":
        a = q.get("id", [None])[0]
        if a and a in attach:
            return ("ok", "/" + attach[a])
        return ("red", None)
    if any(path.endswith(x) for x in INERT_PHP):
        return ("inert",)
    if path.startswith(("styles/", "assets/", "images/", "download/")):
        return ("keep", h)                 # asset path, keep relative
    return ("inert",)

FOOTER_NOTE = (
    'This is a static archive of the DCBase forum (forum.dcbase.org), reconstructed '
    'from all available <a href="https://web.archive.org/">Internet Archive</a> snapshots '
    '(newest genuine capture per thread). Links to threads, forums or users that were never '
    'archived are shown in <span class="na">red</span> and cannot be opened. Login, search, '
    'posting and other interactive functions are disabled.'
)

NOTFOUND_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not in this archive - DCBase</title>
<link rel="stylesheet" href="/styles/prosilver/theme/stylesheet.css">
<link rel="stylesheet" href="/overrides.css">
<style>
  .na-box { max-width: 640px; margin: 60px auto; padding: 24px 28px; border: 1px solid #c8c8c8;
            border-left: 4px solid #cc2200; background: #f7f7f7; border-radius: 3px; }
  .na-box h1 { font-size: 20px; margin: 0 0 10px; color: #cc2200; }
  .na-box p { margin: 8px 0; line-height: 1.6; }
</style>
</head>
<body>
<div class="na-box">
  <h1>Not in this archive</h1>
  <p>This thread, forum, post or page was never captured by the Internet Archive, so it is
     not part of this static backup of the DCBase forum.</p>
  <p><a href="/">&larr; Back to the forum index</a></p>
</div>
</body>
</html>
'''

def process(src, out_name):
    soup = BeautifulSoup(open(src, encoding="utf-8", errors="replace").read(), "html.parser")
    for s in soup.find_all("script"):
        s.decompose()
    for n in soup.find_all("noscript"):
        n.unwrap()
    # asset refs in head: strip query, strip leading ./
    for tag, attr in (("link", "href"), ("img", "src")):
        for el in soup.find_all(tag):
            v = el.get(attr)
            if v and (v.startswith(("./styles/", "./assets/", "./images/", "styles/", "assets/", "images/"))):
                el[attr] = v.lstrip("./").split("?")[0]
    # links
    for a in soup.find_all("a", href=True):
        kind = resolve(a["href"])
        if kind[0] == "ok":
            a["href"] = kind[1]
            for junk in ("data-sid",): a.attrs.pop(junk, None)
            stats["link_ok"] += 1
        elif kind[0] == "red":
            a["href"] = "#"; a["class"] = (a.get("class") or []) + ["unavail"]
            a["title"] = "Not archived"; stats["link_red"] += 1
        elif kind[0] == "inert":
            a["href"] = "#"; a["class"] = (a.get("class") or []) + ["inert"]
            a["title"] = "Disabled in this archive"; stats["link_inert"] += 1
        else:
            a["href"] = kind[1] if len(kind) > 1 and kind[1] else "#"
    # inline post images / other imgs pointing at download or forum
    for img in soup.find_all("img", src=True):
        k = resolve(img["src"])
        if k[0] == "ok": img["src"] = k[1]; stats["img_ok"] += 1
        elif k[0] == "red":
            span = soup.new_tag("span"); span["class"] = "na"; span["title"] = "Image not archived"
            span.string = "[image]"; img.replace_with(span); stats["img_red"] += 1
        elif k[0] == "inert":
            img.decompose(); stats["img_beacon_removed"] += 1   # cron.php / tracking beacons
    # neutralise forms
    for form in soup.find_all("form"):
        form["action"] = "#"; form["onsubmit"] = "return false"
    # footer note
    footer = soup.find(id="page-footer") or soup.find("div", class_="page-footer") or soup.body
    if footer:
        note = soup.new_tag("div"); note["class"] = "archive-note"
        note.append(BeautifulSoup(FOOTER_NOTE, "html.parser"))
        (footer.append(note) if footer is soup.body else footer.insert(0, note))
    # local overrides + <base> safety
    if soup.head:
        link = soup.new_tag("link", rel="stylesheet", href="overrides.css"); soup.head.append(link)
    open(os.path.join(SITE, out_name), "w", encoding="utf-8").write(str(soup))
    stats["pages"] += 1

# ---- build ----
if os.path.isdir(SITE): shutil.rmtree(SITE)
os.makedirs(SITE)
# assets -> original paths
shutil.copytree(os.path.join(RAW, "assets", "styles"), os.path.join(SITE, "styles"))
shutil.copytree(os.path.join(RAW, "assets", "assets"), os.path.join(SITE, "assets"))
if os.path.isdir(os.path.join(RAW, "assets", "images")):
    shutil.copytree(os.path.join(RAW, "assets", "images"), os.path.join(SITE, "images"))
# attachments with detected extension
adir = os.path.join(RAW, "attachments")
if os.path.isdir(adir):
    for fn in os.listdir(adir):
        data = open(os.path.join(adir, fn), "rb").read()
        ext = next((e for magic, e in MAGIC if data.startswith(magic)), "bin")
        aid = fn[1:] if fn.startswith("a") else fn
        out = f"a{aid}.{ext}"; attach[aid] = out
        open(os.path.join(SITE, out), "wb").write(data)
shutil.copy(os.path.join(SCR, "overrides_dcbase.css"), os.path.join(SITE, "overrides.css"))

# pages
def flat(rel):
    base = os.path.basename(rel)
    return base
for root, _, files in os.walk(RAW):
    if os.path.basename(root) in ("assets", "attachments") or "assets" in root or "print" in root:
        continue
    for fn in files:
        if not fn.endswith(".html"): continue
        process(os.path.join(root, fn), fn)

# set of valid page slugs (for the worker to 404 on missing content)
valid = set()
for k in filemap:
    typ, rest = k.split(":", 1)
    if typ not in ("topic", "forum", "profile"): continue
    key = ast.literal_eval(rest) if rest.startswith(("[", "(")) else rest
    if typ == "topic":   valid.add(f"t{key[0]}" if key[1] == "0" else f"t{key[0]}_s{key[1]}")
    elif typ == "forum": valid.add(f"f{key[0]}" if key[1] == "0" else f"f{key[0]}_s{key[1]}")
    elif typ == "profile": valid.add(f"u{key}")

# Cloudflare Pages advanced-mode worker: serve original phpBB URLs, real 404 for missing
WORKER_BODY = r'''
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname, q = url.searchParams;
    let slug = null, isContent = false;
    if (path === "/viewtopic.php") {
      isContent = true;
      let t = q.get("t"); const p = q.get("p"), start = q.get("start");
      if (!t && p) t = PMAP[p];
      if (t) slug = "t" + t + (start && start !== "0" ? "_s" + start : "");
    } else if (path === "/viewforum.php") {
      isContent = true;
      const f = q.get("f"), start = q.get("start");
      if (f) slug = "f" + f + (start && start !== "0" ? "_s" + start : "");
    } else if (path === "/memberlist.php") {
      const u = q.get("u");
      if (q.get("mode") === "viewprofile" && u) { isContent = true; slug = "u" + u; }
    } else if (path === "/index.php" || path === "/app.php") {
      return env.ASSETS.fetch(new Request(url.origin + "/", request));
    } else if (/^\/[tfu]\d[\w]*$/.test(path)) {
      isContent = true; slug = path.slice(1);
    }
    if (isContent) {
      if (slug && VALID.has(slug))
        return env.ASSETS.fetch(new Request(url.origin + "/" + slug, request));
      const nf = await env.ASSETS.fetch(new Request(url.origin + "/404.html", request));
      return new Response(nf.body, { status: 404, headers: nf.headers });
    }
    return env.ASSETS.fetch(request);
  }
};
'''
with open(os.path.join(SITE, "_worker.js"), "w", encoding="utf-8") as fh:
    fh.write("const PMAP = " + json.dumps(pmap, separators=(",", ":")) + ";\n"
             + "const VALID = new Set(" + json.dumps(sorted(valid), separators=(",", ":")) + ");\n"
             + WORKER_BODY)

open(os.path.join(SITE, "404.html"), "w", encoding="utf-8").write(NOTFOUND_HTML)

print("=== dcbase build stats ===")
for k in sorted(stats): print(f"  {stats[k]:6}  {k}")
print(f"attachments: {len(attach)}")
print(f"\nSite written to {SITE}")
