<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/header-dark.svg">
  <img alt="Chopa, développeur full-stack : FiveM, Roblox, agents IA" src="assets/header-light.svg" width="100%">
</picture>

## À propos

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/about-dark.svg">
    <img alt="Chopa : étudiant en BUT Informatique, jeux, bots Discord et agents IA" src="assets/about-light.svg" width="820">
  </picture>
</p>

## Projets

<!-- PROJETS:DEBUT -->
<p align="center">
  <a href="https://github.com/MalikChopa/lullaby-lake"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/projets/lullaby-lake-dark.svg"><img alt="lullaby-lake : Jeu de pêche zen en HD-2D : des personnages en pixel art dans un petit monde en " src="assets/projets/lullaby-lake-light.svg" width="49%"></picture></a>
  <a href="https://github.com/MalikChopa/prismaze"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/projets/prismaze-dark.svg"><img alt="prismaze : Jeu de réflexion en labyrinthe de lasers : oriente les miroirs, sépare la lumièr" src="assets/projets/prismaze-light.svg" width="49%"></picture></a>
  <a href="https://github.com/MalikChopa/gloam"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/projets/gloam-dark.svg"><img alt="gloam : Jeu d&#x27;adresse de nuit : guide un essaim de lucioles à travers les ronces, frôle " src="assets/projets/gloam-light.svg" width="49%"></picture></a>
  <a href="https://github.com/MalikChopa/sumi-niwa"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/projets/sumi-niwa-dark.svg"><img alt="sumi-niwa : Jardin d&#x27;encre génératif en WebGPU : tu plantes, tu souffles, les saisons passen" src="assets/projets/sumi-niwa-light.svg" width="49%"></picture></a>
  <a href="https://github.com/MalikChopa/huezz"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/projets/huezz-dark.svg"><img alt="huezz : Générateur de palettes OKLCH : une couleur de base, 7 rôles, aperçu sur trois ma" src="assets/projets/huezz-light.svg" width="49%"></picture></a>
  <a href="https://github.com/MalikChopa/diapason"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/projets/diapason-dark.svg"><img alt="diapason : Skill Claude Code : ton projet mené par une équipe de sous-agents. Tu décides, e" src="assets/projets/diapason-light.svg" width="49%"></picture></a>
  <a href="https://github.com/MalikChopa/lyra-lyrics"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/projets/lyra-lyrics-dark.svg"><img alt="lyra-lyrics : App macOS : paroles synchronisées toujours au premier plan pour Spotify et Apple" src="assets/projets/lyra-lyrics-light.svg" width="49%"></picture></a>
  <picture><source media="(prefers-color-scheme: dark)" srcset="assets/projets/kashmo-dark.svg"><img alt="Kashmo : Plateforme Discord complète : bot, tableau de bord multi-serveur et jeu de carte" src="assets/projets/kashmo-light.svg" width="49%"></picture>
</p>

<p align="center"><sub><b>À essayer :</b> <a href="https://malikchopa.github.io/lullaby-lake/">lullaby-lake</a> · <a href="https://malikchopa.github.io/prismaze/">prismaze</a> · <a href="https://malikchopa.github.io/gloam/">gloam</a> · <a href="https://MalikChopa.github.io/sumi-niwa/">sumi-niwa</a> · <a href="https://malikchopa.github.io/huezz/">huezz</a></sub></p>
<!-- PROJETS:FIN -->

<details>
<summary>Comment fonctionne Diapason</summary>

```mermaid
%%{init: {'theme':'base','themeVariables':{'fontFamily':'ui-sans-serif, system-ui','lineColor':'#8c8c8c','primaryColor':'#1a1a1a','primaryTextColor':'#f2f2f2','primaryBorderColor':'#8c8c8c'}}}%%
flowchart LR
    A(["Une idée"]) --> B["Cadrage<br/>fiche à valider"]
    B --> C["Diapason<br/>découpe et délègue"]
    C --> D1["Chercheur"]
    C --> D2["Concepteur"]
    C --> D3["Exécutant"]
    C --> D4["Testeur"]
    C --> D5["Auditeur"]
    D1 --> E{"Vérification<br/>faite par Diapason"}
    D2 --> E
    D3 --> E
    D4 --> E
    D5 --> E
    E --> F["HANDOFF.md<br/>reprise possible"]
    E -.-> C

    classDef lead fill:#ea580c,stroke:#ea580c,color:#0a0a0a,font-weight:bold
    classDef agent fill:#1a1a1a,stroke:#8c8c8c,color:#f2f2f2
    classDef gate fill:#262626,stroke:#c4c4c4,color:#f2f2f2
    class C lead
    class D1,D2,D3,D4,D5 agent
    class E,F gate
```

