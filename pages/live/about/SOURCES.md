# Onglet « Comment ça marche / How it works » : sources et notes d'intégration

Rôle EXPLAIN, brief `docs/briefs/46-page-v2.md`, 2026-11-13 (écrit vers 12:40-13:00 UTC). Statut : terminé.
Code lu (lecture seule) : branche `live` à `live-rc13` (e93ad06), `out/wt/LIVE`. Aucune donnée du vrai rover lue ou exécutée ; aucune graine calculée.

## 1. Fichiers livrés

| Fichier | Rôle | Taille (octets) |
|---|---|---|
| `fr.html` | fragment FR (racine `<div class="x" lang="fr" data-explain="fr">`), 13 sections, 7 schémas SVG en ligne, 5 images | 65 046 |
| `en.html` | fragment EN, même structure | 61 581 |
| `explain.css` | classes `.x*` du fragment (aucune autre règle) | 4 694 |
| `img/*.png` | 5 images copiées de `docs/img/comprendre/` sans retouche (toutes ≤ 300 Ko, pas de conversion) | 88 518 au total |
| `src/make_explain.py`, `src/fr.tmpl.html`, `src/en.tmpl.html` | source des fragments : modèles + générateur des schémas ; **ne pas copier dans la page** | — |

Régénérer (depuis la racine du projet) : `HOME="$PWD/out/page-v2/explain/src/.home" .venv/bin/python -I out/page-v2/explain/src/make_explain.py` (bibliothèque standard seule). Le générateur refuse : `<script>`, `<style>`, attribut `style=`, gestionnaire `on…=`, `javascript:`, identifiant en double ou sans préfixe de langue, ancre cassée, `aria-labelledby` sans cible, libellé SVG plus large que sa boîte (chasse 0,6 em). En FR, il pose une espace insécable avant `: ; ? !` et dans `« … »` (texte seulement).

