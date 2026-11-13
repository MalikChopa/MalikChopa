# Direction B « Dedans / dehors » : storyboard

Réalisateur : agent direction B, 2026-11-11. Brief : `docs/briefs/18-realisateurs-cinematique.md`.
Fichiers : `build.py` (script unique), `teaser.gif` (le film), `frames.png` (12 images clés, 2 colonnes), ce fichier.

## Intention
Montage alterné entre le dehors (la planète, le rover endormi) et le dedans (son cerveau). Chaque coupe est un **raccord de forme** :
ciel étoilé ↔ treillis de neurones, crête de dune ↔ courbe d'activation, soleil ↔ neurone, roue ↔ anneau de nœuds,
objectif ↔ cercle, sortie R ↔ moyeu, bras de suspension ↔ fil du signal. Le rythme accélère (plans de 3,5 s jusqu'à 0,7 s).
L'influx descend jusqu'à la roue, qui tourne de 14° : c'est le seul mouvement du film. Puis le silence, le noir, le titre.
Aucun texte avant le titre (hormis L et R sur les deux sorties) : le film se raconte en images (pixel art 320×180 agrandi ×2, bandes noires 2,22:1,
lignes de balayage, vignette, grain fixe par plan, palette désert rouille + bleu des neurones de la console).

## Plans (100 ms par image rendue ; durées mesurées dans le GIF)

| # | Début | Durée | Dehors / dedans | Image | Raccord, intention |
|---|---|---|---|---|---|
| S00 | 0,0 s | 0,6 s | noir | noir, seul le marquage ILLUSTRATION | silence d'ouverture |
| S01 | 0,6 s | 3,5 s | DEHORS | nuit, ciel étoilé au-dessus d'une ligne de dunes noires, bande de poussière ; ouverture en fondu, étoiles qui scintillent doucement | plan d'ensemble, contemplatif |
| S02 | 4,1 s | 3,0 s | DEDANS | les mêmes étoiles (mêmes positions) glissent jusqu'aux places d'un réseau à 5 couches ; les connexions apparaissent | **étoiles ↔ neurones** : le ciel devient un cerveau, endormi |
| S03 | 7,1 s | 3,5 s | DEHORS | aube ; trois plans de dunes en parallaxe (1 ; 0,62 ; 0,35 px/image), crête éclairée, faces d'avalanche à l'ombre | panoramique lent |
| S04 | 10,6 s | 2,5 s | DEDANS | la crête devient la courbe d'activation bleue (même forme, même position, même vitesse de défilement) ; les deux dunes lointaines deviennent deux traces pâles ; de petits pics apparaissent | **crête ↔ courbe** : quelque chose remue |
| S05 | 13,1 s | 2,8 s | DEHORS | lever du soleil ; silhouette du rover, petite, sur une dune ; un liseré de lumière naît sur son contour | première apparition du robot |
| S06 | 15,9 s | 2,0 s | DEDANS | un neurone, à la place exacte du soleil, s'allume ; une étincelle part vers un voisin | **soleil ↔ neurone** |
| S07 | 17,9 s | 3,5 s | DEHORS | le rover endormi (tête de mât baissée), dans l'ombre ; la lumière avance sur le sable et sur lui ; lent travelling avant | le robot, de près ; à la fin il est à moitié dans l'ombre |
| S08 | 21,4 s | 2,0 s | DEDANS | cascade douce : des étincelles traversent les couches 1 à 3, les nœuds touchés restent faiblement allumés | l'éveil se propage |
| S09 | 23,4 s | 1,6 s | DEHORS | gros plan fixe d'une roue (crampons, rayons, bras) posée dans le sable | silence, attente |
| S10 | 25,0 s | 1,2 s | DEDANS | anneau de 12 nœuds + moyeu + 6 rayons, au même centre et au même rayon que la roue ; l'activation fait le tour | **roue ↔ anneau de nœuds** |
| S11 | 26,2 s | 1,0 s | DEHORS | face de la tête caméra, objectif noir (la caméra n'est pas allumée) ; le petit voyant ambre s'allume et reste allumé | **cercle ↔ objectif** ; signe de vie, sans « vision » |
| S12 | 27,2 s | 1,0 s | DEDANS | zoom sur les sorties : les étincelles atteignent les deux nœuds L et R, puis repartent vers la droite | la commande est prise |
| S13 | 28,2 s | 0,8 s | DEHORS | très gros plan du moyeu (à la place exacte du nœud R) ; tressaillement d'environ 1° ; quelques grains tombent | **sortie R ↔ moyeu** |
| S14 | 29,0 s | 0,7 s | DEDANS | un influx file le long d'une ligne qui suit exactement le bras de suspension, jusqu'au nœud du moyeu | **fil ↔ bras** |
| S15 | 29,7 s | 2,2 s | DEHORS | la roue tourne de 14° (avance de 8,5 px d'art), le sable s'accumule devant, des grains tombent des crampons, petite poussière ; puis immobilité | **la première commande atteint la roue** |
| S16 | 31,9 s | 1,5 s | DEHORS | plan large : le rover en pleine lumière, avancé de 2,6 px d'art (14° de roue), petites traces derrière les roues, poussière qui retombe, voyant allumé, tête toujours baissée | tableau final, calme |
| S17 | 33,4 s | 1,0 s | noir | fondu au noir | respiration |
| S18 | 34,4 s | 4,5 s | titre | « SOL-0 » (ambre, fondu par paliers de la rampe HUD), puis « WATCH IT LEARN. LIVE. 4 SOLS A DAY. » (titre à 34,7 s ; accroche visible de 36,0 à 38,9 s, soit 2,9 s) | l'accroche |

Durée totale : **38,9 s**. Texte dessiné (anglais) : `ILLUSTRATION`, `L`, `R`, `SOL-0`, `WATCH IT LEARN. LIVE. 4 SOLS A DAY.`
Accroches de rechange possibles (non rendues) : « IT STARTS WITH NOTHING. WATCH IT LEARN. », « A PLANET OUTSIDE. A BRAIN INSIDE. ».

## Pourquoi le film ne divulgue rien
- Il ne montre que le début : la planète, le rover endormi, le cerveau qui s'éveille, un seul mouvement (la roue tourne de 14°). Ni stade, ni nom de stade, ni module (M0, M1…), ni carte, ni trajet, ni objectif atteint, ni courbe d'apprentissage, ni résultat.
- Le rover n'a qu'un châssis, une suspension à 6 roues, un mât et une tête caméra : **aucun bras, aucune foreuse, aucun instrument, aucune antenne**. Son objectif reste noir (aucune image dedans), en accord avec « VISION OFFLINE » du stade 0. Le voyant ambre signifie seulement « sous tension ».
- Le cerveau est un réseau générique (5 couches), sans étiquette sauf L et R, les deux sorties de roues qui existent dès le stade 0 dans la console.
- Le seul texte d'accroche ne promet aucun résultat (« regarde-le apprendre »).
- Le marquage ILLUSTRATION (carré + texte ambre `#a0702e`, bande noire du bas, à droite) est présent sur **chaque image**, noir et titre compris (vérifié sur les 315 images décodées).
- Aucun logo, aucune image d'agence spatiale, aucun asset externe : tout est dessiné par `build.py` (primitives numpy et `ImageDraw`), police 5×7 du projet recopiée.

## Mesures (2026-11-11, commande ci-dessous, contrôle maison sur les images décodées par Pillow)

| Mesure | Valeur | Limite |
|---|---|---|
| Taille de `teaser.gif` | **1 549 531 octets** | ≤ 2 000 000 |
| Dimensions | 640 × 360 | 640 × 360 |
| Durée | **38 900 ms** (389 images rendues → 315 images GIF, les images identiques sont fusionnées) | ~30-40 s |
| Plus courte image | 100 ms | ≥ 60 ms |
| Couleurs distinctes affichées | **56** (palette globale de 64 entrées, dont 1 index transparent, jamais affiché) | ≤ 64 |
| Transitions EF-87 (≥ 25 % de l'image, Δ luminance ≥ 0,1, la plus sombre < 0,8) | 8 au total, à 7,1 / 10,6 / 21,4 / 23,4 / 25,0 / 26,2 / 27,2 / 29,7 s | — |
| **Maximum de transitions dans une fenêtre de 1 s** | **1** | ≤ 3 |
| Marquage ILLUSTRATION identique sur chaque image décodée | oui (315/315) | toutes |
| Aller-retour (images décodées == images rendues, pixel à pixel) | oui | — |
| Déterminisme : deux constructions dans deux dossiers temporaires, `cmp` | **identiques** | mêmes octets |

Coût par plan (octets, mesuré par l'encodeur) : S00 3 k, S01 171 k, S02 257 k, S03 347 k, S04 108 k, S05 79 k, S06 23 k, S07 88 k, S08 56 k, S09 24 k, S10 26 k, S11 22 k, S12 44 k, S13 39 k, S14 17 k, S15 67 k, S16 24 k, S17 130 k, S18 15 k. Les plans chers sont le panoramique (S03), la métamorphose étoiles → réseau (S02) et les fondus (S01, S17). Marge restante : ~450 Ko.

Temps de construction : 15 à 25 s de rendu + 3 à 17 s d'encodage sur le Mac quand il est peu chargé ; 142 s + 28 s mesurés pendant que d'autres agents tournaient.

Commandes (depuis la racine du projet) :
```
HOME=<dossier temporaire> .venv/bin/python -I out/cinematique/B/build.py --check
HOME=<tmp> .venv/bin/python -I out/cinematique/B/build.py --out <tmp>/a --no-sheet ; (idem vers <tmp>/b) ; cmp <tmp>/a/teaser.gif <tmp>/b/teaser.gif
```
Versions : Python 3.12.15, numpy 2.5.4, Pillow 13.0.0 (`.venv` du projet).

## Choix techniques
- Rendu en 320×144 (zone utile) puis agrandi ×2 au plus proche ; quantification sur une palette fixe avec tramage ordonné (Bayer 4×4) ancré à la grille, pour que les zones fixes ne changent pas d'une image à l'autre.
- Familles de couleurs par matière (paysage, nuit, cerveau, métal) : le sable ne vire jamais au gris, les neurones restent bleus.
- Lignes de balayage : une ligne écran sur deux prend la teinte « jumelle » plus sombre de la palette. Vignette fixe. Grain fixe par plan (un grain qui change à chaque image coûterait l'image entière).
- Encodeur GIF écrit à la main (LZW, palette globale, boucle infinie, disposition 1) : seule la zone qui change est écrite, avec les pixels inchangés en transparent quand c'est plus court. Validé par l'aller-retour pixel à pixel avec le décodeur de Pillow.
- PRNG maison à entiers (splitmix64), graine fixe `0x504C3042`.

## Itérations (jugement de réalisateur sur `frames.png`)
1. Premier rendu : dunes de S03 en « rideaux » verticaux (ombrage par colonne entière), tête du rover levée au lieu de tombante, rover trop « chariot », boîtier d'objectif plat comme un frigo, nœuds orangés au S12 (la quantification piochait dans les gris).
2. Corrections : familles de couleurs par matière, rampe bleue pour les neurones, nouveau dessin du rover (châssis, aérations, articulations, tête à capot, objectif), roue (crampons, flancs, boulons, bras), tête caméra (bords arrondis, capot, bague crantée, vis, voyant), bande de poussière dans la nuit.
3. Finitions : ombrage des dunes limité à la bande sous la crête puis incliné (faces d'avalanche en diagonale), ombre portée de S07 adoucie et limitée au sable proche et au rover (elle tombait à tort sur les dunes lointaines), voyant du S16 agrandi, lent travelling avant sur le rover endormi, tressaillement du moyeu rendu visible.

## Non vérifié / limites
- Affichage réel dans un README GitHub (proxy d'images, mobile, thème clair) : non vérifié. Sur mobile (~350 px de large), le texte ILLUSTRATION (7 px à 640) devient très petit : discret, lisible sur ordinateur.
- Décodage vérifié seulement avec Pillow ; navigateurs non testés (le format écrit est du GIF89a standard).
- Déterminisme vérifié sur ce Mac seulement ; sur une autre machine, les fonctions trigonométriques de numpy pourraient différer d'un bit et changer quelques pixels (non mesuré).
- Les transitions EF-87 sont calculées avec ma propre implémentation (luminance WCAG en flottants), pas avec `rover.render.photosens` du projet.
