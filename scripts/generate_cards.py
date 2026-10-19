#!/usr/bin/env python3
"""Génère les cartes SVG du profil (en-tête, stats, langages, projets).

Aucune dépendance : uniquement la bibliothèque standard.
Variables d'environnement :
  GH_TOKEN  jeton GitHub (un PAT avec le scope `repo` inclut les dépôts privés)
  GH_USER   identifiant GitHub (par défaut : MalikMoussaoui)
"""

import datetime as dt
import json
import math
import os
import pathlib
import textwrap
import urllib.request
from html import escape

USER = os.environ.get("GH_USER", "MalikMoussaoui")
DISPLAY_NAME = "Malik Moussaoui"
TOKEN = os.environ["GH_TOKEN"]
OUT = pathlib.Path(__file__).resolve().parent.parent / "assets"

# Dépôt mis en avant (public uniquement : on y renvoie par un lien).
FEATURED = {
    "maitre-agent": "Plugin Claude Code : une session maître qui pilote des sous-agents, vérifie elle-même et laisse une passation reprenable.",
}

# Fichiers de balisage / config qui faussent la répartition des langages.
IGNORED_LANGS = {"HTML", "CSS", "SCSS", "EJS", "Dockerfile", "PowerShell", "Batchfile", "Makefile", "Objective-C"}

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Ubuntu,'Helvetica Neue',Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"

# Palette « sunset » : violet -> corail -> orange.
THEMES = {
    "dark": dict(bg="#0f0b17", bg2="#1a1226", border="#33243f", text="#f3eefa", muted="#a79bb8",
                 a1="#a78bfa", a2="#fb7185", a3="#fb923c", track="#2a1f38"),
    "light": dict(bg="#ffffff", bg2="#fbf6f3", border="#eadfe8", text="#1d1426", muted="#6e6179",
                  a1="#7c3aed", a2="#e11d48", a3="#ea580c", track="#f1e9ef"),
}


# ---------------------------------------------------------------- données

QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    name
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name isFork isPrivate stargazerCount forkCount description
        primaryLanguage { name color }
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def graphql(variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "User-Agent": "profile-cards"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise SystemExit(f"GraphQL : {payload['errors']}")
    return payload["data"]["user"]


def fetch():
    user = graphql({"login": USER, "after": None})
    repos = list(user["repositories"]["nodes"])
    page = user["repositories"]["pageInfo"]
    while page["hasNextPage"]:
        more = graphql({"login": USER, "after": page["endCursor"]})["repositories"]
        repos += more["nodes"]
        page = more["pageInfo"]
    user["repos"] = repos
    return user


def streaks(calendar):
    days = [d for w in calendar["weeks"] for d in w["contributionDays"]]
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] else 0
        longest = max(longest, run)
    current = 0
    # Aujourd'hui sans contribution ne casse pas encore la série.
    tail = days[:-1] if days and not days[-1]["contributionCount"] else days
    for d in reversed(tail):
        if not d["contributionCount"]:
            break
        current += 1
    return current, longest


def languages(repos, top=8):
    """Pondère par taille ET nombre de dépôts, pour ne pas écraser les petits langages."""
    size, count, color = {}, {}, {}
    for r in repos:
        if r["isFork"]:
            continue
        for e in r["languages"]["edges"]:
            name = e["node"]["name"]
            if name in IGNORED_LANGS:
                continue
            size[name] = size.get(name, 0) + e["size"]
            count[name] = count.get(name, 0) + 1
            color[name] = e["node"]["color"] or "#888888"
    score = {n: math.sqrt(size[n]) * math.sqrt(count[n]) for n in size}
    best = sorted(score, key=score.get, reverse=True)[:top]
    total = sum(score[n] for n in best) or 1
    return [(n, score[n] / total * 100, color[n]) for n in best]


def fmt(n):
    return f"{n:,}".replace(",", " ")


# ---------------------------------------------------------------- briques SVG

def svg(w, h, body, t, title):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none" role="img" aria-labelledby="t">
<title id="t">{escape(title)}</title>
<style>
  text {{ font-family: {FONT}; }}
  text:not([fill]) {{ fill: {t['text']}; }}
  .mono {{ font-family: {MONO}; }}
  .muted {{ fill: {t['muted']}; }}
  .title {{ font-size: 17px; font-weight: 700; }}
  .fade {{ animation: fade .6s ease-out both; }}
  @keyframes fade {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; transform: none; }} }}
  @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} }}
</style>
<defs>
  <linearGradient id="grad" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="{t['a1']}"/><stop offset=".55" stop-color="{t['a2']}"/><stop offset="1" stop-color="{t['a3']}"/>
  </linearGradient>
  <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{t['a1']}" stop-opacity=".55"/><stop offset=".5" stop-color="{t['border']}"/><stop offset="1" stop-color="{t['a2']}" stop-opacity=".45"/>
  </linearGradient>
