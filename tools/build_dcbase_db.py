#!/usr/bin/env python3
"""Build the static DCBase forum from the phpBB-rendered crawl (recovery/raw_*).

Two forums, each its own URL namespace so ids never collide:
  - "forums"  (forum.dcbase.org)          -> served at the root, slugs t/f/u
  - "archive" (archive.dcbase.org/dcpp_forums) -> served under /dcpp_forums/, slugs dt/df/du

Internal phpBB links keep their ORIGINAL URL form; the Cloudflare worker serves the
static file behind that URL so the address bar stays authentic. Cross-forum links
(one board pointing at the other's old host) are normalised to the right namespace.
"""
import os, re, json, shutil, subprocess, urllib.parse, collections
from bs4 import BeautifulSoup

ROOT = r"D:\Projekte\dcbase-forum-backup"
REC  = os.path.join(ROOT, "recovery")
SITE = os.path.join(ROOT, "site")
SCR  = os.path.dirname(os.path.abspath(__file__))

# forum namespaces. key = slug prefix ('' or 'd'); urlbase = path prefix under the domain.
FORUMS = [
    dict(key="",  raw="raw_forums",  db="dcbase_forums",  pfx="phpbb_",  urlbase=""),
    dict(key="d", raw="raw_archive", db="dcbase_archive", pfx="phpbb3_", urlbase="dcpp_forums/"),
]
# host bases each namespace historically lived at (for cross-forum links)
HOST_BASES = {
    "":  ["forum.dcbase.org", "www.forum.dcbase.org", "www.dcbase.org/forums",
          "dcbase.org/forums", "www.dcbase.org/forum", "dcbase.org/forum"],
    "d": ["archive.dcbase.org/dcpp_forums", "archive.dcbase.org",
          "www.dcbase.org/legacy_dcpp_forums", "dcbase.org/legacy_dcpp_forums",
          "www.dcbase.org/dcpp_forums", "dcbase.org/dcpp_forums"],
}
INERT_PHP = ("posting.php", "ucp.php", "search.php", "mcp.php", "report.php", "cron.php",
             "feed.php", "faq.php", "style.php", "viewonline.php", "app.php")
stats = collections.Counter()

def sql(db, q):
    r = subprocess.run(["docker", "exec", "dcbdb", "mysql", "-uroot", "-proot", db,
                        "-N", "-B", "-e", q], capture_output=True, text=True)
    return [ln.split("\t") for ln in r.stdout.splitlines() if ln.strip()]

# ---- registry: which forum namespaces we actually have, their valid slugs + post maps ----
NS = {}   # key -> dict(urlbase, valid=set(slug), pmap={post_id: topic_id})
for f in FORUMS:
    rawdir = os.path.join(REC, f["raw"])
    if not os.path.isdir(rawdir) or not os.listdir(rawdir):
        continue
    # raw files are named without the namespace prefix (t123.html); the slug the
    # converter/worker use carries the prefix (dt123), so prefix them here too.
    valid = {f["key"] + fn[:-5] for fn in os.listdir(rawdir) if fn.endswith(".html")}
    pmap = {p: t for p, t in sql(f["db"], f"SELECT post_id, topic_id FROM {f['pfx']}posts")}
    NS[f["key"]] = dict(urlbase=f["urlbase"], raw=rawdir, valid=valid, pmap=pmap, key=f["key"])
    print(f"namespace {f['key']!r}: {len(valid)} pages, {len(pmap)} posts")

# base-URL -> namespace, longest first so 'archive.dcbase.org/dcpp_forums' beats 'archive.dcbase.org'
BASE_TO_NS = []
for key, bases in HOST_BASES.items():
    if key in NS:
        for b in bases:
            for scheme in ("https://", "http://", "//"):
                BASE_TO_NS.append((scheme + b.rstrip("/") + "/", key))
BASE_TO_NS.sort(key=lambda x: -len(x[0]))

