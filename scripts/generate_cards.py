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
import random
import textwrap
import base64
import urllib.request
from html import escape

USER = os.environ.get("GH_USER", "MalikChopa")
DISPLAY_NAME = "Chopa"
TOKEN = os.environ["GH_TOKEN"]
OUT = pathlib.Path(__file__).resolve().parent.parent / "assets"

# Fichiers de balisage / config qui faussent la répartition des langages.
IGNORED_LANGS = {"HTML", "CSS", "SCSS", "EJS", "Dockerfile", "PowerShell", "Batchfile", "Makefile", "Objective-C"}

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Ubuntu,'Helvetica Neue',Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"

# Palette noir et blanc, avec un seul accent (orange) utilisé avec parcimonie.
THEMES = {
    "dark": dict(bg="#0a0a0a", bg2="#141414", border="#272727", text="#f2f2f2", muted="#8c8c8c",
                 a1="#f2f2f2", a2="#c4c4c4", a3="#8c8c8c", track="#232323", accent="#ea580c"),
    "light": dict(bg="#ffffff", bg2="#f6f6f6", border="#e0e0e0", text="#111111", muted="#6b6b6b",
                  a1="#111111", a2="#4d4d4d", a3="#999999", track="#ececec", accent="#c2410c"),
}
# Rampes de gris pour la barre des langages (du plus utilisé au moins utilisé).
GRAYS = {
    "dark": ["#f2f2f2", "#d2d2d2", "#b3b3b3", "#959595", "#787878", "#5f5f5f", "#4a4a4a", "#383838"],
    "light": ["#111111", "#2d2d2d", "#4a4a4a", "#686868", "#868686", "#a2a2a2", "#bbbbbb", "#cfcfcf"],
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
        releases { totalCount }
        url homepageUrl pushedAt isArchived
        latestRelease { tagName }
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
    return (f'<rect x="{x}" y="{y - 14}" width="4" height="18" rx="2" fill="{t["accent"]}"/>'
            f'<text x="{x + 14}" y="{y}" class="title">{escape(label)}</text>')


# ---------------------------------------------------------------- cartes

def neural_net(t, w, h):
    """Réseau de neurones décoratif : deux blocs de couches sur les côtés, impulsions animées."""
    rnd = random.Random(7)
    left_x, right_x = [60, 150, 240, 330], [870, 960, 1050, 1140]
    counts = [4, 5, 5, 4]

    def layer_nodes(xs):
        layers = []
        for x, n in zip(xs, counts):
            top, bottom = 38, h - 38
            step = (bottom - top) / (n - 1)
            layers.append([(x + rnd.uniform(-10, 10), top + i * step + rnd.uniform(-9, 9)) for i in range(n)])
        return layers

    edges, nodes, pulses = [], [], []
    for side, xs in (("l", left_x), ("r", right_x)):
        layers = layer_nodes(xs)
        for li, layer in enumerate(layers):
            for (x, y) in layer:
                nodes.append((x, y))
            if li + 1 < len(layers):
                for (x1, y1) in layer:
                    for (x2, y2) in layers[li + 1]:
                        edges.append((x1, y1, x2, y2))
    edge_svg = "".join(f'<line x1="{a:.0f}" y1="{b:.0f}" x2="{c:.0f}" y2="{d:.0f}"/>' for a, b, c, d in edges)
    colors = [t["a1"], t["a2"], t["a3"]]
    pulse_colors = [t["accent"], t["a2"], t["a3"]]
    for i, (a, b, c, d) in enumerate(rnd.sample(edges, 26)):
        col = pulse_colors[i % 3]
        dur = rnd.uniform(2.2, 4.2)
        begin = rnd.uniform(0, 4)
        pulses.append(
            f'<circle r="3" fill="{col}" opacity="0"><animateMotion dur="{dur:.1f}s" begin="{begin:.1f}s" repeatCount="indefinite" '
            f'path="M{a:.0f} {b:.0f} L{c:.0f} {d:.0f}"/><animate attributeName="opacity" values="0;1;1;0" '
            f'dur="{dur:.1f}s" begin="{begin:.1f}s" repeatCount="indefinite"/></circle>')
    node_svg = []
    for i, (x, y) in enumerate(nodes):
        col = colors[i % 3]
        node_svg.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="5" fill="{t["bg"]}" stroke="{col}" stroke-width="1.6">'
            f'<animate attributeName="stroke-opacity" values=".35;1;.35" dur="{rnd.uniform(3, 6):.1f}s" '
            f'begin="{rnd.uniform(0, 3):.1f}s" repeatCount="indefinite"/></circle>')
    return (f'<g stroke="{t["a1"]}" stroke-opacity=".16" stroke-width="1">{edge_svg}</g>'
            f'<g>{"".join(node_svg)}</g><g>{"".join(pulses)}</g>')