</details>

<!-- sol-0:start -->
## Sol-0

Un rover simulé qui apprend seul à exister sur une planète procédurale.

A simulated rover that learns on its own to exist on a procedural planet.

<details>
<summary>Watch the trailer · Voir la bande-annonce (39 s)</summary>

<img src="assets/trailer.gif" width="640" alt="Bande-annonce illustrée de Sol-0 (illustration, pas des données de la simulation) : le ciel devient un cerveau, une roue tourne, titre SOL-0 / Illustrated Sol-0 trailer (an illustration, not simulation data): the sky becomes a brain, a wheel turns, SOL-0 title">

</details>

[▶ Voir en direct · Watch live](https://sol0.fr/)

<img src="https://raw.githubusercontent.com/MalikChopa/MalikChopa/state/console.gif" width="640" alt="Console de Sol-0 : caméra CAM-1, cerveau en fonctionnement, carte locale et télémétrie du dernier sol / Sol-0 console: CAM-1 camera, live brain, local map and telemetry of the last sol">

<img src="https://raw.githubusercontent.com/MalikChopa/MalikChopa/state/status.svg" width="640" alt="Statut de Sol-0 : sol, stade, progression mesurée / Sol-0 status: sol, stage, measured progress">

<a href="https://raw.githubusercontent.com/MalikChopa/MalikChopa/state/map.png"><img src="https://raw.githubusercontent.com/MalikChopa/MalikChopa/state/map.png" width="640" alt="Carte explorée par Sol-0 avec brouillard / Map explored by Sol-0 with fog of war"></a>

[Journal](journal/README.md) · [Atlas](atlas/README.md) · [Premières fois / Firsts](firsts/README.md) · [Comment ça marche](pages/how-it-works.fr.md) · [How it works](pages/how-it-works.en.md)

Sol-0 vit en continu sur un serveur, un sol toutes les 15 minutes ; ces images rejouent un sol récent (de moins de 6 heures). Tout ce qui est affiché vient du calcul réel.

Sol-0 lives continuously on a server, one sol every 15 minutes; these images replay a recent sol (less than 6 hours old). Everything shown comes from the actual computation.
<!-- sol-0:end -->

## Stack

| | |
|---|---|
| **Le plus utilisé** | TypeScript · JavaScript · Node.js · React · Next.js · Tailwind CSS · Vite · Fastify · Lua (FiveM) · Luau (Roblox) · Claude Code |
| **Aussi pratiqué** | Swift · Python · Three.js · WebGL · WebGPU · Vue · Astro · discord.js · Prisma · MongoDB · SQLite · Git · GitHub Actions |
| **Vu en cours ou en petit projet** | Java · Spring · PostgreSQL · Docker · Kotlin · Dart et Flutter · C# |

<sub>Classé d'après ce que contiennent mes dépôts, publics et privés.</sub>

## En chiffres

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/stats-dark.svg">
    <img alt="Statistiques GitHub" src="assets/stats-light.svg" width="500">
  </picture>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/langs-dark.svg">
    <img alt="Langages les plus utilisés" src="assets/langs-light.svg" width="500">
  </picture>
</p>

<p align="center"><sub>Commits et contributions : tous dépôts, privés compris · versions, étoiles et langages : dépôts publics seulement · mis à jour chaque jour par GitHub Actions</sub></p>

## En coulisses (dépôts privés)

| | |
|---|---|
| FiveM / GTA RP | Scripts Lua sur mesure (customs, recoil, médias) et outils pour serveurs RP |
| Roblox | Jeux en Luau, en solo et en équipe |
| Bots Discord et SaaS | Next.js, Fastify, Stripe, MongoDB, Socket.io |
| Mobile | Flutter, Kotlin |

## Contributions

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/MalikChopa/MalikChopa/output/snake-dark.svg">
  <img alt="Un serpent qui mange le graphe de contributions" src="https://raw.githubusercontent.com/MalikChopa/MalikChopa/output/snake-light.svg" width="100%">
</picture>

## Contact

<p align="center">
  <img alt="Discord : chp.a" src="https://img.shields.io/badge/Discord-chp.a-111111?style=for-the-badge&logo=discord&logoColor=white&labelColor=3a3a3a">
</p>