def slug(key, kind, _id, start="0"):
    return f"{key}{kind}{_id}" + ("" if start in ("0", 0) else f"_s{start}")

def canon(urlbase, path, q, frag=""):
    parts = [f"{k}={q[k][0]}" for k in ("f", "t", "p", "mode", "u", "start") if k in q]
    return "/" + urlbase + path + ("?" + "&".join(parts) if parts else "") + frag

def resolve(href, cur):
    """cur = current page namespace key. Returns ('ok',url)|('red',)|('inert',)|('keep',url)."""
    if not href or href.startswith(("#", "mailto:", "javascript:")):
        return ("keep", href)
    h = href.replace("&amp;", "&").strip()
    ns_key = cur
    for pre, key in BASE_TO_NS:               # cross-forum absolute link?
        if h.startswith(pre):
            h = h[len(pre):]; ns_key = key; break
    else:
        # dead parent-site homepage -> local forum index
        if h.rstrip("/") in ("https://www.dcbase.org", "http://www.dcbase.org",
                              "https://dcbase.org", "http://dcbase.org"):
            return ("ok", "/")
        if h.startswith(("http://", "https://", "//")):
            return ("keep", href)             # genuine external (incl. dcbase.org wiki)
    ns = NS.get(ns_key)
    if ns is None:
        return ("keep", href)
    h = h[2:] if h.startswith("./") else h
    h = h.lstrip("/")
    path = h.split("?")[0].split("#")[0]
    frag = ("#" + h.split("#", 1)[1]) if "#" in h else ""
    q = urllib.parse.parse_qs(h.split("?", 1)[1].split("#")[0]) if "?" in h else {}
    q.pop("sid", None)
    ub = ns["urlbase"]; V = ns["valid"]; PM = ns["pmap"]
    if path in ("", "index.php", "app.php"):
        return ("ok", "/" + ub if ub else "/")
    if path == "viewtopic.php":
        t = q.get("t", [None])[0]; p = q.get("p", [None])[0]; start = q.get("start", ["0"])[0]
        if t:
            sl = slug(ns_key, "t", t, start)
            return ("ok", canon(ub, path, q, frag)) if sl in V else ("red",)
        if p:
            t = PM.get(p)
            if not frag: frag = f"#p{p}"
            sl = slug(ns_key, "t", t) if t else None
            return ("ok", canon(ub, path, q, frag)) if (sl and sl in V) else ("red",)
        return ("inert",)
    if path == "viewforum.php":
        fid = q.get("f", [None])[0]; start = q.get("start", ["0"])[0]
        if fid:
            sl = slug(ns_key, "f", fid, start)
            return ("ok", canon(ub, path, q)) if sl in V else ("red",)
        return ("inert",)
    if path == "memberlist.php" and q.get("mode", [""])[0] == "viewprofile":
        u = q.get("u", [None])[0]
        if u:
            sl = slug(ns_key, "u", u)
            return ("ok", canon(ub, path, q)) if sl in V else ("red",)
        return ("inert",)
    if path == "search.php":
        return ("ok", "/search.html")  # phpBB search -> our static D1-backed search page
    if path == "download/file.php":
        return ("red",)                # attachment binaries were not part of the DB backup
    if any(path.endswith(x) for x in INERT_PHP):
        return ("inert",)
    if path.startswith(("styles/", "assets/", "images/")):
        return ("keep", "/" + path.split("?")[0])   # shared asset at site root
    return ("inert",)

FOOTER_NOTE = (
    'This is a static archive of the DCBase forums, rebuilt from a complete phpBB database '
    'backup so every post is preserved. It covers the old DC++ developer forum '
    '(archive.dcbase.org, 2003 to 2007) under <code>/dcpp_forums/</code> and the later '
    'forum.dcbase.org (2007 to 2019). Login, search, posting and other interactive functions '
    'are disabled; the few links shown in <span class="na">red</span> point at content that '
    'is not in the backup (uploaded files were not part of it).'
)