def header(t, name):
    w, h = 1200, 300
    grid = "".join(f'<path d="M{x} 0V{h}"/>' for x in range(0, w, 60)) + "".join(f'<path d="M0 {y}H{w}"/>' for y in range(0, h, 60))
    body = f"""
<defs><clipPath id="clip"><rect width="{w}" height="{h}" rx="14"/></clipPath></defs>
<style>
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
  .name {{ font-size: 84px; font-weight: 700; letter-spacing: -2px; }}
  .sub {{ font-size: 22px; font-weight: 400; }}
</style>
<g clip-path="url(#clip)">
  <g stroke="{t['text']}" stroke-opacity=".05">{grid}</g>
  {neural_net(t, w, h)}
</g>
<text x="600" y="76" text-anchor="middle" class="mono muted fade" font-size="16"><tspan fill="{t['accent']}">❯</tspan> whoami</text>
<text x="600" y="164" text-anchor="middle" class="name fade" style="animation-delay:.15s">{escape(name)}</text>
<text x="600" y="210" text-anchor="middle" class="sub muted fade" style="animation-delay:.35s">développeur full-stack · FiveM · Roblox · agents IA</text>
<g class="fade" style="animation-delay:.55s">
  <text x="600" y="252" text-anchor="middle" class="mono muted" font-size="14">Claude Code · TypeScript · Lua · Swift<tspan fill="{t['accent']}" style="animation: blink 1s steps(1) infinite"> ▍</tspan></text>
</g>"""
    return svg(w, h, body, t, f"{name}, développeur full-stack")