Vérifications faites : 2 fragments générés sans erreur ; balises équilibrées (analyse `html.parser`) ; 12 figures, 12 étiquettes (`schéma`/`diagram` × 7, `image d'essai, pas Sol-0`/`test image, not Sol-0` × 4, `illustration` × 1) ; 5 `<img>` avec `alt`, `width`, `height`, `loading="lazy"` ; 7 SVG avec `role="img"`, `<title>`, `<desc>` ; scan privé (`.private_patterns` + IP, nom de clé, préfixe IPv6) : 0. Rendu regardé par miniatures `qlmanage -t` (WebKit de QuickLook, pas de navigateur) : schémas FR/EN, sections intro, cerveau, stades, console, direct, vrai, FAQ. **Non vérifié** : rendu dans de vrais navigateurs, largeurs 320-768 px (raisonné d'après le CSS seulement), lecteurs d'écran.

## 2. Notes pour BUILD (intégration)

- **Chemins** : les images sont appelées `explain/img/<nom>.png`, relatif à `index.html`. Copier `img/` dans `pages/live/explain/img/`. CSP actuelle compatible (`img-src 'self'`, `style-src 'self'`) : aucune règle en ligne, couleurs des schémas en attributs de présentation SVG (non soumis à la CSP).
- **Poids** : 127 Ko pour les deux fragments bruts. Les mettre tous deux dans `index.html` porterait la page vers ≈ 200 Ko (contrôle « page ≤ 200 Ko » de la préparation). Proposition : fichiers séparés `pages/live/explain/{fr,en}.html`, chargés au premier affichage de l'onglet dans la langue active (`fetch` même origine, `connect-src 'self'` déjà présent), puis insérés tels quels ; ou retirer les commentaires `<!-- source … -->` à la copie (≈ 3 Ko par langue ; les sources restent ici). Décision : DESIGN/BUILD.
- **Liens profonds** : le sommaire pointe vers `#x-fr-…` / `#x-en-…`. Le routeur (`#live`, `#about`, `#fr`/`#en`) doit soit les ignorer (onglet « Comment ça marche » ouvert, défilement vers l'ancre), soit intercepter ces clics (`scrollIntoView`, sans changer le hash). Chaque section porte `data-sec` identique dans les deux langues : `intro planet body brain learn camera stages console live real journal faq glossary` (ex. `#about/brain` → section `data-sec="brain"` de la langue active). `h3` a `scroll-margin-top: 72px` (à ajuster à la hauteur de la barre d'onglets).
- **Titres** : `h2` = titre de l'onglet, `h3` = sections, `h4`, `h5` (fiches M0-M5). Garder, ou décaler si l'onglet a déjà un `h2`.
- **Libellés de la page cités** (à garder égaux à `out/page-v2/i18n.json` ; test conseillé : chaque `.x-lbl` = un libellé du dictionnaire de la langue) :
  FR `CONNEXION`, `EN DIRECT`, `APPRENTISSAGE`, `MOTEUR SILENCIEUX`, `REPRISE`, `MOTEUR EN PAUSE`, `SERVEUR OCCUPÉ`, `HORS LIGNE` ; EN `CONNECTING`, `LIVE`, `LEARNING`, `ENGINE SILENT`, `RESUMING`, `ENGINE ON HOLD`, `SERVER BUSY`, `OFFLINE` (source : `pages/live/assets.json` `i18n`, `pages/live/live.js` l. 269 `EXTRA_LABELS`). Noms de la console cités dans le texte : `CAM-1`, `M0`-`M5`, `L`, `R`, `XI`, `???`, `SCAN`, « vision hors ligne » / « no module reads the camera » (pour `VISION OFFLINE`). Si I18N les traduit autrement, ajuster les deux modèles `src/*.tmpl.html` puis régénérer.
- **Fonctions de la v2** : le texte ne parle pas encore de « ouvrir un panneau en plus grand » ni des onglets (non construits à l'écriture). Phrase prête si BUILD les livre, à ajouter à la fin de la section `console` : FR « Sur la page, chaque panneau s'ouvre en plus grand d'un clic, d'un toucher ou avec la touche Entrée, et se referme avec Échap. » ; EN « On the page, each panel opens larger with a click, a tap or the Enter key, and closes with Escape. » (à aligner sur DESIGN.md).
- **EF-87** : aucune animation ni transition (`.x *{animation:none;transition:none}`), `<details>` s'ouvre d'un coup, fond du fragment = fond de la page (`#120c0a`) : changer d'onglet ne fait pas de saut de luminosité dû au fragment. `prefers-reduced-motion` : rien à couper (pas de défilement animé).
- **Contrastes** (calcul WCAG sur la palette) : texte `#f2c38b` sur `#120c0a` ≈ 12:1 ; titres `#ffb347` ≈ 10,9:1 ; légendes `#d98c4a` ≈ 7,2:1 ; étiquettes `#c9673a` ≈ 5,1:1. `#8a3b1e` sert seulement aux traits.
- **Accessibilité** : `lang` sur la racine ; sections `aria-labelledby` ; tableau des stades avec `<caption class="x-sr">` (masquée visuellement) ; tableaux dans `.x-tw` (défilement horizontal du tableau seul, jamais de la page) ; fiches M0-M5 en grille `minmax(min(100%,30ch),1fr)` (une colonne sur téléphone).

## 3. Images (≤ 6, toutes étiquetées)

| Image | Ce que c'est (source : `docs/COMPRENDRE-SOL-0.md`) | Étiquette |
|---|---|---|
| `img/cam1-par-stade.png` (676×488, 14,6 Ko) | CAM-1 aux stades 0-3, chaîne de calibrage J7, graine de test 20261111, 4 sols/jour, 2026-11-11 (§4) | image d'essai, pas Sol-0 |
| `img/cam1-memes-endroits.png` (1080×416, 15,5 Ko) | planche `probe_after.png` du calibrage J7 : mêmes 6 endroits, pas des sols vécus, graine 20261111 (§4) | image d'essai, pas Sol-0 |
| `img/console-annotee.png` (1280×720, 30,2 Ko) | 38e image de `console.gif` du sol 86, stade 3, jalon J6, graine 20261111, 4 sols/jour ; pastilles ajoutées (§10) ; date d'horloge simulée | image d'essai, pas Sol-0 |
| `img/map-sol86.png` (640×400, 4,2 Ko) | `map.png` du même sol 86 (§10) | image d'essai, pas Sol-0 |
| `img/bande-annonce-image180.png` (640×360, 19,3 Ko) | 181e image de `trailer.gif`, marquée ILLUSTRATION à l'image (§8) | illustration |

Les 7 schémas sont dessinés par `src/make_explain.py` (étiquette `SCHÉMA`/`DIAGRAM` dans l'image et dans la légende). Seul chiffre « d'exemple » : le neurone (1 ; −2 ; 0,5 ; 0,25 ; 0,1), repris de `docs/RESEAUX-DE-NEURONES.md` §1.2 (« calcul à la main, sans rapport avec un vrai réseau ») et dit tel quel ; la grille de numéros du schéma « image » est un exemple, ses couleurs sont la vraie palette (`src/rover/core/consts.py` `CAM_RGB`, encre choisie par `CAM_LUT`).

## 4. Affirmation → source

Marques : [C] lu à la source (config ou code de `live-rc13`) ; [Calc] calculé à partir de [C] ; [M] mesuré par le projet (document cité) ; [D] décision de l'utilisateur ou du brief. Chemins de code relatifs à `out/wt/LIVE`.

| # | Affirmation (FR = EN) | Valeur | Source |
|---|---|---|---|
| 1 | Naissance | 2026-11-13T12:11:21Z | [D] brief 46, ligne 1 |
| 2 | Graine de naissance tirée de l'heure par un calcul fixe (SHA-256), écrite une fois ; un redémarrage ne la retire pas | — | [C] `src/rover/live/birth.py` (`derive_birth_seed`, `ensure_birth` : « existing record wins ») |
| 3 | Monde et cerveau de départ issus de cette graine | — | [C] `src/rover/pipeline/sol_io.py` l. 43-49 ; `src/rover/pipeline/sol.py` l. 81-86 (`fresh_state` : `world_seed`, `Brain.initial`) |
| 4 | Essais sur d'autres graines, jamais la sienne | — | [D] `CLAUDE.md` (règle du 2026-11-12) |
| 5 | Sol = 1 200 pas de 72 s = 24 h | 1 200 × 72 = 86 400 s | [C] `config/run.toml` `ticks_per_sol`, `tick_s` ; [Calc] |
| 6 | 96 sols par jour, créneau de 15 min calé sur l'UTC | 86 400 / 900 | [C] `config/run.toml` `sols_per_day = 96` ; `config/live/live.toml` `slot_s = 900` ; `docs/LIVE-DESIGN.md` §3.1 |
| 7 | Pas de 0,7 / 0,7 / 0,65 / 0,6 / 0,6 / 0,6 s ; vie 14 / 14 / 13 / 12 / 12 / 12 min ; fin de sol 1 / 1 / 2 / 3 / 3 / 3 min | 1 200 × `tick_ms` ; 900 − E | [C] `config/live/live.toml` `tick_ms` ; [Calc] ; `docs/LIVE-DESIGN.md` §3.1 |
| 8 | Une photo tous les 8 pas, 150 par sol, toutes les 4,8 à 5,6 s | 8 × 0,6 ; 8 × 0,7 | [C] `config/rover.toml` `cam_period = 8` ; [Calc] |
| 9 | Acuité 8×6 (0-1), 32×20 (2), 80×50 (3), 160×100 (4-5) | — | [C] `config/rover.toml` `[camera] acuity` |
| 10 | Palette de 24 numéros (0-23) ; le cerveau lit la clarté de chaque numéro | — | [C] `src/rover/core/consts.py` `N_SENSOR_COLORS`, `CAM_LUT` |
| 11 | Image affichée = entrée du cerveau ; balayage réversible ; test pixel par pixel ; distance lue mais non dessinée | — | `docs/COMPRENDRE-SOL-0.md` §4 ; `docs/RESEAUX-DE-NEURONES.md` §3.1-§3.3 |
| 12 | Au stade 0, aucun module ne lit la caméra | — | `docs/RESEAUX-DE-NEURONES.md` §3.2 ; [C] `pages/live/console.js` (`VISION OFFLINE`) |
| 13 | Cases de 5 m ; roche, poussière, sable, glace ; glace : adhérence 0,5 contre 1 | — | [C] `config/world.toml` `cell_m` ; `config/rover.toml` `mu` |
| 14 | Année de 600 sols = 6 j 6 h | 4 × 150 ; 600 / 96 = 6,25 j | [C] `config/world.toml` `season_sols = 150` ; [Calc] ; `docs/LIVE-DESIGN.md` §4.3 |
| 15 | Jour du rover de 9,5 à 14,5 h | 12 ± 2,5 | [C] `config/world.toml` `day_base_h`, `day_amp_h` |
| 16 | Tempête 1 sol sur 40 ≈ 2,4 par jour ; vue ÷ 2 ; panneau à 35 % | 96 / 40 | [C] `config/events.toml` `storm_one_in`, `storm_view`, `storm_solar` ; [Calc] |
| 17 | Deux commandes entre −1 et +1 ; vitesse max ≈ 1,7 cm/s | 0,25 case/pas × 5 m / 72 s = 1,74 cm/s | [C] `config/rover.toml` `v_max` ; [Calc] ; `docs/COMPRENDRE-SOL-0.md` §3 |
| 18 | Panne sous 15 %, veille forcée jusqu'à 40 % | — | [C] `config/rover.toml` `[energy] cutoff`, `resume` |
| 19 | Mode de secours au sol suivant : dégage, remet sur roues (−10 % batterie), remonte à 40 % une batterie restée vide | — | [C] `src/rover/stages/watchdog.py` l. 16-37 ; `config/rover.toml` `tip_cost = 0.1`, `safe_recharge = 0.40` |
| 20 | Sens éteint = exactement 0 ; entrées de M0 allumées : 5 (stades 0-1), 18 (2), 22 (3-5) | — | [C] `src/rover/core/consts.py` `M0_ACTIVE` ; `docs/RESEAUX-DE-NEURONES.md` §2.2 |
| 21 | Tailles : M0 24→16→2 = 434 ; M1 5→16→3 = 147 ; M2 40→8 = 320 ; M3 8→8→3 = 99 ; M4 10→8→1 = 97 ; total ≈ 1 100 | 1 097 | [C] `config/brain.toml` `[m0]`…`[m4]` ; [Calc] `n_in·h + h + h·out + out` |
| 22 | M5 : jusqu'à 15 familles ; nom à partir de 5 membres ; 10 itérations de Lloyd ; nouvelle famille au-delà de 0,25 ; sans tirage | — | [C] `src/rover/core/consts.py` `M5_K_MAX = 15` ; `config/brain.toml` `[m5]` ; `docs/RESEAUX-DE-NEURONES.md` §6.2 |
| 23 | M1 prédit avance, dérive, rotation sur 20 pas ; gradient, Adam 0,01, 200 pas au stade 1, 50 ensuite ; R² sur sols mis de côté | — | [C] `config/brain.toml` `[m1]`, `babble_segment = 20` ; `src/rover/brain/brain.py` l. 292-294 ; `docs/RESEAUX-DE-NEURONES.md` §5.1 |
| 24 | M2 : 40 mesures → 8 nombres, règle de Sanger | — | [C] `config/brain.toml` `[m2] k = 8` ; `docs/RESEAUX-DE-NEURONES.md` §5.2 |
| 25 | M3 tous les 20 pas : rouler, s'arrêter au soleil (moteurs coupés), dormir ; entrées | — | [C] `config/brain.toml` `[m3] step_ticks = 20` ; `src/rover/brain/brain.py` l. 211 (SEEK_SUN garé) ; `src/rover/brain/m3_energy.py` l. 27-29 |
| 26 | M4 : forer ou non ; au plus 6 forages par sol ; entrées | — | [C] `config/matter.toml` `drills_max = 6` ; `docs/RESEAUX-DE-NEURONES.md` §2.2, §6.1 |
| 27 | Évolution : 48 variantes par paires, 2 parcours de 160 pas, rangs, Adam 0,03 ; 12 générations pour le module du stade, 2 d'entretien (24 variantes) pour les autres | — | [C] `config/brain.toml` `[es]` ; `src/rover/brain/brain.py` l. 280-321 ; `docs/RESEAUX-DE-NEURONES.md` §4 |
| 28 | Note d'un parcours de M0 : progrès − 0,002 × effort − 2 − 1 + 5 | — | [C] `config/brain.toml` `[es] energy_pen`, `tip_pen`, `stuck_pen`, `arrive_bonus` |
| 29 | Examen fixe dès le stade 2 : 20 parcours, 300 pas, 1,5 case ; un sol sur 4 en consolidation ; régression : 2 fois sous 80 % du meilleur des 5 derniers → retour du pilote | — | [C] `config/brain.toml` `[battery]`, `arrive_r` ; `docs/RESEAUX-DE-NEURONES.md` §7 (seul M0 est restauré) |
| 30 | Softsign v/(1+|v|), identique au bit près ; OpenAI-ES (Salimans et al., 2017) ; splitmix64 | — | `docs/RESEAUX-DE-NEURONES.md` §1.3, §4.1, §8 ; [C] `src/rover/core/rng.py` l. 1 |
| 31 | La console montre module, génération (ex. 7/12), meilleure et moyenne, examen | — | [C] `pages/live/live.js` (`GEN`, `BEST`, `MEAN`, `TEST COURSES`) ; `docs/LIVE-DESIGN.md` §9.3 |
| 32 | Critères : 200 couples ; R² ≥ 0,70 trois sols ; 16/20 ; 20 sols sans panne ; lift ≥ 26 sur 150 forages contre le hasard apparié ; ARI ≥ 0,8 dix sols valides | — | [C] `config/stages.toml` ; `src/rover/stages/machine.py` l. 41-73 ; `src/rover/brain/m4_sample.py` `chance_base` |
| 33 | Durées min. 6 h, 12 h, 7 j, 14 j, 14 j, 60 j ; entrées au plus tôt 0, 6 h, 18 h, j 7,75, j 21,75, j 35,75 ; consolidation j 95,75 | heures cumulées 6, 18, 186, 522, 858, 2 298 | [C] `config/stages.toml` `min_hours` ; [Calc] ; `docs/LIVE-DESIGN.md` §4.2 |
| 34 | Barre plafonnée à 99 % ; « critère atteint » + temps restant | — | [C] `src/rover/stages/machine.py` l. 104-122 |
| 35 | Seuil −10 % après 3 puis 5 fois la durée visée ; jamais de passage forcé | — | [C] `config/stages.toml` `recal_factor = 0.9`, `recal_second = 5` ; `src/rover/stages/machine.py` l. 91-100 |
| 36 | Après le stade 5 : consolidation, en attente d'une mise à jour ; une suite conçue, pas construite | — | [C] `src/rover/version.py` `MAX_STAGE = 5` ; `src/rover/render/status_svg.py` l. 30 ; [D] `CLAUDE.md` (phase 3, 2026-11-12 14:00) |
| 37 | Console : panneaux, légende des connexions (|poids × entrée|, pointillé = négatif), batterie dès le stade 3, bras (16×16, HRD R G B GRN, gain, M4, forages), SCAN (16 bandes, nuage, famille) | — | [C] `pages/live/console.js` l. 109-110, 273-287, 292-372 ; `pages/live/assets.json` `legend` ; `docs/RESEAUX-DE-NEURONES.md` §3.3 |
| 38 | Carte locale 60 × 60 cases = 300 m | 60 × 5 m | [C] `src/rover/live/views.py` l. 12 `CELLS = 60` ; [Calc] |
| 39 | Serveur Linux loué, en Europe, allumé jour et nuit | — | [D] `CLAUDE.md` (2026-11-12 18:00 : Contabo, UE) ; `docs/HANDOFF.md` (Ubuntu 24.04) |
| 40 | Chaque pas calculé à son heure, jamais en avance | — | `docs/LIVE-DESIGN.md` §3.3 R1 |
| 41 | Flux depuis live.sol0.fr ; dessin au plus 2 fois par seconde ; pas d'interpolation | 500 ms | [C] `pages/live/live.js` l. 5 `MIN_DRAW_MS` ; `docs/LIVE-DESIGN.md` §9.2 |
| 42 | Âge de la donnée = âge de la chose la plus ancienne affichée (image CAM-1 comprise) | — | [C] `pages/live/live.js` `dataAgeS` (l. 276-284) |
| 43 | Connexion : état exact du sol en cours d'abord | — | [C] `pages/live/live.js` (`snapLeft`, `exact`) ; `docs/HANDOFF.md` (rc6-rc11 « état exact ») |
| 44 | Moteur silencieux : 120 s sans ligne, ou 5 s sans pas pendant le sol | — | [C] `pages/live/live.js` l. 6 `SILENT_S`, `TICK_GAP_MS` |
| 45 | Reprise : sol recalculé jusqu'au pas dû, empreinte vérifiée ; sinon maintien | — | [C] `src/rover/live/engine.py` l. 213-326 (`Hold("determinism")`) ; `docs/LIVE-DESIGN.md` §5.3 |
| 46 | Moteur en pause : refus plutôt que réparation silencieuse (empreinte, contrôle, disque plein…) ; plus de sol jusqu'au redémarrage | — | [C] `src/rover/live/engine.py` (`Hold` : `disk_full`, `foreign_write`, `refused`, `prepare`, `determinism`, `check`) ; `pages/live/live.js` `holdText` |
| 47 | Serveur occupé : 503/429, nouvel essai automatique | 9 s | [C] `pages/live/live.js` l. 7 `BUSY_POLL_MS`, l. 217 |
| 48 | Hors ligne après 3 échecs ; dernier sol publié, « enregistré, pas en direct » ; essai chaque minute | — | [C] `pages/live/live.js` l. 7 `FAILS_TO_OFFLINE = 3`, `OFFLINE_RETRY_MS = 60000` ; `pages/live/assets.json` `offline_note` |
| 49 | Créneaux manqués jamais rattrapés ; entrée de journal dès 4 créneaux (1 h) ; numéro du sol = mémoire | — | [C] `src/rover/narrative/digest.py` l. 20 `IMMEDIATE_MISSED = 4` ; `docs/LIVE-DESIGN.md` §3.1, §5.3 |
| 50 | Trace = boîte noire ; dessin interdit d'appeler monde, physique, cerveau (test) ; activation changée → point changé (test) | — | `docs/COMPRENDRE-SOL-0.md` §8 ; `docs/COMMENT-CA-MARCHE.md` §1 (`tests/test_layers.py`) ; `docs/RESEAUX-DE-NEURONES.md` §3.3 (`tests/render/test_truth_panels.py`) |
| 51 | 68 empreintes identiques entre l'ordinateur de développement et le serveur, avant la naissance | 68 égales, 0 différente | [M] `out/server/SERVER.md` l. 11 ; `docs/JOURNAL.md` l. 72 ; `docs/HANDOFF.md` (rc13 : refs 68/68) |
| 52 | Publication par le serveur toutes les 24 sols (≈ 6 h) et aussitôt après un sol marquant ; images + mémoire sur une branche à part, journal sur la branche principale | — | [C] `config/live/live.toml` `publish_every_sols = 24` ; `docs/LIVE-DESIGN.md` §8.1 |
| 53 | Les images publiées rejouent un sol de moins de 6 h ; texte des images en anglais | — | `pages/readme-section.md` ; [D] `docs/FICHE.md` §3 ; brief 46 §3 |
| 54 | Journal bilingue, sobre, première personne ; phrases à trous, pas de modèle de langage ; résumé quotidien + entrées immédiates (premières fois, stade, incident) | — | [D] `docs/FICHE.md` §3 ; `docs/COMMENT-CA-MARCHE.md` §0 ; `docs/LIVE-DESIGN.md` §6.1 |
| 55 | Mise à jour du programme entre deux sols, signalée par le journal | — | `docs/LIVE-DESIGN.md` §6.1, §11 (`sol0ctl update` en phase `idle`) |
| 56 | Cibles tirées par le programme | — | [C] `config/brain.toml` `target_dist`, `target_period` ; `docs/RESEAUX-DE-NEURONES.md` §9 (`_update_targets`) |
| 57 | Aux stades 0-2, sommeil la nuit (caméra éteinte, cerveau à 0) ; dès le stade 3, M3 décide ; image de nuit bruitée | bruit 0,6 la nuit contre 0,15 le jour | [C] `src/rover/brain/brain.py` l. 191-194 ; `config/rover.toml` `noise_night`, `noise_day` ; `docs/LIVE-DESIGN.md` §9.2 |
| 58 | Journée de 24 h jouée en 12 à 14 min : 100 à 120 fois plus vite | 1 440 / 14 ≈ 103 ; 1 440 / 12 = 120 | [Calc] d'après #7 |
| 59 | GPT-3 : 175 milliards de paramètres, publié en 2020 | — | `docs/COMPRENDRE-SOL-0.md` §6 et §13 (arXiv 2005.14165) ; non revérifié ici |
| 60 | Paris : UTC+1 en hiver, UTC+2 en été | — | connaissance générale |
| 61 | Exemple du neurone : 1 × 0,5 + (−2) × 0,25 + 0,1 = 0,1 ; 0,1 / 1,1 = 0,09 | — | `docs/RESEAUX-DE-NEURONES.md` §1.2 ; [Calc] |

## 5. Points ouverts « à re-valider » (aucun ne bloque)

1. **Profil GitHub à l'écriture** (GET en lecture seule, ≈ 12:45 UTC) : pas encore de branche `state` ni de section Sol-0 dans le README (seule la PR 1 est fusionnée). Le texte parle donc des « images du profil » et décrit la cadence prévue (`publish_every_sols = 24`), sans dire que le README les affiche déjà. Que la publication soit active sur le serveur : **non vérifié** (aucun accès serveur). À relire après la PR 2 (README).
2. Mention « en Europe » pour le serveur : vraie, utile au lecteur ; à garder ou retirer selon le souhait de l'utilisateur.
3. Mention de la suite (« une suite est conçue, mais pas encore construite », phase 3) : à garder ou retirer.
4. Image de la bande-annonce dans l'onglet (seule illustration) : montrée pour expliquer l'exception à « tout est réel » ; à garder ou retirer.
5. Les 4 images d'essai viennent de l'ancienne cadence (4 sols/jour) et d'une graine de test : étiquetées comme telles ; quand Sol-0 aura vécu, de vraies images de sa vie (publiées) pourraient les remplacer, avec leur date et leur sol.
6. L'onglet est long (≈ 13 sections) : le sommaire et les dépliants (FAQ, « pour aller plus loin ») le rendent parcourable ; une version courte n'a pas été écrite.