def process(src, out_name, cur):
    soup = BeautifulSoup(open(src, encoding="utf-8", errors="replace").read(), "html.parser")
    for s in soup.find_all(["script", "noscript"]):
        s.decompose() if s.name == "script" else s.unwrap()
    # drop head links/meta that leak the crawl host (localhost) or point at disabled
    # feeds/search: canonical, feed alternates, opensearch, og:url
    for l in list(soup.find_all("link")):
        rel = " ".join(l.get("rel") or [])
        if any(x in rel for x in ("canonical", "alternate", "search")):
            l.decompose()
    for m in list(soup.find_all("meta", attrs={"property": "og:url"})):
        m.decompose()
    # asset refs: strip ./ and query
    for tag, attr in (("link", "href"), ("img", "src")):
        for el in soup.find_all(tag):
            v = el.get(attr) or ""
            if re.match(r'\.?/?(styles|assets|images)/', v):
                el[attr] = "/" + re.sub(r'^\.?/?', '', v).split("?")[0]
    # links
    for a in soup.find_all("a", href=True):
        k = resolve(a["href"], cur)
        if k[0] == "ok":
            a["href"] = k[1]; stats["link_ok"] += 1
        elif k[0] == "red":
            a["href"] = "#"; a["class"] = (a.get("class") or []) + ["unavail"]
            a["title"] = "Not in this archive"; stats["link_red"] += 1
        elif k[0] == "inert":
            a["href"] = "#"; a["class"] = (a.get("class") or []) + ["inert"]
            a["title"] = "Disabled in this archive"; stats["link_inert"] += 1
        else:
            a["href"] = k[1] if len(k) > 1 and k[1] else "#"
    # inline images (post images, avatars, smilies via /images already handled)
    for img in soup.find_all("img", src=True):
        k = resolve(img["src"], cur)
        if k[0] == "ok":
            img["src"] = k[1]; stats["img_ok"] += 1
        elif k[0] == "red":
            span = soup.new_tag("span"); span["class"] = "na"; span["title"] = "Image not in backup"
            span.string = "[image]"; img.replace_with(span); stats["img_red"] += 1
        elif k[0] == "inert":
            img.decompose()
    for form in soup.find_all("form"):
        form["action"] = "#"; form["onsubmit"] = "return false"
    # add a Search entry to the main nav (the bot-rendered pages omit phpBB's own search box)
    nav = soup.find("ul", class_="nav-main")
    if nav and not nav.find("a", href="/search.html"):
        li = soup.new_tag("li"); li["class"] = "nav-search"
        a = soup.new_tag("a", href="/search.html"); a["role"] = "menuitem"
        icon = soup.new_tag("i"); icon["class"] = "icon fa-search fa-fw"; icon["aria-hidden"] = "true"
        span = soup.new_tag("span"); span.string = "Search"
        a.append(icon); a.append(span); li.append(a); nav.append(li)
    footer = soup.find(id="page-footer") or soup.body
    if footer:
        note = soup.new_tag("div"); note["class"] = "archive-note"
        note.append(BeautifulSoup(FOOTER_NOTE, "html.parser"))
        (footer.append(note) if footer is soup.body else footer.insert(0, note))
    # cross-forum notice box on the two index pages
    if out_name in ("index.html", "dindex.html"):
        pb = soup.find(id="page-body")
        if pb:
            if cur == "":   # newer forum index -> point to the old DC++ forum
                box_html = ('<div class="xforum-box"><strong>Looking for the classic DC++ developer '
                            'forum?</strong> The old board (archive.dcbase.org, 2003 to 2007) with Feature '
                            'Discussion, Protocol Alley and Programmer’s Help is preserved here too. '
                            '<a href="/dcpp_forums/">Browse the archived DC++ forum →</a></div>')
            else:           # old forum index -> point back to the newer forum
                box_html = ('<div class="xforum-box"><strong>This is the archived DC++ developer forum '
                            '(2003 to 2007).</strong> The later forum.dcbase.org (2007 to 2019) lives at '
                            '<a href="/">the main forum index →</a>.</div>')
            pb.insert(0, BeautifulSoup(box_html, "html.parser"))
    if soup.head:
        soup.head.append(soup.new_tag("link", rel="stylesheet", href="/overrides.css"))
    open(os.path.join(SITE, out_name), "w", encoding="utf-8").write(str(soup))
    stats["pages"] += 1