def terminal_card(t):
    """Session de terminal animée : les lignes se tapent l'une après l'autre."""
    w = 820
    lines = [
        ("prompt", 'whoami'),
        ("out", "Chopa, étudiant en BUT Informatique."),
        ("out", "Je construis des agents IA : Diapason est mon premier projet du genre."),
        ("out", "Côté dev : FiveM / GTA RP, jeux Roblox, bots Discord et SaaS en TypeScript."),
        ("out", "En ce moment : IA en direct, une IA qui apprend seule à conduire."),
    ]
    cw, x0, y0, lh = 9.2, 28, 92, 30
    body, begin = [], 0.15
    defs = []
    for i, (kind, text) in enumerate(lines):
        y = y0 + i * lh
        n = len(text)
        dur = max(0.3, n * 0.011)
        values = ";".join(f"{(k * cw + 26):.0f}" for k in range(n + 1))
        defs.append(
            f'<clipPath id="c{i}"><rect x="{x0 - 4}" y="{y - 18}" width="0" height="26">'
            f'<animate attributeName="width" values="{values}" dur="{dur:.2f}s" begin="{begin:.2f}s" '
            f'calcMode="discrete" fill="freeze"/></rect></clipPath>')
        if kind == "prompt":
            glyph = f'<text x="{x0}" y="{y}" font-size="15" class="mono" fill="{t["accent"]}">❯</text>'
            txt = f'<text x="{x0 + 20}" y="{y}" font-size="15" class="mono" xml:space="preserve">{escape(text)}</text>'
        else:
            glyph = f'<text x="{x0}" y="{y}" font-size="15" class="mono" fill="{t["muted"]}">●</text>'
            txt = f'<text x="{x0 + 20}" y="{y}" font-size="15" class="mono">{escape(text)}</text>'
        body.append(f'<g clip-path="url(#c{i})">{glyph}{txt}</g>')
        begin += dur + (0.25 if kind == "prompt" else 0.1)
    h = y0 + len(lines) * lh + 24
    cursor_y = y0 + len(lines) * lh
    body.append(f'<g opacity="0"><animate attributeName="opacity" values="0;1" dur="0.01s" begin="{begin:.2f}s" fill="freeze"/>'
                f'<text x="{x0}" y="{cursor_y}" font-size="15" class="mono" fill="{t["accent"]}">❯</text>'
                f'<rect x="{x0 + 20}" y="{cursor_y - 14}" width="9" height="18" fill="{t["accent"]}" style="animation: blink 1s steps(1) infinite"/></g>')
    chrome = (f'<rect x=".5" y=".5" width="{w - 1}" height="40" rx="14" fill="{t["bg2"]}"/>'
              f'<rect x=".5" y="26" width="{w - 1}" height="15" fill="{t["bg2"]}"/>'
              f'<path d="M.5 41H{w - .5}" stroke="{t["border"]}"/>'
              f'<circle cx="26" cy="21" r="5" fill="{t["border"]}"/><circle cx="44" cy="21" r="5" fill="{t["border"]}"/>'
              f'<circle cx="62" cy="21" r="5" fill="{t["border"]}"/>'
              f'<text x="{w / 2}" y="26" text-anchor="middle" class="mono muted" font-size="13">chopa — zsh</text>')
    style = '<style>@keyframes blink { 50% { opacity: 0; } }</style>'
    inner = f'{style}<defs>{"".join(defs)}</defs>{chrome}' + "".join(body)
    return svg(w, h, inner, t, "À propos de Chopa : étudiant en BUT Informatique, jeux, bots et agents IA")


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
        ("repo", "Versions publiées", fmt(sum(r["releases"]["totalCount"] for r in user["repos"] if not r["isPrivate"] and not r["isFork"]))),
        ("star", "Étoiles reçues", fmt(sum(r["stargazerCount"] for r in user["repos"] if not r["isPrivate"] and not r["isFork"]))),
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


# ---------------------------------------------------------------- projets (cartes + bloc du README)

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARK_A, MARK_B = "<!-- PROJETS:DEBUT -->", "<!-- PROJETS:FIN -->"
MAX_VISIBLE = 8


def load_config():
    p = ROOT / "projects.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def collect_projects(user, cfg):
    """Dépôts publics (sauf forks, archivés, cachés) + projets sans lien, dans l'ordre voulu."""
    hide = set(cfg.get("cacher", []))
    tweaks = cfg.get("retouches", {})
    pool = {}
    for r in user["repos"]:
        if r["isPrivate"] or r["isFork"] or r["isArchived"] or r["name"] in hide:
            continue
        tw = tweaks.get(r["name"], {})
        pool[r["name"]] = dict(
            name=r["name"], url=r["url"], desc=tw.get("desc") or r["description"] or "",
            lang=(r["primaryLanguage"] or {}).get("name", ""), stars=r["stargazerCount"],
            tag=(r["latestRelease"] or {}).get("tagName", ""), demo=r["homepageUrl"] or "",
            pushed=r["pushedAt"], capture=tw.get("capture", ""), ancrage=tw.get("ancrage", "Min"), visuel=tw.get("visuel", ""), label="")
    ordered = []
    for n in cfg.get("a_la_une", []) + cfg.get("ordre", []):
        if n in pool and pool[n] not in ordered:
            ordered.append(pool[n])
    if cfg.get("auto_decouverte", True):
        ordered += sorted((p for p in pool.values() if p not in ordered), key=lambda p: p["pushed"], reverse=True)
    for x in cfg.get("sans_lien", []):
        ordered.append(dict(name=x["nom"], url="", desc=x["desc"], lang=x.get("langage", ""), stars=0,
                            tag="", demo="", pushed="", capture="", ancrage="Min", visuel=x.get("visuel", ""), label=x.get("etiquette", "")))
    featured = set(cfg.get("a_la_une", []))
    for p in ordered:
        p["featured"] = bool(p["capture"] or p["visuel"])
    return ordered


