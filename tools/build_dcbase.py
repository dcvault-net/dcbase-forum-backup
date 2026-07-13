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

# Cloudflare Pages advanced-mode worker: original phpBB URLs -> static files
WORKER_BODY = '''
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const q = url.searchParams;
    let target = null;
    if (path === "/viewtopic.php") {
      let t = q.get("t");
      const p = q.get("p"), start = q.get("start");
      if (!t && p) t = PMAP[p];
      if (t) target = "/t" + t + (start && start !== "0" ? "_s" + start : "");
    } else if (path === "/viewforum.php") {
      const f = q.get("f"), start = q.get("start");
      if (f) target = "/f" + f + (start && start !== "0" ? "_s" + start : "");
    } else if (path === "/memberlist.php") {
      const u = q.get("u");
      if (q.get("mode") === "viewprofile" && u) target = "/u" + u;
    } else if (path === "/index.php" || path === "/app.php") {
      target = "/";
    }
    // serve the archived content AT the original URL (no redirect)
    if (target) return env.ASSETS.fetch(new Request(url.origin + target, request));
    return env.ASSETS.fetch(request);
  }
};
'''
with open(os.path.join(SITE, "_worker.js"), "w", encoding="utf-8") as fh:
    fh.write("const PMAP = " + json.dumps(pmap, separators=(",", ":")) + ";\n" + WORKER_BODY)

print("=== dcbase build stats ===")
for k in sorted(stats): print(f"  {stats[k]:6}  {k}")
print(f"attachments: {len(attach)}")
print(f"\nSite written to {SITE}")