</defs>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="14" fill="{t['bg']}" stroke="url(#edge)"/>
{body}
</svg>
"""


def card_title(label, t, x=24, y=38):
    return (f'<rect x="{x}" y="{y - 14}" width="4" height="18" rx="2" fill="url(#grad)"/>'
            f'<text x="{x + 14}" y="{y}" class="title">{escape(label)}</text>')


# ---------------------------------------------------------------- cartes

def header(t, name):
    w, h = 1200, 300
    blobs = f"""
  <g filter="url(#blur)" opacity=".75">
    <circle cx="230" cy="80" r="170" fill="{t['a1']}" style="animation: drift1 14s ease-in-out infinite alternate"/>
    <circle cx="980" cy="230" r="190" fill="{t['a2']}" style="animation: drift2 17s ease-in-out infinite alternate"/>
    <circle cx="640" cy="320" r="140" fill="{t['a3']}" opacity=".7" style="animation: drift1 20s ease-in-out infinite alternate-reverse"/>
  </g>"""
    grid = "".join(f'<path d="M{x} 0V{h}" />' for x in range(0, w, 40)) + "".join(
        f'<path d="M0 {y}H{w}" />' for y in range(0, h, 40))
    body = f"""
<defs>
  <filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="70"/></filter>
  <clipPath id="clip"><rect width="{w}" height="{h}" rx="14"/></clipPath>
  <linearGradient id="shine" x1="0" y1="0" x2="1" y2="0" spreadMethod="repeat">
    <stop offset="0" stop-color="{t['a1']}"/><stop offset=".33" stop-color="{t['a2']}"/>
    <stop offset=".66" stop-color="{t['a3']}"/><stop offset="1" stop-color="{t['a1']}"/>
    <animateTransform attributeName="gradientTransform" type="translate" values="-1 0;0 0" dur="6s" repeatCount="indefinite"/>
  </linearGradient>
</defs>
<style>
  @keyframes drift1 {{ to {{ transform: translate(90px, 40px); }} }}
  @keyframes drift2 {{ to {{ transform: translate(-110px, -50px); }} }}
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
  .name {{ font-size: 76px; font-weight: 800; letter-spacing: -2px; }}
  .sub {{ font-size: 24px; font-weight: 500; }}
</style>
<g clip-path="url(#clip)">
  {blobs}
  <rect width="{w}" height="{h}" fill="{t['bg']}" opacity=".55"/>
  <g stroke="{t['text']}" stroke-opacity=".05">{grid}</g>
</g>
<text x="600" y="78" text-anchor="middle" class="mono muted fade" font-size="17">~ $ whoami</text>
<text x="600" y="168" text-anchor="middle" class="name fade" style="animation-delay:.15s" fill="url(#shine)">{escape(name)}</text>
<text x="600" y="218" text-anchor="middle" class="sub fade" style="animation-delay:.35s">aka <tspan font-weight="800" fill="url(#grad)">Chopa</tspan> · développeur full-stack &amp; créateur de jeux</text>
<g class="fade" style="animation-delay:.55s">
  <text x="600" y="262" text-anchor="middle" class="mono muted" font-size="15">TypeScript · Lua · FiveM · Roblox · IA<tspan fill="{t['a2']}" style="animation: blink 1s steps(1) infinite"> ▍</tspan></text>