def slug(name):
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


def schema_visual(t, w, h):
    """Schéma de fonctionnement de Diapason (dessiné, pas une capture) : idée → cadrage → Diapason → agents → vérification → passation."""
    y, bw, bh = h // 2, 74, 34
    xs = [18, 98, 178]
    out = [f'<rect width="{w}" height="{h}" fill="{t["bg2"]}"/>']
    labels = ["Idée", "Cadrage", "Diapason"]
    for i, x in enumerate(xs):
        acc = i == 2
        out.append(f'<rect x="{x}" y="{y - bh // 2}" width="{bw - 6}" height="{bh}" rx="5" fill="{t["accent"] if acc else "none"}" stroke="{t["accent"] if acc else t["border"]}"/>'
                   f'<text x="{x + (bw - 6) / 2}" y="{y + 4}" font-size="11.5" text-anchor="middle" fill="{t["bg"] if acc else t["text"]}" font-weight="{700 if acc else 400}">{labels[i]}</text>')
        if i < 2:
            out.append(f'<path d="M{x + bw - 6} {y}h12" stroke="{t["muted"]}"/>')
    # cinq agents
    ax = 270
    for k, name in enumerate(["chercheur", "concepteur", "exécutant", "testeur", "auditeur"]):
        ay = y - 52 + k * 26
        out.append(f'<path d="M{xs[2] + bw - 6} {y}L{ax} {ay}" stroke="{t["border"]}"/>'
                   f'<rect x="{ax}" y="{ay - 10}" width="74" height="20" rx="4" fill="none" stroke="{t["border"]}"/>'
                   f'<text x="{ax + 37}" y="{ay + 4}" font-size="10" text-anchor="middle" fill="{t["muted"]}">{name}</text>')
    out.append(f'<path d="M{ax + 74} {y}h14" stroke="{t["muted"]}"/>'
               f'<rect x="{ax + 88}" y="{y - bh // 2}" width="40" height="{bh}" rx="5" fill="none" stroke="{t["border"]}"/>'
               f'<text x="{ax + 108}" y="{y + 4}" font-size="10" text-anchor="middle" fill="{t["text"]}">✓</text>')
    return "".join(out)


def lyra_visual(t, w, h):
    """Fenêtre de paroles flottante (dessinée, textes inventés) : ligne précédente, ligne en cours, ligne suivante, progression, commandes."""
    cx, wx, wy, ww, wh = w / 2, 62, 24, w - 124, 104
    return (f'<rect width="{w}" height="{h}" fill="{t["bg2"]}"/>'
            f'<rect x="{wx}" y="{wy}" width="{ww}" height="{wh}" rx="16" fill="{t["bg"]}" stroke="{t["border"]}"/>'
            f'<text x="{cx}" y="{wy + 30}" font-size="11.5" text-anchor="middle" fill="{t["muted"]}" opacity=".55">chaque ligne glisse à sa place</text>'
            f'<text x="{cx}" y="{wy + 58}" font-size="16.5" font-weight="700" text-anchor="middle" fill="{t["text"]}">la ligne en cours s\'allume</text>'
            f'<text x="{cx}" y="{wy + 84}" font-size="11.5" text-anchor="middle" fill="{t["muted"]}" opacity=".55">synchronisée sur le morceau</text>'
            f'<rect x="{wx + 28}" y="{wy + wh - 11}" width="{ww - 56}" height="2.5" rx="1.2" fill="{t["border"]}"/>'
            f'<rect x="{wx + 28}" y="{wy + wh - 11}" width="{(ww - 56) * .42:.1f}" height="2.5" rx="1.2" fill="{t["accent"]}"/>'
            f'<g fill="{t["muted"]}" transform="translate({cx} {wy + wh + 24})"><path d="M-30 -6l-9 6 9 6z"/><rect x="-5" y="-6" width="3.5" height="12" rx="1"/>'
            f'<rect x="1.5" y="-6" width="3.5" height="12" rx="1"/><path d="M30 -6l9 6-9 6z"/></g>')


