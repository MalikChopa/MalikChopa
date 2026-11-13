# Outils du trailer / Trailer tools

Le trailer est une **illustration** (pas un résultat de simulation). Tout se lance depuis la racine du dépôt, avec le `.venv` du projet (Pillow + numpy), `HOME` dans un dossier temporaire. Le MP4 et le WAV ne sont pas versionnés (`out/` est ignoré par git).

Prérequis : macOS avec Swift / AVFoundation (pour le MP4 seulement).

```
export HOME=$PWD/out/home; mkdir -p $HOME out/trailer
T=tools/trailer

# 1. GIF du README (versionné, jamais reconstruit par l'Action)
.venv/bin/python -I $T/build.py --out assets/trailer.gif --check

# 2. Bande-son « Tension » -> out/trailer/soundtrack.wav (48 kHz, déterministe, ~7,5 Mo)
.venv/bin/python -I $T/sound_tension.py --gif assets/trailer.gif --out out/trailer --report

# 3. Images 1280x720 à 30 i/s (chaque image du GIF étalée sur ses ms exactes)
.venv/bin/python -I $T/make_mp4.py assets/trailer.gif out/trailer/frames      # affiche : 1167 38900

# 4. MP4 (H.264 + AAC 192 kb/s, faststart) -> out/trailer/sol-0-teaser.mp4
swift $T/mux.swift out/trailer/frames out/trailer/soundtrack.wav out/trailer/sol-0-teaser.mp4

# 5. Contrôle (durée, pistes, taille, fps ; extrait 3 images)
swift $T/probe.swift out/trailer/sol-0-teaser.mp4 out/trailer/probe
```

Attendu : durée vidéo 38,9 s (1167 images / 30), 1280x720, une piste audio ; le conteneur peut afficher ~0,03 à 0,1 s de plus (AAC). `sound_tension.py` vérifie que la durée du GIF correspond au calendrier de `build.py` (sinon il s'arrête) et lit ses événements dans `build.py`.

Fichiers : `build.py` (GIF), `STORYBOARD.md`, `sound_tension.py`, `make_mp4.py`, `mux.swift`, `probe.swift`.