</g>"""
    return svg(w, h, body, t, f"{name} aka Chopa")


ICONS = {
    # Octicons (MIT), 16x16.
    "pulse": "M6 2c.306 0 .582.187.696.471L10 10.731l1.304-3.26A.751.751 0 0 1 12 7h3.25a.75.75 0 0 1 0 1.5h-2.742l-1.812 4.528a.751.751 0 0 1-1.392 0L6 4.77 4.696 8.03A.75.75 0 0 1 4 8.5H.75a.75.75 0 0 1 0-1.5h2.742l1.812-4.529A.751.751 0 0 1 6 2Z",
    "commit": "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z",
    "pr": "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z",
    "repo": "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z",
    "flame": "M9.533.753V.752c.217 2.385 1.463 3.626 2.653 4.81C13.37 6.74 14.498 7.863 14.498 10c0 3.5-3 6-6.5 6S1.5 13.512 1.5 10c0-1.298.536-2.56 1.425-3.286.376-.308.862 0 1.035.454C4.46 8.487 5.581 8.419 6 8c.282-.282.341-.811-.003-1.5C4.34 3.187 7.035.75 8.77.146c.39-.135.726.183.763.607ZM7.998 14.5c2.832 0 5-1.98 5-4.5 0-1.463-.68-2.19-1.879-3.383l-.036-.037c-1.013-1.008-2.3-2.29-2.834-4.434-.322.256-.63.579-.864.953-.432.696-.621 1.58-.046 2.73.473.947.67 2.284-.278 3.232-.61.61-1.545.84-2.403.633a2.79 2.79 0 0 1-1.436-.874A3.198 3.198 0 0 0 3 10c0 2.53 2.164 4.5 4.998 4.5Z",
    "trophy": "M3.217 6.962A3.75 3.75 0 0 1 0 3.25v-.5C0 1.784.784 1 1.75 1h1.356c.228-.585.796-1 1.462-1h6.864c.647 0 1.227.403 1.452 1h1.366c.966 0 1.75.784 1.75 1.75v.5a3.75 3.75 0 0 1-3.225 3.712 4.75 4.75 0 0 1-3.149 3.35l.335 2.188h.789a1.75 1.75 0 0 1 1.75 1.75v1a.75.75 0 0 1-.75.75H4.25a.75.75 0 0 1-.75-.75v-1a1.75 1.75 0 0 1 1.75-1.75h.79l.334-2.187a4.75 4.75 0 0 1-3.157-3.35ZM4.5 1.75v3.5a3.25 3.25 0 0 0 6.5 0V1.75a.25.25 0 0 0-.25-.25H4.75a.25.25 0 0 0-.25.25ZM5.25 13.5a.25.25 0 0 0-.25.25v.25h6v-.25a.25.25 0 0 0-.25-.25ZM1.75 2.5a.25.25 0 0 0-.25.25v.5c0 .865.587 1.594 1.385 1.81A4.731 4.731 0 0 1 3 4.25V2.5Zm11 1.75v.81A1.876 1.876 0 0 0 14.5 3.25v-.5a.25.25 0 0 0-.25-.25H12.75Z",
    "star": "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Zm0 2.445L6.615 5.5a.75.75 0 0 1-.564.41l-3.097.45 2.24 2.184a.75.75 0 0 1 .216.664l-.528 3.084 2.769-1.456a.75.75 0 0 1 .698 0l2.77 1.456-.53-3.084a.75.75 0 0 1 .216-.664l2.24-2.183-3.096-.45a.75.75 0 0 1-.564-.41L8 2.694Z",
    "fork": "M5 5.372v.878c0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75v-.878a2.25 2.25 0 1 1 1.5 0v.878a2.25 2.25 0 0 1-2.25 2.25h-1.5v2.128a2.251 2.251 0 1 1-1.5 0V8.5h-1.5A2.25 2.25 0 0 1 3.5 6.25v-.878a2.25 2.25 0 1 1 1.5 0ZM5 3.25a.75.75 0 1 0-1.5 0 .75.75 0 0 0 1.5 0Zm6.75.75a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm-3 8.75a.75.75 0 1 0-1.5 0 .75.75 0 0 0 1.5 0Z",
}


def icon(name, x, y, color, scale=1.0):
    return f'<path transform="translate({x} {y}) scale({scale})" d="{ICONS[name]}" fill="{color}"/>'


def stats_card(t, user):
    w, h = 500, 230
    cc = user["contributionsCollection"]
    cal = cc["contributionCalendar"]
    current, longest = streaks(cal)
    since = user["createdAt"][:4]
    rows = [
        ("commit", "Commits (12 mois)", fmt(cc["totalCommitContributions"] + cc["restrictedContributionsCount"])),
        ("pr", "Pull requests", fmt(user["pullRequests"]["totalCount"])),
        ("repo", "Dépôts", fmt(user["repositories"]["totalCount"])),
        ("flame", "Série en cours", f"{current} j"),
        ("trophy", "Meilleure série", f"{longest} j"),
    ]
    body = [card_title("Activité", t)]
    for i, (ic, label, value) in enumerate(rows):
        y = 74 + i * 30
        delay = 0.15 + i * 0.12
        body.append(
            f'<g class="fade" style="animation-delay:{delay:.2f}s">'
            f'{icon(ic, 26, y - 12, t["a1"] if i % 2 == 0 else t["a2"])}'
            f'<text x="52" y="{y}" font-size="14" class="muted">{label}</text>'
            f'<text x="290" y="{y}" font-size="14" font-weight="700" text-anchor="end">{value}</text></g>'
        )
    # Anneau : contributions de l'année.
    cx, cy, r = 395, 128, 62
    circ = 2 * math.pi * r
    body.append(f"""
<style>
  @keyframes ring {{ from {{ stroke-dashoffset: {circ:.1f}; }} to {{ stroke-dashoffset: 0; }} }}
  .ring {{ stroke-dasharray: {circ:.1f}; animation: ring 1.6s cubic-bezier(.3,.7,.2,1) both; }}
