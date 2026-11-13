#!/usr/bin/env python3
"""Build the static live page folder (design 9.1, page v2 DESIGN.md §9.4 and §10): copy pages/live, write config.json, fill the CSP
origins, write the static texts in both languages and insert the « How it works » tab (about/fr.html, about/en.html) into index.html.

Usage: build_page.py --repo OWNER/REPO --stream https://live.DOMAIN --out DIR [--birth-utc YYYY-MM-DDTHH:MM:SSZ]
                     [--site https://DOMAIN | none] [--src pages/live]
Never pushes anything. `--out` must be missing, empty, or carry the `.sol0-page` marker of a previous build.
In index.html: {{STREAM_ORIGIN}}, {{STATE_ORIGIN}} (CSP: the bare origin of the published state), {{STATE_SRC}} (CSP: the state
branch of --repo only, https://raw.githubusercontent.com/OWNER/REPO/state/), {{t:id}} (text of i18n.json id in both languages: one
span per language, the page shows the one of <html lang>), {{tb:id}} (both languages shown, for <noscript>), {{a:id}} (English, for
an attribute or the title; app.js rewrites it in the page language), <!--ABOUT:fr--> and <!--ABOUT:en--> (the fragments, HTML
comments removed), {{REPO_URL}}, {{REPO}}, <!--SEO--> (canonical, Open Graph, X card and JSON-LD for the site, or nothing).
Site (SEO plan, lot A): --site, a bare https origin, the address the page is indexed under (canonical https://DOMAIN/); by default
the stream's host without its first label `live.` (https://live.sol0.fr -> https://sol0.fr); `none`: no canonical, no Open Graph,
no sitemap. With a site: robots.txt (with its Sitemap line) and sitemap.xml (one URL: the site's root); without: robots.txt only.
Copied: the top-level files of --src (index.html processed; 404.html, favicon.ico as they are), icons/*.png, about/img/* (.png
.webp .jpg .svg) and media/* (.mp4 .png: the intro cinematic, consigne 52); never about/*.html, about/SOURCES.md, fixtures or
anything else. A media/ MP4 must start with `ftyp` and have its `moov` before its `mdat` (it starts while loading); every media/NAME
written in a copied text file must exist in media/.
Refuses: a non-https stream or site, an origin that is not a bare host, a fragment outside the allow-list of tags and attributes
(SEC-30: no script, style, meta, base, iframe, object, embed, form, event handler; href only to an anchor #... or the repository,
src only to about/img/...; url() only to an #id; checked on the exact served text, comments removed first; every `<` opens an
allowed tag, strict nesting, nothing unfinished at the end, no http-equiv, backslash or `//` but the repository's), an unknown
text id, an image over 300 KB, an MP4 over 4 MB, and the budgets: JS + CSS <= 150 KB, JSON <= 40 KB, index.html <= 250 KB,
images <= 2 MB, 404.html + robots.txt + sitemap.xml <= 64 KB, media <= 4 MB; and any `http(s)://` in the files that is not one this script wrote (CSP sources,
repository, site, schema.org in the JSON-LD, the sitemap namespace).
Output is deterministic (same inputs, same bytes); standard library only (the server runs it too).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import struct
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKER = ".sol0-page"
BUDGETS = {"code": 150 * 1024, "json": 40 * 1024, "html": 250 * 1024, "images": 2 * 1024 * 1024, "other": 64 * 1024,
           "media": 4 * 1024 * 1024}
MAX_IMAGE = 300 * 1024
MEDIA_MAX = {".mp4": 4 * 1024 * 1024, ".png": MAX_IMAGE}        # consigne 51: intro.mp4 target <= 3 MB, hard cap 4 MB
MEDIA_REF = re.compile(r"media/([A-Za-z0-9._-]+)")
IMAGE_EXT = (".png", ".webp", ".jpg", ".svg")
BINARY_EXT = (".ico", ".png", ".webp", ".jpg")
OG_IMAGE = "bande-annonce-image180.png"        # labelled ILLUSTRATION in the picture (the trailer's only exception to « all is real »)
OG_IMAGE_ALT = ("Pixel-art illustration, not a real image of Sol-0: a wheeled rover with a camera mast in a rust desert, "
                "marked ILLUSTRATION.")
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
SCHEMA_ORG = "https://schema.org"
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
ORIGIN_RE = re.compile(r"^https://[a-z0-9](?:[a-z0-9.-]{0,250}[a-z0-9])?(?::[0-9]{1,5})?$")
STATE_ORIGIN = "https://raw.githubusercontent.com"
FORBIDDEN = re.compile(r"<script|<style|\sstyle\s*=|\son[a-z]+\s*=|javascript:", re.I)

# SEC-30 (FRONT-06): the explainer fragments go through an allow-list (tags, attributes, values), not only a shape check. Anything
# else refuses the build (the fragment is never rewritten: what is served is what was reviewed, comments removed).
_GLOBAL_ATTRS = {"class", "id", "lang", "role", "tabindex", "title", "aria-label", "aria-labelledby", "aria-describedby", "aria-hidden",
                 "data-sec", "data-explain"}
_SVG_ATTRS = {"fill", "fill-opacity", "stroke", "stroke-width", "stroke-dasharray", "stroke-linecap", "stroke-linejoin",
              "stroke-opacity", "opacity", "marker-end", "marker-start", "marker-mid", "font-size", "font-weight", "font-family",
              "text-anchor", "dominant-baseline", "transform", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "dx",
              "dy", "width", "height", "points", "d", "viewbox"}
_TAGS = {t: set() for t in ("div", "section", "nav", "h2", "h3", "h4", "h5", "h6", "p", "strong", "em", "b", "i", "code", "span", "small",
                            "sup", "sub", "abbr", "kbd", "blockquote", "ul", "ol", "li", "dl", "dt", "dd", "figure", "figcaption", "br",
                            "table", "caption", "thead", "tbody", "tfoot", "tr", "summary")}
_TAGS.update({"a": {"href"}, "img": {"src", "alt", "width", "height", "loading", "decoding"}, "th": {"scope", "colspan", "rowspan"},
              "td": {"colspan", "rowspan"}, "details": {"open"}})
_TAGS.update({t: _SVG_ATTRS for t in ("svg", "g", "defs", "title", "desc", "path", "rect", "text", "tspan", "circle", "ellipse", "line",
                                       "polyline", "polygon")})
_TAGS["marker"] = _SVG_ATTRS | {"markerheight", "markerwidth", "orient", "refx", "refy"}
_SVG_TAGS = {"svg", "g", "defs", "title", "desc", "path", "rect", "text", "tspan", "circle", "ellipse", "line", "polyline", "polygon",
             "marker"}
_VOID = {"br", "img"}
_HREF_RE = re.compile(r"^#[A-Za-z0-9/_-]*$")
_SRC_RE = re.compile(r"^about/img/[A-Za-z0-9._-]+\.(?:png|webp|jpg|svg)$")
_URLFN_RE = re.compile(r"url\(", re.I)
_URLFN_OK = re.compile(r"^url\(#[A-Za-z0-9_-]+\)$")
# Checks on the exact served text that do not depend on how html.parser tokenizes it (VERIF-P I1: a browser and html.parser can
# disagree on where a tag starts or ends; these hold whatever the tokenizer): every `<` opens an allowed tag or end tag (a literal
# `<` is written &lt;); no http-equiv, no backslash (CSS escapes), no `//` but the repository's; every href/src assignment, quoted or
# not, is allowed as written; every url( is url(#id).
_LT_RE = re.compile(r"<(/?)([^\s/>]*)")
_SERVED_NO = re.compile(r"http-equiv|\\|[\s/\"'=]on[a-z]+\s*=|srcdoc|formaction|xlink:|xml:base|<!|<\?", re.I)
_ASSIGN_RE = re.compile(r"(?<![A-Za-z0-9_:.-])(href|src)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>\"']*)", re.I)
_URLFN_ALL = re.compile(r"url\([^)]*\)?", re.I)


class _AllowList(HTMLParser):
    def __init__(self, name: str, links: set):
        super().__init__(convert_charrefs=False)          # text arrives as written: a raw `<` in text is seen and refused
        self.name, self.links = name, links
        self.open = []                                    # strict nesting: the fragment can never swallow the page around it

    def _no(self, why: str):
        raise SystemExit("about/%s: %s refused (SEC-30 allow-list)" % (self.name, why))

    def handle_starttag(self, tag, attrs):
        self._check(tag, attrs)
        if tag not in _VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self._check(tag, attrs)
        if tag not in _VOID and tag not in _SVG_TAGS:     # <div/> opens a div in HTML: refused (only void and SVG elements)
            self._no("self-closing <%s/>" % tag)

    def handle_endtag(self, tag):
        if tag not in _TAGS:
            self._no("end tag </%s>" % tag)
        if not self.open or self.open[-1] != tag:
            self._no("end tag </%s> that does not close <%s>" % (tag, self.open[-1] if self.open else ""))
        self.open.pop()

    def _check(self, tag, attrs):
        if tag not in _TAGS:
            self._no("tag <%s>" % tag)
        for k, v in attrs:
            if k not in _TAGS[tag] and k not in _GLOBAL_ATTRS:
                self._no("attribute %s on <%s>" % (k, tag))
            v = "" if v is None else v            # values arrive with their character references decoded
            if k == "href" and not (_HREF_RE.match(v) or v in self.links):
                self._no("link %r (only #anchors and the repository)" % v)
            if k == "src" and not _SRC_RE.match(v):
                self._no("source %r (only about/img/...)" % v)
            if _URLFN_RE.search(v) and not _URLFN_OK.match(v.strip()):
                self._no("value %r of %s (url() only to an #id)" % (v, k))
            if "\\" in v or "<" in v:
                self._no("value %r of %s (no backslash, no <)" % (v, k))

    def handle_data(self, data):
        if "<" in data:                           # e.g. the content of an SVG <title> that html.parser reads as text
            self._no("raw < in text %r (write &lt;)" % data[:40])

    def handle_comment(self, data):
        self._no("comment left in the served text")

    def handle_decl(self, decl):
        self._no("declaration")

    def handle_pi(self, data):
        self._no("processing instruction")

    def unknown_decl(self, data):
        self._no("declaration")


def _allow_list(name: str, txt: str, links: set) -> None:
    """SEC-30 on `txt`, the exact text that is served (comments already removed, {{REPO_URL}} filled): tokenizer-independent
    checks first, then the html.parser allow-list, which must consume the whole text (nothing left unfinished at the end)."""
    def no(why):
        raise SystemExit("about/%s: %s refused (SEC-30 allow-list)" % (name, why))
    for m in _LT_RE.finditer(txt):
        if m.group(2).lower() not in _TAGS:
            no("markup %r (only the allowed tags; a literal < is written &lt;)" % txt[m.start():m.start() + 24])
    m = _SERVED_NO.search(txt)
    if m:
        no("%r (http-equiv, backslash, event handler, srcdoc, formaction, xlink, declaration)" % m.group(0))
    rest = txt
    for u in sorted(links, key=len, reverse=True):
        rest = rest.replace(u, "")
    if "//" in rest:
        no("'//' (protocol-relative or external address; only the repository's link)")
    for m in _ASSIGN_RE.finditer(txt):
        v = m.group(2)
        v = v[1:-1] if v[:1] in "\"'" else v
        if m.group(1).lower() == "href" and not (_HREF_RE.match(v) or v in links):
            no("link %r (only #anchors and the repository)" % v)
        if m.group(1).lower() == "src" and not _SRC_RE.match(v):
            no("source %r (only about/img/...)" % v)
    for m in _URLFN_ALL.finditer(txt):
        if not _URLFN_OK.match(m.group(0)):
            no("%r (url() only to an #id)" % m.group(0))
    p = _AllowList(name, links)
    p.feed(txt)
    if p.rawdata or p.cdata_elem:
        no("unfinished markup at the end %r" % (p.rawdata[:40] if p.rawdata else "<%s>" % p.cdata_elem))
    p.close()
    if p.open:
        no("unclosed <%s>" % p.open[-1])


def _texts(src: Path) -> dict:
    p = src / "i18n.json"
    return json.loads(p.read_text(encoding="utf-8"))["strings"] if p.is_file() else {}


def _fill_texts(doc: str, strings: dict) -> str:
    def tid(m):
        i = m.group(2)
        if i not in strings:
            raise SystemExit("index.html: unknown text id %r" % i)
        return i

    def both(m):
        s = strings[tid(m)]
        if m.group(1) == "tb":
            return '<p lang="fr">%s</p><p lang="en">%s</p>' % (html.escape(s["fr"], False), html.escape(s["en"], False))
        if m.group(1) == "a":
            return html.escape(s["en"], True)
        return '<span class="l-fr" lang="fr">%s</span><span class="l-en" lang="en">%s</span>' % (
            html.escape(s["fr"], False), html.escape(s["en"], False))
    return re.sub(r"\{\{(t|tb|a):([a-z0-9._-]+)\}\}", both, doc)


def _fragment(src: Path, lang: str, repo_url: str) -> str:
    p = src / "about" / ("%s.html" % lang)
    if not p.is_file():
        return ""
    txt = p.read_text(encoding="utf-8")
    if FORBIDDEN.search(txt):
        raise SystemExit("about/%s: script, style, event handler or javascript: refused" % p.name)
    # comments removed first, then the allow-list runs on the exact text that is served (VERIF-P I1: checking before the removal let
    # a comment opened inside an attribute value hide a tag)
    served = re.sub(r"<!--.*?-->", "", txt, flags=re.S).replace("{{REPO_URL}}", repo_url).strip("\n")
    if FORBIDDEN.search(served):
        raise SystemExit("about/%s: script, style, event handler or javascript: refused" % p.name)
    _allow_list(p.name, served, {repo_url})
    return served


BIRTH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _birth(v):
    if v is None:
        return None
    from datetime import datetime
    if not BIRTH_RE.match(v):
        raise SystemExit("bad --birth-utc (YYYY-MM-DDTHH:MM:SSZ expected)")
    try:
        datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise SystemExit("bad --birth-utc (not a real date)")
    return v


SITE_AUTO = "auto"


def _site(site, stream: str):
    """The site's origin (SEO): `none` -> None; `auto` -> the stream's host without `live.` when that leaves a dotted host, else
    None; anything else must be a bare https origin."""
    if site is None or site == SITE_AUTO:
        m = re.match(r"^https://live\.([a-z0-9-]+(?:\.[a-z0-9-]+)+(?::[0-9]{1,5})?)$", stream)
        return ("https://" + m.group(1)) if m else None
    if site == "none":
        return None
    site = site.rstrip("/")
    if not ORIGIN_RE.match(site):
        raise SystemExit("bad --site: a bare https origin is expected (https://example.org), or none")
    return site


def _png_size(p: Path):
    d = p.read_bytes()[:24]
    if len(d) < 24 or d[:8] != b"\x89PNG\r\n\x1a\n" or d[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", d[16:24])


def _seo_block(site: str, strings: dict, src: Path) -> str:
    """<head> lines for https://SITE/ (SEO plan, lot A: one indexable URL, so no hreflang yet): canonical, Open Graph (the trailer
    still, labelled ILLUSTRATION in the picture, size read from the file), X card, WebSite JSON-LD. English texts of i18n.json (the
    page's x-default language), escaped."""
    e = lambda v: html.escape(v, True)
    title, desc = strings["d.title"]["en"], strings["d.desc"]["en"]
    root = site + "/"
    out = ['<link rel="canonical" href="%s">' % e(root),
           '<meta property="og:type" content="website">',
           '<meta property="og:site_name" content="Sol-0">',
           '<meta property="og:title" content="%s">' % e(title),
           '<meta property="og:description" content="%s">' % e(desc),
           '<meta property="og:url" content="%s">' % e(root),
           '<meta property="og:locale" content="en_US">',
           '<meta property="og:locale:alternate" content="fr_FR">']
    img = src / "about" / "img" / OG_IMAGE
    wh = _png_size(img) if img.is_file() else None
    if wh:
        out += ['<meta property="og:image" content="%s">' % e(root + "about/img/" + OG_IMAGE),
                '<meta property="og:image:type" content="image/png">',
                '<meta property="og:image:width" content="%d">' % wh[0],
                '<meta property="og:image:height" content="%d">' % wh[1],
                '<meta property="og:image:alt" content="%s">' % e(OG_IMAGE_ALT)]
    out.append('<meta name="twitter:card" content="%s">' % ("summary_large_image" if wh else "summary"))
    ld = {"@context": SCHEMA_ORG, "@type": "WebSite", "name": "Sol-0", "alternateName": ["SOL-0", "Sol-0 live"], "url": root,
          "inLanguage": ["en", "fr"]}
    out.append('<script type="application/ld+json">%s</script>' % json.dumps(ld, separators=(",", ":")).replace("<", "\\u003c"))
    return "\n".join(out)


def _mp4_ok(name: str, data: bytes) -> None:
    """Top-level boxes of an MP4: `ftyp` first, `moov` before `mdat` (« faststart »: playback starts while loading); sizes 0 (to
    the end), 1 (64-bit) and 32-bit understood; a box that runs past the end refuses."""
    o, seen = 0, []
    while o < len(data):
        if o + 8 > len(data):
            raise SystemExit("media/%s: truncated MP4 box at %d" % (name, o))
        n, kind = struct.unpack(">I4s", data[o:o + 8])
        if n == 1:
            if o + 16 > len(data):
                raise SystemExit("media/%s: truncated MP4 box at %d" % (name, o))
            n = struct.unpack(">Q", data[o + 8:o + 16])[0]
        elif n == 0:
            n = len(data) - o
        if n < 8 or o + n > len(data):
            raise SystemExit("media/%s: bad MP4 box size at %d" % (name, o))
        seen.append(kind)
        o += n
    if not seen or seen[0] != b"ftyp" or b"moov" not in seen or b"mdat" not in seen or seen.index(b"moov") > seen.index(b"mdat"):
        raise SystemExit("media/%s: not a faststart MP4 (ftyp first, moov before mdat): %s" % (name, [k.decode("latin-1") for k in seen]))


def _urls_ok(name: str, txt: str, allowed: set, prefixes: tuple) -> None:
    for u in re.findall(r"https?://[^\s\"'<>;,]*", txt):
        if u not in allowed and not any(u.startswith(p) for p in prefixes):
            raise SystemExit("%s: URL %r outside the configuration" % (name, u))


def build(repo: str, stream: str, out: Path, src: Path, birth_utc=None, site=None) -> dict:
    if not REPO_RE.match(repo):
        raise SystemExit("bad --repo (OWNER/REPO expected)")
    birth_utc = _birth(birth_utc)
    stream = stream.rstrip("/")
    if not ORIGIN_RE.match(stream):
        raise SystemExit("bad --stream: a bare https origin is expected (https://live.example.org)")
    site = _site(site, stream)
    if out.exists() and any(out.iterdir()) and not (out / MARKER).is_file():
        raise SystemExit("--out is not empty and has no %s marker: refusing" % MARKER)
    if out.exists():
        for p in sorted(out.iterdir()):
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
    out.mkdir(parents=True, exist_ok=True)
    repo_url = "https://github.com/%s" % repo
    state_src = "%s/%s/state/" % (STATE_ORIGIN, repo)        # SEC-15/29: the only GitHub path the page may read (contract P = S)
    strings = _texts(src)
    seo = _seo_block(site, strings, src) if site else ""
    sizes = {"code": 0, "json": 0, "html": 0, "images": 0, "other": 0, "media": 0}

    def kind(name: str) -> str:            # "html" = index.html (the page); "other" = 404.html, robots.txt, sitemap.xml
        if name == "index.html":
            return "html"
        if name.endswith((".html", ".txt", ".xml")):
            return "other"
        if name.endswith(".json"):
            return "json"
        return "images" if name.endswith(BINARY_EXT) else "code"
    for f in sorted(src.iterdir()):
        if not f.is_file():
            continue
        data = f.read_bytes()
        if f.name == "index.html":
            doc = data.decode("utf-8").replace("{{STREAM_ORIGIN}}", stream).replace("{{STATE_ORIGIN}}", STATE_ORIGIN)
            doc = doc.replace("{{STATE_SRC}}", state_src)
            doc = _fill_texts(doc, strings)
            for lang in ("fr", "en"):
                doc = doc.replace("<!--ABOUT:%s-->" % lang, _fragment(src, lang, repo_url))
            doc = doc.replace("{{REPO_URL}}", repo_url).replace("{{REPO}}", html.escape(repo, True))
            doc = doc.replace("<!--SEO-->\n", seo + "\n" if seo else "").replace("<!--SEO-->", seo)
            data = doc.encode("utf-8")
        sizes[kind(f.name)] += len(data)
        (out / f.name).write_bytes(data)
    for sub, exts in ((("about", "img"), IMAGE_EXT), (("icons",), (".png",))):
        d = src.joinpath(*sub)
        if not d.is_dir():
            continue
        (out.joinpath(*sub)).mkdir(parents=True)
        for f in sorted(d.iterdir()):
            if not f.is_file() or f.suffix.lower() not in exts:
                continue
            data = f.read_bytes()
            if len(data) > MAX_IMAGE:
                raise SystemExit("%s/%s is %d bytes (> %d)" % ("/".join(sub), f.name, len(data), MAX_IMAGE))
            sizes["images"] += len(data)
            out.joinpath(*sub, f.name).write_bytes(data)
    # the intro cinematic (consigne 52): served from the page's own folder (CSP media-src 'self'; the poster through img-src 'self')
    media = set()
    if (src / "media").is_dir():
        (out / "media").mkdir()
        for f in sorted((src / "media").iterdir()):
            ext = f.suffix.lower()
            if not f.is_file() or ext not in MEDIA_MAX or f.name.startswith("."):
                continue
            data = f.read_bytes()
            if len(data) > MEDIA_MAX[ext]:
                raise SystemExit("media/%s is %d bytes (> %d)" % (f.name, len(data), MEDIA_MAX[ext]))
            if ext == ".mp4":
                _mp4_ok(f.name, data)
            elif not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise SystemExit("media/%s is not a PNG" % f.name)
            sizes["media"] += len(data)
            (out / "media" / f.name).write_bytes(data)
            media.add(f.name)
    # SEO plan lot A: robots.txt for the page's hosts (S serves its own for live.DOMAIN's API), one-URL sitemap.xml with a site
    robots = "User-agent: *\nAllow: /\n" + ("\nSitemap: %s/sitemap.xml\n" % site if site else "")
    (out / "robots.txt").write_text(robots, encoding="utf-8")
    sizes["other"] += len(robots.encode("utf-8"))
    if site:
        sm = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="%s">\n<url><loc>%s/</loc></url>\n</urlset>\n'
              % (SITEMAP_NS, html.escape(site, False)))
        (out / "sitemap.xml").write_text(sm, encoding="utf-8")
        sizes["other"] += len(sm.encode("utf-8"))
    cfg_d = {"stream": stream, "stateRaw": "%s/%s/state" % (STATE_ORIGIN, repo), "repo": repo}
    if birth_utc:
        cfg_d["birth_utc"] = birth_utc            # a dated fact given at build time, never guessed
    cfg = json.dumps(cfg_d, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    (out / "config.json").write_bytes(cfg)
    sizes["json"] += len(cfg)
    (out / MARKER).write_text("sol-0 live page\n", encoding="utf-8")
    for k, cap in BUDGETS.items():
        if sizes[k] > cap:
            raise SystemExit("%s is %d bytes (> %d)" % (k, sizes[k], cap))
    # every URL of the written text files is one this script wrote: CSP sources, repository, site, schema.org, sitemap namespace
    site_pre = (site + "/",) if site else ()
    for f in sorted(out.iterdir()):
        if not f.is_file() or f.name in (MARKER, "config.json") or f.name.endswith(BINARY_EXT):
            continue
        txt = f.read_text(encoding="utf-8")
        if f.name == "index.html":
            if "<!--ABOUT" in txt or "<!--SEO" in txt:
                raise SystemExit("index.html: ABOUT or SEO marker left")
            _urls_ok(f.name, txt, {stream, STATE_ORIGIN, state_src, repo_url, SCHEMA_ORG}, site_pre)
        elif f.name == "robots.txt":
            _urls_ok(f.name, txt, set(), site_pre)
        elif f.name == "sitemap.xml":
            _urls_ok(f.name, txt, {SITEMAP_NS}, site_pre)
        else:
            _urls_ok(f.name, txt, set(), ())
        if "{{" in txt:
            raise SystemExit("%s: placeholder left" % f.name)
        for m in MEDIA_REF.finditer(txt):
            if m.group(1) not in media:
                raise SystemExit("%s: media/%s is not in the page" % (f.name, m.group(1)))
    files = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    return {"bytes": sum(sizes.values()), "sizes": sizes, "files": files, "site": site}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--stream", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--birth-utc", default=None, help="birth of the rover, ISO-8601 UTC (2026-11-13T12:11:21Z); absent = no \"alive for\" line")
    ap.add_argument("--site", default=SITE_AUTO, help="origin the page is indexed under (https://sol0.fr), or none; default: the "
                    "stream's host without live.")
    ap.add_argument("--src", default=str(ROOT / "pages" / "live"))
    a = ap.parse_args(argv)
    r = build(a.repo, a.stream, Path(a.out), Path(a.src), a.birth_utc, a.site)
    print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