# ---- build ----
if os.path.isdir(SITE): shutil.rmtree(SITE)
os.makedirs(SITE)
for d in ("styles", "assets", "images"):
    src = os.path.join(REC, "assets", d)
    if os.path.isdir(src): shutil.copytree(src, os.path.join(SITE, d))
shutil.copy(os.path.join(SCR, "overrides_dcbase.css"), os.path.join(SITE, "overrides.css"))

for key, ns in NS.items():
    for fn in os.listdir(ns["raw"]):
        if not fn.endswith(".html"): continue
        base = fn[:-5]
        out = key + base + ".html"   # ''->t123.html / index.html ; 'd'->dt123.html / dindex.html
        process(os.path.join(ns["raw"], fn), out, key)

# ---- worker: route original phpBB URLs (per namespace) to slugs, real 404 for misses ----
worker_ns = {k: dict(urlbase=v["urlbase"], pmap=v["pmap"],
                     valid=sorted(v["valid"])) for k, v in NS.items()}
WORKER_BODY = r'''
async function handleSearch(url, env, ctx) {
  const raw = (url.searchParams.get("q") || url.searchParams.get("keywords") || "").trim();
  if (!raw || !env.DB) return Response.json({ q: raw, results: [] });
  const terms = (raw.match(/[\p{L}\p{N}_]+/gu) || []).slice(0, 10);
  if (!terms.length) return Response.json({ q: raw, results: [] });
  // Edge-cache identical searches so a crawler hitting search URLs cannot spike
  // the D1 FTS table. Archived content is static, so results never change.
  const cache = caches.default;
  const cacheKey = new Request(url.origin + "/api/forum-search?q=" + encodeURIComponent(raw.toLowerCase()));
  const hit = await cache.match(cacheKey);
  if (hit) return hit;
  // quoted terms (implicit AND); prefix-match the final term for as-you-type feel
  const fts = terms.map((t, i) => '"' + t + '"' + (i === terms.length - 1 ? "*" : "")).join(" ");
  try {
    const stmt = env.DB.prepare(
      "SELECT ns, topic_id, post_id, start, poster, post_time, title, " +
      "snippet(search, 1, '@@H@@', '@@X@@', ' … ', 12) AS snip " +
      "FROM search WHERE search MATCH ? ORDER BY bm25(search) LIMIT 50");
    const { results } = await stmt.bind(fts).all();
    const resp = Response.json({ q: raw, count: results.length, results },
      { headers: { "Cache-Control": "public, max-age=86400" } });
    if (ctx && ctx.waitUntil) ctx.waitUntil(cache.put(cacheKey, resp.clone()));
    return resp;
  } catch (e) {
    return Response.json({ q: raw, results: [], error: String(e) });
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/api/forum-search") return handleSearch(url, env, ctx);
    let path = url.pathname, q = url.searchParams;
    // pick namespace by path prefix (longest urlbase first)
    let nsKey = "", rest = path;
    for (const k of Object.keys(NS).sort((a,b)=>NS[b].urlbase.length-NS[a].urlbase.length)) {
      const ub = "/" + NS[k].urlbase;
      if (NS[k].urlbase && path.startsWith(ub)) { nsKey = k; rest = path.slice(ub.length-1); break; }
    }
    const ns = NS[nsKey]; if (!ns) return env.ASSETS.fetch(request);
    let slug = null, isContent = false;
    if (rest === "/viewtopic.php") {
      isContent = true;
      let t = q.get("t"); const p = q.get("p"), start = q.get("start");
      if (!t && p) t = ns.pmap[p];
      if (t) slug = nsKey + "t" + t + (start && start !== "0" ? "_s" + start : "");
    } else if (rest === "/viewforum.php") {
      isContent = true;
      const f = q.get("f"), start = q.get("start");
      if (f) slug = nsKey + "f" + f + (start && start !== "0" ? "_s" + start : "");
    } else if (rest === "/memberlist.php") {
      const u = q.get("u");
      if (q.get("mode") === "viewprofile" && u) { isContent = true; slug = nsKey + "u" + u; }
    } else if (rest === "/index.php" || rest === "/app.php" || rest === "/" ) {
      const home = nsKey ? "/" + nsKey + "index" : "/";
      return env.ASSETS.fetch(new Request(url.origin + home, request));
    }
    if (isContent) {
      if (slug && ns.valid.has(slug))
        return env.ASSETS.fetch(new Request(url.origin + "/" + slug, request));
      const nf = await env.ASSETS.fetch(new Request(url.origin + "/404.html", request));
      return new Response(nf.body, { status: 404, headers: nf.headers });
    }
    return env.ASSETS.fetch(request);
  }
};
'''
js_ns = "const NS = {\n"
for k, v in worker_ns.items():
    js_ns += (f"  {json.dumps(k)}: {{ urlbase: {json.dumps(v['urlbase'])}, "
              f"pmap: {json.dumps(v['pmap'], separators=(',',':'))}, "
              f"valid: new Set({json.dumps(v['valid'], separators=(',',':'))}) }},\n")