</style>
<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{t['track']}" stroke-width="9"/>
<circle cx="{cx}" cy="{cy}" r="{r}" stroke="url(#grad)" stroke-width="9" stroke-linecap="round" class="ring" transform="rotate(-90 {cx} {cy})"/>
<text x="{cx}" y="{cy + 2}" text-anchor="middle" font-size="30" font-weight="800" class="fade" style="animation-delay:.6s">{fmt(cal['totalContributions'])}</text>
<text x="{cx}" y="{cy + 24}" text-anchor="middle" font-size="12" class="muted fade" style="animation-delay:.7s">contributions</text>
<text x="{cx}" y="{cy + 92}" text-anchor="middle" font-size="12" class="muted fade" style="animation-delay:.8s">sur GitHub depuis {since}</text>""")
    return svg(w, h, "\n".join(body), t, "Statistiques GitHub")


def langs_card(t, langs):
    w, h = 500, 230
    body = [card_title("Langages", t)]
    x0, bw, y0 = 24, w - 48, 60
    body.append(f'<clipPath id="bar"><rect x="{x0}" y="{y0}" width="{bw}" height="10" rx="5"/></clipPath>')
    body.append(f'<style>@keyframes grow {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}'
                f'.grow {{ transform-origin: {x0}px 0; animation: grow 1.2s cubic-bezier(.3,.7,.2,1) both; }}</style>')
    body.append(f'<rect x="{x0}" y="{y0}" width="{bw}" height="10" rx="5" fill="{t["track"]}"/>')
    segs, x = [], x0
    for _, pct, color in langs:
        seg = bw * pct / 100
        segs.append(f'<rect x="{x:.2f}" y="{y0}" width="{seg + 0.6:.2f}" height="10" fill="{color}"/>')
        x += seg
    body.append(f'<g clip-path="url(#bar)"><g class="grow">{"".join(segs)}</g></g>')
    for i, (name, pct, color) in enumerate(langs):
        col, row = divmod(i, 4)
        x = 24 + col * 236
        y = 106 + row * 30
        delay = 0.3 + i * 0.08
        body.append(
            f'<g class="fade" style="animation-delay:{delay:.2f}s">'
            f'<circle cx="{x + 6}" cy="{y - 5}" r="6" fill="{color}"/>'
            f'<text x="{x + 20}" y="{y}" font-size="14" font-weight="600">{escape(name)}</text>'
            f'<text x="{x + 210}" y="{y}" font-size="13" class="muted mono" text-anchor="end">{pct:.1f}%</text></g>'
        )
    return svg(w, h, "\n".join(body), t, "Langages les plus utilisés")


def repo_card(t, repo, desc):
    w, h = 480, 150
    lines = textwrap.wrap(desc, 62)[:3]
    lang = repo["primaryLanguage"] or {"name": "—", "color": t["muted"]}
    body = [
        icon("repo", 24, 22, t["a1"]),
        f'<text x="50" y="35" font-size="16" font-weight="700" fill="url(#grad)">{escape(repo["name"])}</text>',
    ]
    for i, line in enumerate(lines):
        body.append(f'<text x="24" y="{66 + i * 20}" font-size="13" class="muted fade" '
                    f'style="animation-delay:{0.1 + i * 0.08:.2f}s">{escape(line)}</text>')
    y = h - 22
    body.append(
        f'<circle cx="30" cy="{y - 4}" r="6" fill="{lang["color"] or t["muted"]}"/>'
        f'<text x="44" y="{y}" font-size="13">{escape(lang["name"])}</text>'
        f'{icon("star", 150, y - 12, t["muted"])}'
        f'<text x="172" y="{y}" font-size="13" class="muted">{repo["stargazerCount"]}</text>'
        f'{icon("fork", 205, y - 12, t["muted"])}'
        f'<text x="227" y="{y}" font-size="13" class="muted">{repo["forkCount"]}</text>'
    )
    return svg(w, h, "\n".join(body), t, repo["name"])


# ---------------------------------------------------------------- main

def main():
    user = fetch()
    langs = languages(user["repos"])
    by_name = {r["name"]: r for r in user["repos"]}
    OUT.mkdir(exist_ok=True)
    for theme, t in THEMES.items():
        files = {
            f"header-{theme}.svg": header(t, DISPLAY_NAME),
            f"stats-{theme}.svg": stats_card(t, user),
            f"langs-{theme}.svg": langs_card(t, langs),
        }
        for name, desc in FEATURED.items():
            if name in by_name and not by_name[name]["isPrivate"]:
                files[f"repo-{name}-{theme}.svg"] = repo_card(t, by_name[name], desc)
        for fname, content in files.items():
            (OUT / fname).write_text(content, encoding="utf-8")
    print(f"{len(THEMES)} thèmes générés dans {OUT} — langages : "
          + ", ".join(f"{n} {p:.0f}%" for n, p, _ in langs))


if __name__ == "__main__":
    main()