def kashmo_visual(t, w, h):
    """Bot Discord + jeu de cartes (dessiné) : fil de messages avec une commande, et trois cartes en éventail."""
    out = [f'<rect width="{w}" height="{h}" fill="{t["bg2"]}"/>']
    for i, (bar1, bar2, cmd) in enumerate([(110, 70, False), (130, 0, True), (90, 120, False)]):
        y = 34 + i * 42
        out.append(f'<circle cx="34" cy="{y}" r="11" fill="none" stroke="{t["border"]}"/><circle cx="34" cy="{y}" r="4" fill="{t["accent"] if cmd else t["muted"]}"/>')
        if cmd:
            out.append(f'<rect x="56" y="{y - 11}" width="108" height="22" rx="5" fill="none" stroke="{t["accent"]}"/>'
                       f'<text x="110" y="{y + 4}" font-size="11.5" class="mono" text-anchor="middle" fill="{t["accent"]}">/ticket ouvrir</text>')
        else:
            out.append(f'<rect x="56" y="{y - 9}" width="{bar1}" height="5" rx="2.5" fill="{t["muted"]}" opacity=".55"/>')
            if bar2:
                out.append(f'<rect x="56" y="{y + 2}" width="{bar2}" height="5" rx="2.5" fill="{t["border"]}"/>')
    for k, (ang, dx, hi) in enumerate([(-14, -52, False), (14, 52, False), (0, 0, True)]):
        cx, cy = 300 + dx * .9, 88
        out.append(f'<g transform="translate({cx} {cy}) rotate({ang})">'
                   f'<rect x="-34" y="-50" width="68" height="100" rx="7" fill="{t["bg"]}" stroke="{t["accent"] if hi else t["border"]}" stroke-width="{1.4 if hi else 1}"/>'
                   f'<circle cx="0" cy="-12" r="14" fill="none" stroke="{t["muted"]}" opacity=".6"/><circle cx="0" cy="-12" r="4" fill="{t["accent"] if hi else t["muted"]}"/>'
                   f'<rect x="-22" y="14" width="44" height="4" rx="2" fill="{t["border"]}"/><rect x="-22" y="24" width="30" height="4" rx="2" fill="{t["border"]}"/></g>')
    return "".join(out)


