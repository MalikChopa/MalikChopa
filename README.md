<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/header-dark.svg">
  <img alt="Malik Moussaoui aka Chopa — développeur full-stack et créateur de jeux" src="assets/header-light.svg" width="100%">
</picture>

<p align="center">
  <img alt="Ce que je fais" src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=22&duration=2600&pause=900&color=FB923C&center=true&vCenter=true&width=720&lines=Mon%20premier%20projet%20d%27agents%20%3A%20Diapason;Lyra%20Lyrics%20%3A%20les%20paroles%20de%20ta%20musique%20sur%20Mac;En%20ce%20moment%20%3A%20IA%20en%20direct;Dev%20FiveM%20%2F%20Roblox%20%2F%20bots%20Discord%20%2F%20SaaS;%C3%89tudiant%20en%20BUT%20Informatique">
</p>

<p align="center">
  <a href="https://github.com/MalikMoussaoui?tab=followers"><img alt="Abonnés" src="https://img.shields.io/github/followers/MalikMoussaoui?label=abonn%C3%A9s&style=for-the-badge&logo=github&color=8b5cf6&labelColor=1a1226"></a>
  <img alt="Vues du profil" src="https://hits.sh/github.com/MalikMoussaoui.svg?style=for-the-badge&label=vues&color=fb923c&labelColor=1a1226">
  <a href="https://github.com/MalikMoussaoui/diapason"><img alt="Étoiles de Diapason" src="https://img.shields.io/github/stars/MalikMoussaoui/diapason?label=Diapason&style=for-the-badge&logo=claude&logoColor=white&color=fb7185&labelColor=1a1226"></a>
</p>

## 🧑‍💻 À propos

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/about-dark.svg">
    <img alt="Malik « Chopa » Moussaoui : étudiant en BUT Informatique, je construis des agents IA et j'apprends à une IA à conduire" src="assets/about-light.svg" width="820">
  </picture>
</p>

## 🤖 Mon virage IA

| | |
|---|---|
| 🧠 **Mon premier projet d'agents** | [`Diapason`](https://github.com/MalikMoussaoui/diapason) (version 1.7) : un skill Claude Code qui cadre le projet avec toi, confie le travail à des sous-agents, vérifie lui-même les faits décisifs et laisse une passation reprenable |
| 📡 **IA en direct** | En cours : des IA qui apprennent seules à conduire et à faire la course sur un circuit 2D (apprentissage par renforcement), avec une page web pour suivre leurs progrès en quasi-direct. Le dépôt arrive bientôt |

Comment fonctionne Diapason, en une image :

```mermaid
%%{init: {'theme':'base','themeVariables':{'fontFamily':'ui-sans-serif, system-ui','lineColor':'#fb923c','primaryColor':'#2a1f38','primaryTextColor':'#f3eefa','primaryBorderColor':'#a78bfa'}}}%%
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

    classDef master fill:#fb923c,stroke:#fb923c,color:#1a1226,font-weight:bold
    classDef agent fill:#2a1f38,stroke:#a78bfa,color:#f3eefa
    classDef gate fill:#33243f,stroke:#fb7185,color:#f3eefa
    class C master
    class D1,D2,D3,D4,D5 agent
    class E,F gate
```

## 🛠️ Stack

<p align="center"><sub><b>IA</b></sub><br>
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude_Code-D97757?style=for-the-badge&logo=claude&logoColor=white">
  <img alt="Anthropic" src="https://img.shields.io/badge/Anthropic-191919?style=for-the-badge&logo=anthropic&logoColor=white">
  <a href="https://github.com/MalikMoussaoui/diapason"><img alt="Diapason" src="https://img.shields.io/badge/Diapason-fb923c?style=for-the-badge&logo=github&logoColor=white"></a>
</p>

<p align="center"><sub><b>LANGAGES</b></sub><br>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://skillicons.dev/icons?i=typescript%2Cjavascript%2Clua%2Cpython%2Cjava%2Ckotlin%2Cdart%2Cswift%2Ccs%2Cbash&theme=dark">
    <img alt="TypeScript, JavaScript, Lua, Python, Java, Kotlin, Dart, Swift, C#, Bash" src="https://skillicons.dev/icons?i=typescript,javascript,lua,python,java,kotlin,dart,swift,cs,bash&theme=light">
  </picture>
</p>

