"""GIF -> sequence PNG 30 fps constante, x2 nearest-neighbour (1280x720).
Usage: make_mp4.py assets/trailer.gif dossier_sortie  (affiche le nombre d'images)"""
import sys, os
from PIL import Image
FPS = 30
def main(gif, out):
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f.startswith("f") and f.endswith(".png"): os.remove(os.path.join(out, f))
    im = Image.open(gif)
    starts, t = [], 0
    for i in range(im.n_frames):
        im.seek(i); starts.append(t); t += im.info.get('duration', 100)
    total_ms = t
    n = round(total_ms * FPS / 1000)
    cache = {}
    k = 0
    for f in range(n):
        ms = (f + 0.5) * 1000 / FPS  # milieu de l'image video
        while k + 1 < len(starts) and starts[k + 1] <= ms:
            k += 1
        if k not in cache:
            im.seek(k)
            fr = im.convert('RGB').resize((1280, 720), Image.NEAREST)
            cache = {k: fr}
        cache[k].save(os.path.join(out, f'f{f:05d}.png'), compress_level=1)
    print(n, total_ms)
if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