def ia_visual(t, w, h):
    """Circuit 2D vu de dessus (le vrai tracé du projet), voiture orange avec ses rayons, et la courbe du meilleur tour qui descend."""
    ctrl = [(120, 123), (424, 62), (748, 56), (854, 201), (840, 298), (847, 431), (602, 504), (371, 389), (245, 474), (80, 389), (60, 244)]
    sc, ox, oy = 0.34, 12, 6
    pts = [(ox + (x - 55) * sc, oy + (y - 50) * sc + 6) for x, y in ctrl]
    n = len(pts)
    d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
    segs = []
    for i in range(n):
        p0, p1, p2, p3 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}"
        segs.append((p1, c1, c2, p2))
    def at(i, u):
        p1, c1, c2, p2 = segs[i]; m = 1 - u
        x = m**3 * p1[0] + 3 * m * m * u * c1[0] + 3 * m * u * u * c2[0] + u**3 * p2[0]
        y = m**3 * p1[1] + 3 * m * m * u * c1[1] + 3 * m * u * u * c2[1] + u**3 * p2[1]
        return x, y
    (x0, y0), (x1, y1) = at(1, 0.5), at(1, 0.56)
    ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
    rays = "".join(f'<line x1="0" y1="0" x2="{34 * math.cos(math.radians(a)):.1f}" y2="{34 * math.sin(math.radians(a)):.1f}" stroke="{t["muted"]}" stroke-width=".9" opacity=".7"/>' for a in (-60, -30, 0, 30, 60))
    gx, gy = at(8, 0.4)
    spark = "M" + " L".join(f"{318 + i * 3.6:.1f} {44 + 66 * (1 - math.exp(-i / 7)):.1f}" for i in range(21))
    return (f'<rect width="{w}" height="{h}" fill="{t["bg2"]}"/>'
            f'<path d="{d}Z" fill="none" stroke="{t["border"]}" stroke-width="11" stroke-linejoin="round"/>'
            f'<path d="{d}Z" fill="none" stroke="{t["muted"]}" stroke-width="1" stroke-dasharray="4 5" opacity=".5"/>'
            f'<circle cx="{gx:.1f}" cy="{gy:.1f}" r="3.6" fill="{t["muted"]}" opacity=".7"/>'
            f'<g transform="translate({x0:.1f} {y0:.1f}) rotate({ang:.1f})">{rays}<rect x="-6" y="-3.4" width="12" height="6.8" rx="2" fill="{t["accent"]}"/></g>'
            f'<text x="318" y="30" font-size="9.5" class="mono" fill="{t["muted"]}">meilleur tour</text>'
            f'<path d="M318 40V118H394" fill="none" stroke="{t["border"]}"/>'
            f'<path d="{spark}" fill="none" stroke="{t["accent"]}" stroke-width="1.8" stroke-linecap="round"/>')