js_ns += "};\n"
open(os.path.join(SITE, "_worker.js"), "w", encoding="utf-8").write(js_ns + WORKER_BODY)

NOTFOUND = '''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not in this archive - DCBase</title>
<link rel="stylesheet" href="/styles/prosilver/theme/stylesheet.css">
<link rel="stylesheet" href="/overrides.css">
<style>.na-box{max-width:640px;margin:60px auto;padding:24px 28px;border:1px solid #c8c8c8;
border-left:4px solid #cc2200;background:#f7f7f7;border-radius:3px}.na-box h1{font-size:20px;
margin:0 0 10px;color:#cc2200}.na-box p{margin:8px 0;line-height:1.6}</style></head><body>
<div class="na-box"><h1>Not in this archive</h1>
<p>This thread, forum, post or page is not part of this static backup of the DCBase forums.</p>
<p><a href="/">&larr; Back to the forum index</a></p></div></body></html>'''
open(os.path.join(SITE, "404.html"), "w", encoding="utf-8").write(NOTFOUND)

SEARCH_HTML = r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Search the DCBase forums</title>
<link rel="stylesheet" href="/styles/prosilver/theme/stylesheet.css">
<link rel="stylesheet" href="/assets/css/font-awesome.min.css">
<link rel="stylesheet" href="/overrides.css">
<style>
  #sch-wrap { max-width: 1000px; margin: 0 auto; padding: 16px; }
  #sch-head h1 { font-size: 22px; margin: 6px 0 2px; }
  #sch-head p { color: #536482; margin: 0 0 16px; }
  #sch-form { display: flex; gap: 8px; margin-bottom: 6px; }
  #sch-q { flex: 1; padding: 9px 12px; font-size: 16px; border: 1px solid #b4bac0; border-radius: 4px; }
  #sch-btn { padding: 9px 18px; font-size: 16px; cursor: pointer; border: 1px solid #0f4c81;
             background: #105289; color: #fff; border-radius: 4px; }
  #sch-status { color: #667; font-size: 13px; margin: 10px 2px; min-height: 16px; }
  .sr { padding: 12px 2px; border-bottom: 1px solid #e4e8ec; }
  .sr-title { font-size: 16px; font-weight: bold; }
  .sr-meta { color: #708090; font-size: 12px; margin: 2px 0 4px; }
  .sr-meta .tag { display: inline-block; padding: 0 6px; border-radius: 3px; background: #eef3f7;
                  color: #305; margin-right: 6px; }
  .sr-snip { color: #333; line-height: 1.5; }
  .sr-snip mark { background: #fff2a8; padding: 0 1px; }
  #sch-foot { color: #889; font-size: 12px; margin-top: 24px; border-top: 1px solid #e4e8ec; padding-top: 12px; }
  #sch-foot a { color: #105289; }
</style></head><body>
<div id="sch-wrap">
  <div id="sch-head">
    <p><a href="/">&larr; DCBase forums</a> &nbsp;|&nbsp; <a href="/dcpp_forums/">DC++ archive (2003–2007)</a></p>
    <h1>Search the forums</h1>
    <p>Full-text search across every post in both boards (32,000+ posts).</p>
  </div>
  <form id="sch-form" onsubmit="return run(event)">
    <input id="sch-q" type="search" name="q" placeholder="Search posts and topics…" autocomplete="off" autofocus>
    <button id="sch-btn" type="submit">Search</button>
  </form>
  <div id="sch-status"></div>
  <div id="results"></div>
  <div id="sch-foot">Static archive of the DCBase forums, rebuilt from the phpBB database.
    Search is powered by a Cloudflare D1 full-text index. Login, posting and other interactive
    functions are disabled.</div>
</div>
<script>
function esc(s){ return (s||"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function fmtDate(ts){ if(!ts) return ""; var d=new Date(ts*1000); return isNaN(d)?"":d.toISOString().slice(0,10); }
function snip(s){ return esc(s).split("@@H@@").join("<mark>").split("@@X@@").join("</mark>"); }
function render(data){
  var box=document.getElementById("results"), st=document.getElementById("sch-status");
  if(data.error){ st.textContent="Search is temporarily unavailable."; box.innerHTML=""; return; }
  var rs=data.results||[];
  if(!rs.length){ st.textContent = data.q ? 'No posts found for “'+data.q+'”.' : ""; box.innerHTML=""; return; }
  st.textContent = rs.length + (data.count===50?"+":"") + " result" + (rs.length===1?"":"s") + ' for “'+data.q+'”';
  box.innerHTML = rs.map(function(r){
    var base = r.ns==="d" ? "/dcpp_forums/" : "/";
    var href = base+"viewtopic.php?t="+r.topic_id+(r.start>0?"&start="+r.start:"")+"#p"+r.post_id;
    var tag  = r.ns==="d" ? "DC++ archive" : "forum.dcbase.org";
    return '<div class="sr"><a class="sr-title" href="'+href+'">'+esc(r.title||"(no subject)")+'</a>'+
           '<div class="sr-meta"><span class="tag">'+tag+'</span>by '+esc(r.poster||"?")+' · '+fmtDate(r.post_time)+'</div>'+
           '<div class="sr-snip">'+snip(r.snip)+'</div></div>';
  }).join("");
}
function search(q){
  var st=document.getElementById("sch-status");
  if(!q){ document.getElementById("results").innerHTML=""; st.textContent=""; return; }
  st.textContent="Searching…";
  fetch("/api/forum-search?q="+encodeURIComponent(q)).then(function(r){return r.json();})
    .then(render).catch(function(){ st.textContent="Search is temporarily unavailable."; });
}
function run(e){ if(e) e.preventDefault();
  var q=document.getElementById("sch-q").value.trim();
  history.replaceState(null,"", q ? "?q="+encodeURIComponent(q) : location.pathname);
  search(q); return false; }
(function(){
  var q=new URLSearchParams(location.search).get("q");
  if(q){ document.getElementById("sch-q").value=q; search(q); }
})();
</script>
</body></html>'''
open(os.path.join(SITE, "search.html"), "w", encoding="utf-8").write(SEARCH_HTML)

print("\n=== build stats ===")
for k in sorted(stats): print(f"  {stats[k]:6}  {k}")
print(f"site -> {SITE}")