<p align="center"><sub><b>FRONT</b></sub><br>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://skillicons.dev/icons?i=react%2Cnextjs%2Cvuejs%2Castro%2Ctailwindcss%2Cthreejs%2Cvite%2Cflutter%2Chtml%2Ccss&theme=dark">
    <img alt="React, Next.js, Vue, Astro, Tailwind CSS, Three.js, Vite, Flutter, HTML, CSS" src="https://skillicons.dev/icons?i=react,nextjs,vuejs,astro,tailwindcss,threejs,vite,flutter,html,css&theme=light">
  </picture>
</p>

<p align="center"><sub><b>BACK</b></sub><br>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://skillicons.dev/icons?i=nodejs%2Cdiscordjs%2Cprisma%2Cmongodb%2Cpostgresql%2Csqlite%2Cspring%2Cdocker%2Cnginx&theme=dark">
    <img alt="Node.js, discord.js, Prisma, MongoDB, PostgreSQL, SQLite, Spring, Docker, Nginx" src="https://skillicons.dev/icons?i=nodejs,discordjs,prisma,mongodb,postgresql,sqlite,spring,docker,nginx&theme=light">
  </picture>
</p>

<p align="center"><sub><b>JEUX &amp; OUTILS</b></sub><br>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://skillicons.dev/icons?i=robloxstudio%2Cgit%2Cgithub%2Cgithubactions%2Cvscode%2Cpnpm&theme=dark">
    <img alt="Roblox Studio, Git, GitHub, GitHub Actions, VS Code, pnpm" src="https://skillicons.dev/icons?i=robloxstudio,git,github,githubactions,vscode,pnpm&theme=light">
  </picture><br>
  <img alt="FiveM" src="https://img.shields.io/badge/FiveM-F40552?style=for-the-badge&logo=fivem&logoColor=white">
</p>

## 📊 En chiffres

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/stats-dark.svg">
    <img alt="Statistiques GitHub" src="assets/stats-light.svg" width="49%">
  </picture>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/langs-dark.svg">
    <img alt="Langages les plus utilisés" src="assets/langs-light.svg" width="49%">
  </picture>
</p>

<p align="center"><sub>Dépôts publics et privés · mis à jour chaque jour par GitHub Actions</sub></p>

## 🚀 Projets à la une

<p align="center">
  <a href="https://github.com/MalikMoussaoui/diapason"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/repo-diapason-dark.svg">
    <img alt="Diapason, skill Claude Code" src="assets/repo-diapason-light.svg" width="49%">
  </picture></a>
  <a href="https://github.com/MalikMoussaoui/lyra-lyrics"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/repo-lyra-lyrics-dark.svg">
    <img alt="Lyra Lyrics, paroles synchronisées sur Mac" src="assets/repo-lyra-lyrics-light.svg" width="49%">
  </picture></a>
</p>

<p align="center"><sub>🎵 <b>Lyra Lyrics</b> : une app Mac en Swift (version 1.0.1) qui affiche les paroles synchronisées de ce que tu écoutes sur Spotify ou Apple Music.</sub></p>

### 🔒 En coulisses (dépôts privés)

| | |
|---|---|
| 🚓 **FiveM / GTA RP** | Scripts Lua sur mesure (customs, recoil, médias) et outils pour serveurs RP |
| 🧱 **Roblox** | Jeux en Luau, en solo et en équipe |
| 🤖 **Bots Discord & SaaS** | Next.js, Fastify, Stripe, MongoDB, Socket.io |
| 📱 **Mobile** | Flutter, Kotlin, Swift |

## 🐍 Mes contributions, version snake

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/MalikMoussaoui/MalikMoussaoui/output/snake-dark.svg">
  <img alt="Un serpent qui mange le graphe de contributions" src="https://raw.githubusercontent.com/MalikMoussaoui/MalikMoussaoui/output/snake-light.svg" width="100%">
</picture>

## 📫 Me trouver

<p align="center">
  <img alt="Discord : chp.a" src="https://img.shields.io/badge/Discord-chp.a-5865F2?style=for-the-badge&logo=discord&logoColor=white">
  <a href="mailto:amalik.moussaoui1710@gmail.com"><img alt="E-mail" src="https://img.shields.io/badge/E--mail-me%20contacter-fb923c?style=for-the-badge&logo=gmail&logoColor=white"></a>
</p>

<img alt="" src="https://capsule-render.vercel.app/api?type=waving&color=0:a78bfa,50:fb7185,100:fb923c&height=120&section=footer" width="100%">