def _mix(a, b, k):
    """Mélange deux couleurs #rrggbb (k = part de b)."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * k):02x}" for x, y in zip(pa, pb))


def huezz_visual(t, w, h):
    """Palette de 7 rôles en gris avec un seul accent, deux maquettes filaires et une pastille de contraste (dessiné)."""
    out = [f'<rect width="{w}" height="{h}" fill="{t["bg2"]}"/>']
    for i in range(7):
        col = t["accent"] if i == 3 else _mix(t["text"], t["bg"], i / 6 * 0.92)
        out.append(f'<rect x="{26 + i * 26}" y="24" width="20" height="98" rx="5" fill="{col}"/>')
    out.append(f'<text x="26" y="144" font-size="10.5" class="mono" fill="{t["muted"]}">oklch(0.64 0.19 45)</text>')
    out.append(f'<rect x="218" y="26" width="118" height="80" rx="7" fill="{t["bg"]}" stroke="{t["border"]}"/>'
               f'<path d="M218 40H336" stroke="{t["border"]}"/>'
               f'<circle cx="228" cy="33" r="2" fill="{t["muted"]}"/><circle cx="236" cy="33" r="2" fill="{t["muted"]}"/>'
               f'<rect x="230" y="52" width="62" height="7" rx="3.5" fill="{t["text"]}" opacity=".85"/>'
               f'<rect x="230" y="66" width="86" height="4" rx="2" fill="{t["border"]}"/><rect x="230" y="75" width="70" height="4" rx="2" fill="{t["border"]}"/>'
               f'<rect x="230" y="87" width="34" height="11" rx="5.5" fill="{t["accent"]}"/>')
    out.append(f'<rect x="348" y="38" width="36" height="68" rx="9" fill="{t["bg"]}" stroke="{t["border"]}"/>'
               f'<rect x="355" y="50" width="22" height="5" rx="2.5" fill="{t["text"]}" opacity=".8"/><rect x="355" y="61" width="22" height="3" rx="1.5" fill="{t["border"]}"/>'
               f'<rect x="355" y="68" width="16" height="3" rx="1.5" fill="{t["border"]}"/><rect x="355" y="90" width="22" height="8" rx="4" fill="{t["accent"]}"/>')
    out.append(f'<rect x="218" y="120" width="76" height="22" rx="11" fill="none" stroke="{t["accent"]}"/>'
               f'<text x="256" y="135" font-size="11" class="mono" text-anchor="middle" fill="{t["accent"]}">AA 7,2:1 ✓</text>')
    return "".join(out)


def sumi_visual(t, w, h):
    """Jardin d'encre : bambous à la ligne, soleil orange, lavis gris (dessiné)."""
    out = [f'<rect width="{w}" height="{h}" fill="{t["bg2"]}"/>',
           f'<path d="M0 142Q70 122 150 140T300 134T400 144V{h}H0Z" fill="{t["muted"]}" opacity=".14"/>',
           f'<path d="M0 154Q90 140 190 152T400 150V{h}H0Z" fill="{t["muted"]}" opacity=".16"/>',
           f'<circle cx="318" cy="52" r="17" fill="{t["accent"]}" opacity=".92"/>']
    stalks = [(92, 18, 6.0, .9), (132, 44, 5.0, .65), (176, 64, 4.0, .45)]
    for x, top, sw, op in stalks:
        out.append(f'<path d="M{x} 156V{top}" stroke="{t["text"]}" stroke-width="{sw}" stroke-linecap="round" opacity="{op}"/>')
        y = 150
        while y > top + 14:
            out.append(f'<path d="M{x - sw / 2 - 1.5} {y}h{sw + 3}" stroke="{t["bg2"]}" stroke-width="1.6" opacity=".9"/>')
            y -= 26
        for k, (dy, side) in enumerate([(top + 22, 1), (top + 50, -1), (top + 80, 1)]):
            if dy > 140:
                continue
            ln = 34 - k * 4
            out.append(f'<path d="M{x} {dy}q{side * ln * .55} {-9 - k * 2} {side * ln} {5}q{-side * ln * .5} {-1} {-side * ln} {-5}z" fill="{t["text"]}" opacity="{op * .8:.2f}"/>')
    for cx, cy, r in ((236, 96, 1.6), (262, 118, 1.2), (214, 128, 1.4), (286, 104, 1.2)):
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{t["muted"]}" opacity=".7"/>')
    return "".join(out)


def draw_visual(t, kind, w, h):
    return {"schema": schema_visual, "lyra": lyra_visual, "kashmo": kashmo_visual, "ia": ia_visual, "huezz": huezz_visual, "sumi": sumi_visual}[kind](t, w, h)


def project_card(t, p):
    w = 400
    thumb_h = 170 if p["featured"] else 0
    h = thumb_h + 150
    lines = textwrap.wrap(p["desc"], 46)[:3]
    body, top = [], thumb_h
    if thumb_h and p["visuel"]:
        body.append(f'<clipPath id="th"><path d="M0 14a14 14 0 0 1 14-14h{w - 28}a14 14 0 0 1 14 14V{thumb_h}H0Z"/></clipPath>'
                    f'<g clip-path="url(#th)">{draw_visual(t, p["visuel"], w, thumb_h)}</g><path d="M0 {thumb_h}H{w}" stroke="{t["border"]}"/>')
    elif thumb_h:
        data = base64.b64encode((ROOT / p["capture"]).read_bytes()).decode()
        body.append(f'<clipPath id="th"><path d="M0 14a14 14 0 0 1 14-14h{w - 28}a14 14 0 0 1 14 14V{thumb_h}H0Z"/></clipPath>'
                    f'<image href="data:image/jpeg;base64,{data}" x="0" y="0" width="{w}" height="{thumb_h}" '
                    f'preserveAspectRatio="xMidY{p["ancrage"]} slice" clip-path="url(#th)"/>'
                    f'<path d="M0 {thumb_h}H{w}" stroke="{t["border"]}"/>')
    body.append(icon("repo", 22, top + 20, t["muted"]))
    body.append(f'<text x="46" y="{top + 33}" font-size="16" font-weight="700">{escape(p["name"])}</text>')
    badge = p["label"] or p["tag"]
    if badge:
        body.append(f'<text x="{w - 20}" y="{top + 33}" font-size="12" class="mono muted" text-anchor="end">{escape(badge)}</text>')
    for i, line in enumerate(lines):
        body.append(f'<text x="22" y="{top + 62 + i * 19}" font-size="13" class="muted">{escape(line)}</text>')
    y = top + 134
    if p["lang"]:
        body.append(f'<circle cx="28" cy="{y - 4}" r="5" fill="{t["muted"]}"/><text x="42" y="{y}" font-size="12.5">{escape(p["lang"])}</text>')
    if p["stars"]:
        body.append(f'{icon("star", 150, y - 12, t["muted"])}<text x="172" y="{y}" font-size="12.5" class="muted">{p["stars"]}</text>')
    if p["demo"]:
        body.append(f'<text x="{w - 20}" y="{y}" font-size="12" class="mono" fill="{t["accent"]}" text-anchor="end">démo en ligne ↗</text>')
    return svg(w, h, "\n".join(body), t, p["name"])


def write_projects(projects):
    out = OUT / "projets"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.svg"):
        old.unlink()
    for theme, t in THEMES.items():
        for p in projects:
            (out / f"{slug(p['name'])}-{theme}.svg").write_text(project_card(t, p), encoding="utf-8")


def projects_block(projects):
    def one(p):
        pic = (f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/projets/{slug(p["name"])}-dark.svg">'
               f'<img alt="{escape(p["name"])} : {escape(p["desc"][:80])}" src="assets/projets/{slug(p["name"])}-light.svg" width="49%"></picture>')
        return f'<a href="{p["url"]}">{pic}</a>' if p["url"] else pic
    visible, more = projects[:MAX_VISIBLE], projects[MAX_VISIBLE:]
    html = '<p align="center">\n  ' + "\n  ".join(one(p) for p in visible) + "\n</p>"
    if more:
        html += ('\n\n<details>\n<summary>Tous les projets (' + str(len(projects)) + ')</summary>\n\n<p align="center">\n  '
                 + "\n  ".join(one(p) for p in more) + "\n</p>\n\n</details>")
    return html


def update_readme(projects):
    p = ROOT / "README.md"
    s = p.read_text(encoding="utf-8")
    if MARK_A not in s or MARK_B not in s:
        print("README : repères PROJETS absents, bloc non mis à jour")
        return
    a, b = s.index(MARK_A) + len(MARK_A), s.index(MARK_B)
    p.write_text(s[:a] + "\n" + projects_block(projects) + "\n" + s[b:], encoding="utf-8")


# ---------------------------------------------------------------- main

def main():
    user = fetch()
    langs = languages(user["repos"])
    OUT.mkdir(exist_ok=True)
    for theme, t in THEMES.items():
        grays = GRAYS[theme]
        langs_theme = [(n, p, grays[i % len(grays)]) for i, (n, p, _) in enumerate(langs)]
        files = {
            f"header-{theme}.svg": header(t, DISPLAY_NAME),
            f"about-{theme}.svg": terminal_card(t),
            f"stats-{theme}.svg": stats_card(t, user),
            f"langs-{theme}.svg": langs_card(t, langs_theme),
        }
        for fname, content in files.items():
            (OUT / fname).write_text(content, encoding="utf-8")
    cfg = load_config()
    projects = collect_projects(user, cfg)
    write_projects(projects)
    update_readme(projects)
    print(f"{len(THEMES)} thèmes générés dans {OUT} — langages : "
          + ", ".join(f"{n} {p:.0f}%" for n, p, _ in langs))


if __name__ == "__main__":
    main()
