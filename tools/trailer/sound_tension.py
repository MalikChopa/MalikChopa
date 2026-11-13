#!/usr/bin/env python3
"""Sol-0, trailer « Dedans / dehors » : bande-son « Tension » (choisie par l'utilisateur, 2026-11-11).

Synthèse procédurale 100 % originale : numpy + stdlib `wave`, aucun échantillon, aucun son téléchargé,
aucune mélodie empruntée. Déterministe : PRNG maison à entiers (splitmix64), graine fixe.
Le calendrier des événements est lu dans `build.py` (même dossier, le script qui fabrique le GIF) : étincelles,
pointes de la courbe, anneau, voyant, tressaillement du moyeu, rotation de la roue, chute des grains.

Usage (depuis la racine du projet) :
  HOME=<tmp> .venv/bin/python -I tools/trailer/sound_tension.py [--gif assets/trailer.gif] [--out DOSSIER] [--report] [--cues]
Sortie : DOSSIER/soundtrack.wav (48 kHz, hors dépôt : out/ est ignoré par git).
"""
import argparse
import importlib.util
import math
import os
import wave

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BDIR = HERE                 # build.py est dans le même dossier
ROOT = os.path.dirname(os.path.dirname(HERE))
SR = 48000
SEED = 0x534F4E32          # "SON2"
MASK = (1 << 64) - 1
TAU = 2 * math.pi


# ------------------------------------------------------------------------------------------ timeline
def load_build():
    spec = importlib.util.spec_from_file_location("trailer_build", os.path.join(BDIR, "build.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BLD = load_build()
FRAME = 4800                # one rendered image = 100 ms = 4800 samples
KIND = {"S00": "black", "S01": "OUT", "S02": "IN", "S03": "OUT", "S04": "IN", "S05": "OUT", "S06": "IN",
        "S07": "OUT", "S08": "IN", "S09": "OUT", "S10": "IN", "S11": "OUT", "S12": "IN", "S13": "OUT",
        "S14": "IN", "S15": "OUT", "S16": "OUT", "S17": "black", "S18": "title"}
SHOTS = []                  # (sid, start_frame, n_frames)
_f = 0
for _sid, _n, _fn, _lab in BLD.SHOTS:
    SHOTS.append((_sid, _f, _n))
    _f += _n
TOTAL_FRAMES = _f
N = TOTAL_FRAMES * FRAME
ST = {sid: f0 for sid, f0, n in SHOTS}
NF = {sid: n for sid, f0, n in SHOTS}


def T(sid, fi=0.0):
    """Time (s) of rendered image `fi` of shot `sid`."""
    return (ST[sid] + fi) * 0.1


def S(t):
    return int(round(t * SR))


def gif_duration_ms(path):
    im = Image.open(path)
    tot, k = 0, 0
    while True:
        try:
            im.seek(k)
        except EOFError:
            break
        tot += im.info.get("duration", 0)
        k += 1
    return tot, k


TT = np.arange(N) / SR
CUES = []                   # (t, sid, image, sound)


def cue(t, sid, img, snd):
    CUES.append((round(t, 4), sid, img, snd))


# ------------------------------------------------------------------------------------------ randomness
class Rng:
    def __init__(self, seed):
        self.s = seed & MASK

    def next(self):
        self.s = (self.s + 0x9E3779B97F4A7C15) & MASK
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def unit(self):
        return (self.next() >> 11) / float(1 << 53)

    def uniform(self, a, b):
        return a + (b - a) * self.unit()


def subseed(*parts):
    r = Rng(SEED)
    for p in parts:
        r.s = (r.s ^ (p * 0x2545F4914F6CDD1D)) & MASK
        r.next()
    return r.next()


def noise(seed, n):
    """Counter-based splitmix64, vectorised: n floats in [-1, 1)."""
    i = np.arange(1, n + 1, dtype=np.uint64)
    z = np.uint64(seed & MASK) + i * np.uint64(0x9E3779B97F4A7C15)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    z = z ^ (z >> np.uint64(31))
    return (z >> np.uint64(11)).astype(np.float64) * (2.0 / float(1 << 53)) - 1.0


def lfo_at(seed, t, rate):
    """Smooth value noise in [-1, 1] evaluated at times t (s)."""
    x = np.asarray(t, dtype=np.float64) * rate
    i = np.floor(x).astype(np.int64)
    f = x - i
    pts = noise(seed, int(i.max()) + 3)
    f = (1 - np.cos(np.pi * f)) * 0.5
    return pts[i] * (1 - f) + pts[i + 1] * f


# ------------------------------------------------------------------------------------------ dsp helpers
def lp_mag(f, fc, order=2):
    return 1.0 / np.sqrt(1.0 + (np.abs(f) / fc) ** (2 * order))


def hp_mag(f, fc, order=2):
    r = (np.abs(f) / fc) ** order
    return r / np.sqrt(1.0 + r * r)


def bp_log(f, fc, oct_bw):
    ff = np.maximum(np.abs(f), 1.0)
    return np.exp(-0.5 * (np.log2(ff / fc) / oct_bw) ** 2)


def pow2(n):
    return 1 << (int(n) - 1).bit_length()


def fft_filter(x, fn, pad=4096):
    n = len(x)
    nf = pow2(n + pad)
    X = np.fft.rfft(x, nf)
    f = np.fft.rfftfreq(nf, 1.0 / SR)
    return np.fft.irfft(X * fn(f), nf)[:n]


def conv(x, h):
    n = len(x) + len(h) - 1
    nf = pow2(n)
    return np.fft.irfft(np.fft.rfft(x, nf) * np.fft.rfft(h, nf), nf)[:n]


def stft_filter(x, mask_fn, nfft=2048, hop=512):
    """Time-varying zero-phase filter: mask_fn(t_col (s, relative to x[0]), f_row) -> gain."""
    n = len(x)
    xp = np.concatenate([np.zeros(nfft), x, np.zeros(2 * nfft)])
    nfr = (len(xp) - nfft) // hop + 1
    win = np.hanning(nfft + 1)[:-1]
    idx = np.arange(nfft)[None, :] + hop * np.arange(nfr)[:, None]
    X = np.fft.rfft(xp[idx] * win, axis=1)
    del idx
    tc = (hop * np.arange(nfr) + nfft / 2 - nfft) / SR
    f = np.fft.rfftfreq(nfft, 1.0 / SR)
    X *= mask_fn(tc[:, None], f[None, :])
    y = np.fft.irfft(X, nfft, axis=1) * win
    del X
    out = np.zeros(len(xp) + nfft * 4)
    q = nfft // hop
    for r in range(q):
        seg = y[r::q].reshape(-1)
        out[r * hop:r * hop + len(seg)] += seg
    norm = (win ** 2).sum() / hop
    return out[nfft:nfft + n] / norm


def pan_gains(p):
    a = (np.clip(p, -1, 1) + 1) * math.pi / 4
    return math.cos(a), math.sin(a)


def place(bus, sig, t, gain=1.0, pan=0.0):
    """Add mono (n,) or stereo (2, n) `sig` to `bus` (2, N) starting at time t (s)."""
    i0 = S(t)
    if sig.ndim == 1:
        gl, gr = pan_gains(pan)
        sig = np.vstack([sig * gl, sig * gr])
    a, b = max(0, i0), min(N, i0 + sig.shape[1])
    if b <= a:
        return
    bus[:, a:b] += gain * sig[:, a - i0:b - i0]


def edges(n, a=0.0005, r=0.0005):
    e = np.ones(n)
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    na, nr = min(na, n), min(nr, n)
    e[:na] *= np.linspace(0, 1, na)
    e[n - nr:] *= np.linspace(1, 0, nr)
    return e


def auto(points):
    xs, ys = zip(*points)
    return np.interp(TT, xs, ys)


def segments(kinds, extra=()):
    segs = []
    for sid, f0, n in SHOTS:
        if KIND[sid] in kinds or sid in extra:
            a, b = f0 * 0.1, (f0 + n) * 0.1
            if segs and abs(segs[-1][1] - a) < 1e-9:
                segs[-1][1] = b
            else:
                segs.append([a, b])
    return segs


def gate(kinds, ramp=0.012, extra=()):
    pts = [(0.0, 0.0)]
    for a, b in segments(kinds, extra):
        pts += [(a - ramp / 2, 0.0), (a + ramp / 2, 1.0), (b - ramp / 2, 1.0), (b + ramp / 2, 0.0)]
    pts.append((N / SR + 1, 0.0))
    pts = sorted(pts)
    return auto(pts)


def by_shot(levels, ramp=0.012):
    """Piecewise-constant level per shot (dict sid -> level), short ramps at the cuts."""
    pts = []
    for sid, f0, n in SHOTS:
        v = levels.get(sid, 0.0)
        a, b = f0 * 0.1, (f0 + n) * 0.1
        pts += [(a + ramp / 2, v), (b - ramp / 2, v)]
    return auto([(0.0, pts[0][1])] + pts + [(N / SR + 1, pts[-1][1])])


def rms_norm(x, target):
    r = np.sqrt(np.mean(x ** 2)) + 1e-12
    return x * (target / r)


def xpos_pan(x):
    return float(np.clip((x / BLD.AW) * 2 - 1, -1, 1)) * 0.8


# ------------------------------------------------------------------------------------------ instruments
MEMBRANE = [1.0, 1.593, 2.136, 2.296, 2.653, 2.917, 3.156, 3.5, 4.06, 4.6]   # circular-membrane mode ratios


def tick(seed, tock=False, bright=1.0):
    n = int(0.14 * SR)
    t = np.arange(n) / SR
    k = 0.78 if tock else 1.0
    y = np.zeros(n)
    r = Rng(seed)
    for f, d, a in ((2350, 0.020, 1.0), (3720, 0.013, 0.55 * bright), (5150, 0.008, 0.3 * bright), (1180, 0.035, 0.45)):
        y += a * np.sin(TAU * f * k * t + r.uniform(0, TAU)) * np.exp(-t / d)
    click = noise(seed, n) * np.exp(-t / 0.0012)
    y += 0.7 * fft_filter(click, lambda f: hp_mag(f, 900, 2) * lp_mag(f, 7000, 3), pad=512)
    y *= 1 - np.exp(-t / 0.0002)
    return y / np.abs(y).max()


def thump(f0=52.0, dur=0.32, drop=2.2, decay=0.09, drive=1.6):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f0 * (1 + (drop - 1) * np.exp(-t / 0.018))
    ph = TAU * np.cumsum(f) / SR
    y = np.sin(ph) * np.exp(-t / decay) * (1 - np.exp(-t / 0.0015))
    y = np.tanh(drive * y) / math.tanh(drive)
    y *= edges(n, 0.0, 0.01)
    return y


def boom(seed, f0=36.71, dur=2.0, drop=3.0, decay=0.45):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f0 * (1 + (drop - 1) * np.exp(-t / 0.05))
    ph = TAU * np.cumsum(f) / SR
    y = np.sin(ph) * np.exp(-t / decay)
    y = np.tanh(1.8 * y) / math.tanh(1.8)
    tr = noise(seed, n) * np.exp(-t / 0.012)
    y += 0.5 * fft_filter(tr, lambda f: lp_mag(f, 900, 2), pad=1024)
    y *= (1 - np.exp(-t / 0.001)) * edges(n, 0.0, 0.05)
    return y


def clank(seed, base=110.0, dur=1.4, decay=0.5, bright=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    r = Rng(seed)
    y = np.zeros(n)
    for k, m in enumerate(MEMBRANE):
        f = base * m * (1 + r.uniform(-0.006, 0.006))
        if f > 9000:
            continue
        a = (1.0 / (1 + 0.5 * k)) * (bright if k > 3 else 1.0)
        y += a * np.sin(TAU * f * t + r.uniform(0, TAU)) * np.exp(-t / (decay / (1 + 0.35 * k)))
    tr = noise(seed + 1, n) * np.exp(-t / 0.004)
    y += 0.6 * fft_filter(tr, lambda f: bp_log(f, 2200, 1.2), pad=1024)
    y *= (1 - np.exp(-t / 0.0004)) * edges(n, 0.0, 0.05)
    return y / np.abs(y).max()


def glitch(seed, energy=1.0, fmin=900.0, fmax=4200.0, nseg=None):
    """Granular glitch spark: 3-8 micro-segments (blips, crushed squares, chirps, stutters)."""
    r = Rng(seed)
    nseg = nseg or 3 + int(r.unit() * 6)
    parts = []
    for k in range(nseg):
        L = int(SR * r.uniform(0.002, 0.011))
        t = np.arange(L) / SR
        f = fmin * (fmax / fmin) ** r.unit()
        typ = r.next() % 4
        if typ == 0:
            s = np.sign(np.sin(TAU * f * t + 0.1)) * 0.45
        elif typ == 1:
            s = np.diff(noise(seed + 97 * (k + 1), L + 1)) * 0.35
        elif typ == 2:
            s = np.sin(TAU * f * t * (1 + (1 if r.unit() < 0.5 else -0.45) * t / max(t[-1], 1e-4)))
        else:
            q = max(8, L // 3)
            s = np.tile(np.sin(TAU * f * t[:q]), 4)[:L]
        bits = 2 + r.next() % 4
        s = np.round(s * (1 << bits)) / (1 << bits)
        parts.append(s * edges(L, 0.0004, 0.0008) * r.uniform(0.45, 1.0))
        parts.append(np.zeros(int(SR * r.uniform(0.0, 0.006))))
    y = np.concatenate(parts)
    y = fft_filter(y, lambda f: lp_mag(f, 6500, 4) * hp_mag(f, 250, 1), pad=1024)
    return energy * y / (np.abs(y).max() + 1e-9)


def ping(seed, f, decay=0.25, dur=None):
    dur = dur or decay * 5
    n = int(dur * SR)
    t = np.arange(n) / SR
    r = Rng(seed)
    y = (np.sin(TAU * f * t + r.uniform(0, TAU)) + 0.35 * np.sin(TAU * f * 2.756 * t) * np.exp(-t / (decay * 0.3))
         + 0.2 * np.sin(TAU * f * 1.003 * t))
    y *= np.exp(-t / decay) * (1 - np.exp(-t / 0.0015)) * edges(n, 0.0, 0.02)
    return y / np.abs(y).max()


def sizzle(seed, dur, pan0, pan1, f0, f1, swell=True):
    """Travelling spark: a granular stream following the spark from pan0 to pan1."""
    n = int(dur * SR)
    out = np.zeros((2, n + SR // 50))
    r = Rng(seed)
    t = 0.0
    while t < dur:
        u = t / dur
        f = f0 * (f1 / f0) ** u * (1 + r.uniform(-0.03, 0.03))
        L = int(SR * r.uniform(0.003, 0.008))
        tg = np.arange(L) / SR
        g = np.sin(TAU * f * tg) * np.hanning(L) * ((0.25 + 0.75 * u) if swell else 1.0) * r.uniform(0.5, 1.0)
        gl, gr = pan_gains(pan0 + (pan1 - pan0) * u)
        i = int(t * SR)
        out[0, i:i + L] += g * gl
        out[1, i:i + L] += g * gr
        t += r.uniform(0.007, 0.02) * (1 - 0.45 * u)
    return out[:, :n]


def saw_additive(freq, fc, amp, nh_max=200, thresh=3e-4, seed=1):
    """Band-limited saw by additive synthesis; freq, fc, amp: arrays (time-varying)."""
    r = Rng(seed)
    ph = TAU * np.cumsum(freq) / SR + r.uniform(0, TAU)
    y = np.zeros(len(freq))
    fmax = float(np.max(freq))
    for h in range(1, nh_max + 1):
        if h * fmax > 16000:
            break
        g = lp_mag(h * freq, fc, 2) / h
        if g.max() < thresh:
            break
        y += g * np.sin(h * ph)
    return y * amp


def reverb_ir(seed, dur, t60_low, t60_high, predelay=0.018, lp=6500.0):
    n = int(dur * SR)
    out = []
    for ch in range(2):
        z = noise(seed + ch * 7, n)

        def mask(t, f):
            ff = np.clip(f, 120, 9000)
            w = np.log(ff / 120) / np.log(9000 / 120)
            t60 = t60_low * (1 - w) + t60_high * w
            return 10 ** (-3 * np.maximum(t, 0) / t60) * lp_mag(f, lp, 2) * hp_mag(f, 70, 1)
        y = stft_filter(z, mask)
        pd = int(predelay * SR)
        y[:pd] = 0
        y[pd:pd + 240] *= np.linspace(0, 1, 240)
        y *= edges(n, 0.0, 0.05)
        out.append(y / np.sqrt((y ** 2).sum()))
    return np.vstack(out)


def reverb(bus, ir, wet):
    out = np.zeros_like(bus)
    for ch in range(2):
        out[ch] = conv(bus[ch], ir[ch])[:bus.shape[1]] * wet
    return out


# ------------------------------------------------------------------------------------------ score
def build_score():
    dry = np.zeros((2, N))
    send = np.zeros((2, N))        # medium room (ticks, glitches, pings)
    big = np.zeros((2, N))         # big hall (braam, ring)
    t_cut = T("S17")               # hard cut to silence
    t_title = T("S18", 3)          # SOL-0 first visible (34.7 s)
    t_hook = T("S18", 16)          # tagline first visible (36.0 s)

    # ---- sub drone (D1 + D2, beating, fifth) -------------------------------------------------------
    i_cut = S(t_cut)
    t = TT[:i_cut]
    d = (0.55 * np.sin(TAU * 36.71 * t) + 0.32 * np.sin(TAU * 73.42 * t + 0.4 * np.sin(TAU * 0.07 * t))
         + 0.2 * np.sin(TAU * 73.72 * t) + 0.1 * np.sin(TAU * 110.0 * t + 1.0))
    d = np.tanh(1.7 * d) / math.tanh(1.7)
    lvl = auto([(0, 0), (0.6, 0.035), (2.0, 0.09), (7.1, 0.11), (13.1, 0.14), (17.9, 0.16), (21.4, 0.19),
                (23.39, 0.2), (23.41, 0.07), (24.99, 0.09), (25.01, 0.15), (28.2, 0.2), (30.1, 0.3),
                (31.2, 0.22), (33.39, 0.32), (33.4, 0.32), (40, 0.32)])[:i_cut]
    dry[:, :i_cut] += d * lvl
    cue(0.0, "S00", "noir", "drone sub ré (36,7 Hz + 73,4 Hz) qui monte en fondu depuis 0")

    # ---- cold desert wind (OUTSIDE) --------------------------------------------------------------
    gust_seed = subseed(1)
    wind = []
    for ch in range(2):
        z = noise(subseed(2, ch), N)

        def wmask(tc, f, ch=ch):
            g = lfo_at(gust_seed, tc, 0.22)
            fc = 380 * 2 ** (1.1 * g)
            wh = 1150 * 2 ** (0.35 * lfo_at(gust_seed + 5, tc, 0.13) + 0.04 * ch)
            m = bp_log(f, fc, 1.1) + 0.5 * np.exp(-0.5 * ((f - wh) / 28.0) ** 2)
            return m * lp_mag(f, 3200, 2) * hp_mag(f, 110, 2) * (0.6 + 0.4 * (g + 1) / 2)
        wind.append(rms_norm(stft_filter(z, wmask), 0.03))
    wind = np.vstack(wind)
    wl = by_shot({"S01": 0.9, "S03": 1.0, "S05": 0.75, "S07": 0.85, "S09": 0.22, "S11": 0.3, "S13": 0.35,
                  "S15": 0.5, "S16": 0.6})
    wl *= auto([(0, 0), (0.6, 0.0), (2.0, 1.0), (40, 1.0)])          # S01 opens from black
    dry += wind * wl
    cue(T("S01"), "S01", "DEHORS, la nuit s'ouvre en fondu (0,6 → 2,0 s)", "vent froid du désert (bruit filtré, sifflement) en fondu avec l'image")
    for sid in ("S03", "S05", "S07", "S09", "S11", "S13", "S15"):
        cue(T(sid), sid, "DEHORS", "vent froid du désert (bruit filtré, sifflement) entre sur la coupe")

    # ---- metallic texture (bowed metal, membrane modes on D3) -----------------------------------
    met = []
    for ch in range(2):
        z = noise(subseed(3, ch), N)

        def mmask(tc, f, ch=ch):
            m = 0
            for k, ratio in enumerate(MEMBRANE[:8]):
                fk = 146.83 * ratio * (1 + 0.0015 * ch)
                ak = 0.5 + 0.5 * lfo_at(subseed(4, k), tc, 0.35 + 0.07 * k)
                m = m + ak / (1 + 0.3 * k) * np.exp(-0.5 * ((f - fk) / 3.0) ** 2)
            return m
        met.append(rms_norm(stft_filter(z, mmask, nfft=8192, hop=2048), 0.024))
    met = np.vstack(met)
    ml = by_shot({"S01": 0.35, "S02": 0.12, "S03": 0.55, "S04": 0.15, "S05": 0.75, "S06": 0.15, "S07": 0.95,
                  "S08": 0.2, "S09": 0.45, "S10": 0.2, "S11": 0.6, "S12": 0.25, "S13": 0.7, "S14": 0.3,
                  "S15": 0.8, "S16": 1.0})
    ml *= auto([(0, 0), (0.6, 0), (2.5, 1), (17.9, 1), (21.39, 1.35), (21.4, 1), (40, 1)])
    dry += met * ml
    cue(T("S07"), "S07", "rover endormi, travelling avant", "texture métallique frottée qui enfle (modes de membrane sur ré)")

    # ---- inside texture: data chatter (IN) ---------------------------------------------------------
    t = TT
    chat = np.zeros((2, N))
    for ch, freqs in enumerate(((1174.66, 1760.0), (1244.51, 1567.98))):
        for k, fq in enumerate(freqs):
            g = (noise(subseed(5, ch, k), N // 1200 + 2) > 0.1).astype(float)
            g = np.repeat(g, 1200)[:N]
            g = fft_filter(g, lambda f: lp_mag(f, 120, 2), pad=0)
            chat[ch] += np.sin(TAU * fq * t) * g * (0.5 if k else 1.0)
    hum = np.sin(TAU * 146.83 * t) * (0.6 + 0.4 * np.sin(TAU * 0.5 * t))
    inside = rms_norm(chat, 0.008) + rms_norm(hum, 0.012)
    il = by_shot({"S02": 0.5, "S04": 0.7, "S06": 0.8, "S08": 1.0, "S10": 0.8, "S12": 0.9, "S14": 1.0})
    dry += inside * il
    for sid in ("S02", "S04", "S06", "S08", "S10", "S12", "S14"):
        cue(T(sid), sid, "DEDANS", "texture numérique (bavardage de données D6/Eb6, bourdon 147 Hz) entre sur la coupe")

    # ---- cut accents ---------------------------------------------------------------------------------
    cuts = [sid for sid, f0, n in SHOTS if sid not in ("S00", "S01", "S17", "S18")]
    for k, sid in enumerate(cuts):
        tc = T(sid)
        w = 0.12 + 0.88 * (k / (len(cuts) - 1)) ** 1.5
        if KIND[sid] == "IN":
            place(dry, glitch(subseed(10, k), 1.0, 600, 3200), tc, 0.10 * w, -0.2)
            place(dry, thump(46, 0.3, 2.0, 0.08), tc, 0.30 * w)
            cue(tc, sid, "coupe DEHORS → DEDANS", "accent : étincelle glitch + coup sourd (46 Hz)")
        else:
            place(dry, boom(subseed(11, k), 41.2, 1.2, 2.4, 0.22), tc, 0.30 * w)
            place(send, clank(subseed(12, k), 98.0, 1.2, 0.35, 0.6), tc, 0.05 * w, 0.15)
            prev = SHOTS[[x[0] for x in SHOTS].index(sid) - 1][0]
            cue(tc, sid, f"coupe {'DEDANS' if KIND[prev] == 'IN' else 'DEHORS'} → DEHORS",
                "accent : impact grave (41 Hz) + choc métallique feutré")

    # ---- S02: stars glide to their neuron places -> each star is a tone gliding to its layer's pitch
    layer_f = [293.66, 440.0, 622.25, 698.46, 587.33]
    n02 = NF["S02"]
    i0, i1 = S(T("S02")), S(T("S03"))
    tl = (TT[i0:i1] - T("S02")) / 0.1                         # continuous frame index
    m = np.clip((tl - 3) / 15.0, 0, 1)
    m = m * m * (3 - 2 * m)
    la = np.clip((tl - 11) / 14.0, 0, 1)
    la = la * la * (3 - 2 * la)
    acc = np.zeros((2, i1 - i0))
    k = 0
    for (x, y, lv, ph, sp, isn) in BLD.STARS:
        if not isn:
            continue
        nx, ny, layer = BLD.NODES[k]
        fs = 330.0 * 2 ** ((106.0 - y) / 106.0 * 1.6)
        fn = layer_f[layer] * 2 ** ((ny - 72.0) / 72.0 * 0.012)
        f = fs * (fn / fs) ** m
        lt = lv * (0.78 + 0.22 * np.sin(ph + tl * sp))
        ph_ = TAU * np.cumsum(f) / SR + Rng(subseed(20, k)).uniform(0, TAU)
        v = np.sin(ph_) * lt
        gl, gr = pan_gains(xpos_pan(x + (nx - x) * float(m[len(m) // 2])))
        acc[0] += v * gl
        acc[1] += v * gr
        k += 1
    gat = (noise(subseed(21), (i1 - i0) // 960 + 2) > -0.2).astype(float)
    gat = fft_filter(np.repeat(gat, 960)[:i1 - i0], lambda f: lp_mag(f, 200, 2), pad=0)
    acc *= (0.55 + 0.45 * gat) * edges(i1 - i0, 0.01, 0.01)
    dry[:, i0:i1] += rms_norm(acc, 0.02) * (0.5 + 0.5 * m)
    cue(T("S02", 3), "S02", "les étoiles glissent vers les places des neurones (images 3-18)",
        "34 voix sinus : chaque étoile = une hauteur qui glisse vers l'accord de sa couche (ré, la, mi♭, fa, ré)")
    # connections appear (la: images 11-25) -> crackle density follows d(la)/dt
    dla = np.gradient(la)
    rr = Rng(subseed(22))
    tcur = T("S02", 11)
    while tcur < T("S02", 25):
        dens = 2 + 38 * float(np.interp((tcur - T("S02")) / 0.1, tl, dla)) / dla.max()
        place(send, glitch(subseed(23, int(tcur * 1000)), 1.0, 1500, 5000, nseg=2), tcur, 0.05, rr.uniform(-0.6, 0.6))
        tcur += 1.0 / dens
    cue(T("S02", 11), "S02", "les connexions apparaissent (images 11-25)", "crépitement de micro-glitchs, densité = vitesse d'apparition")

    # ---- S04: the dune crest becomes the activation trace --------------------------------------
    n04 = NF["S04"]
    ys = []
    for fi in range(n04 + 1):
        near, _, _ = BLD.crest_tops((35 + fi) * BLD.CAM3)
        ys.append(float(near[-6]))
    ys = np.array(ys)
    i0, i1 = S(T("S04")), S(T("S05"))
    tl = (TT[i0:i1] - T("S04")) / 0.1
    yv = np.interp(tl, np.arange(n04 + 1), ys)
    lo, hi = ys.min(), ys.max()
    f = 392.0 * 2 ** ((hi - yv) / max(hi - lo, 1e-6) * 1.0)
    ph_ = TAU * np.cumsum(f) / SR
    tr = (np.sin(ph_) + 0.3 * np.sin(2 * ph_)) * edges(i1 - i0, 0.01, 0.01)
    place(dry, rms_norm(tr, 0.018), T("S04"), 1.0, xpos_pan(BLD.AW - 6))
    cue(T("S04"), "S04", "point lumineux au bout de la courbe (x = 314)",
        "tonalité sinus dont la hauteur suit la hauteur réelle de la crête (392-784 Hz)")
    g = BLD.Rng(BLD.SEED + 404)
    for k in range(26):
        t0 = g.randint(-4, n04 + 2)
        x = g.uniform(10, BLD.AW - 10)
        hgt = g.uniform(2.0, 4.0 + 6.0 * (t0 / n04))
        if 0 <= t0 < n04:
            tc = T("S04", t0)
            e = 0.35 + 0.65 * min(1.0, hgt / 9.0)
            place(send, glitch(subseed(30, k), 1.0, 1200, 4800), tc, 0.11 * e, xpos_pan(x))
            cue(tc, "S04", f"pointe sur la courbe (x={x:.0f}, h={hgt:.1f})", "étincelle glitch granulaire")

    # ---- S06: one neuron fires at the sun's place, a spark leaves to a neighbour ----------------
    g = BLD.Rng(BLD.SEED + 606)
    others = []
    px, py = BLD.SUN_P
    for k in range(9):
        a = 2 * math.pi * k / 9 + g.uniform(-0.25, 0.25)
        dist = g.uniform(55, 150)
        others.append((px + math.cos(a) * dist, py + math.sin(a) * dist * 0.7))
    tx, ty = others[5]
    place(send, glitch(subseed(40), 1.0, 900, 3600), T("S06"), 0.16, xpos_pan(px))
    place(send, ping(subseed(41), 587.33, 0.5), T("S06"), 0.07, xpos_pan(px))
    cue(T("S06"), "S06", "le neurone (place du soleil) s'allume", "étincelle glitch + tintement ré5")
    sz = sizzle(subseed(42), T("S06", 15) - T("S06", 6), xpos_pan(px), xpos_pan(tx), 1400, 2600)
    place(send, sz, T("S06", 6), 0.05)
    cue(T("S06", 6), "S06", f"une étincelle part vers le voisin ({tx:.0f},{ty:.0f})", "flux granulaire qui suit l'étincelle (panoramique)")
    place(send, glitch(subseed(43), 1.0, 1200, 4200), T("S06", 15), 0.14, xpos_pan(tx))
    place(send, ping(subseed(44), 880.0, 0.35), T("S06", 15), 0.05, xpos_pan(tx))
    cue(T("S06", 15), "S06", "le voisin s'allume", "étincelle glitch + tintement la5")

    # ---- S08: cascade (exact schedule from build.cascade_state) ---------------------------------
    _, sparks = BLD.cascade_state(0)
    act_t = {2: 0}
    for (i, j, ts, dur) in sparks:
        act_t[j] = min(act_t.get(j, 999), ts + dur)
    pitch_l = {0: 587.33, 1: 880.0, 2: 932.33, 3: 1174.66}
    for k, (i, j, ts, dur) in enumerate(sorted(sparks, key=lambda s: (s[2], s[0], s[1]))):
        xi, yi, li = BLD.NODES[i]
        xj, yj, lj = BLD.NODES[j]
        tc = T("S08", ts)
        place(send, glitch(subseed(50, k), 1.0, 1000, 4500, nseg=3), tc, 0.07, xpos_pan(xi))
        place(send, sizzle(subseed(51, k), dur * 0.1, xpos_pan(xi), xpos_pan(xj), 1500, 2400), tc, 0.025)
    for ts in sorted(set(s[2] for s in sparks)):
        nb = sum(1 for s in sparks if s[2] == ts)
        cue(T("S08", ts), "S08", f"{nb} étincelle(s) partent (cascade)", "glitch court par étincelle + flux granulaire 0,4 s")
    for k, (j, ta) in enumerate(sorted(act_t.items(), key=lambda kv: (kv[1], kv[0]))):
        if ta >= NF["S08"]:
            continue
        xj, yj, lj = BLD.NODES[j]
        place(send, ping(subseed(52, k), pitch_l[lj] * 2 ** ((yj - 72) / 72 * 0.03), 0.18), T("S08", ta), 0.035, xpos_pan(xj))
    for ta in sorted(set(v for v in act_t.values() if v < NF["S08"])):
        nb = sum(1 for v in act_t.values() if v == ta)
        cue(T("S08", ta), "S08", f"{nb} nœud(s) s'allument", "tintement court (hauteur selon la couche)")

    # ---- ticking rhythm that accelerates with the editing (S09-S16) ----------------------------
    plan = [("S09", 0.4), ("S10", 0.3), ("S11", 0.25), ("S12", 0.2), ("S13", 0.16), ("S14", 0.7 / 6)]
    ticks = []
    for sid, step in plan:
        a, b = T(sid), T(sid) + NF[sid] * 0.1
        k = 0
        while a + k * step < b - 1e-6:
            ticks.append((a + k * step, sid, k == 0, step))
            k += 1
    t_turn0 = T("S15", 4)               # first visible rotation (30.1 s)
    t_turn1 = T("S15", 15)              # rotation complete (31.2 s)
    for k in range(4):
        ticks.append((T("S15", k), "S15", k == 0, 0.1))
    k = 0
    while t_turn1 + k * 0.1 < t_cut - 1e-6:
        tc = t_turn1 + k * 0.1
        ticks.append((tc, "S15" if tc < T("S16") - 1e-6 else "S16", abs(tc - T("S16")) < 1e-6, 0.1))
        k += 1
    for n_, (tc, sid, accent, step) in enumerate(ticks):
        u = (tc - T("S09")) / (t_cut - T("S09"))
        lvl = (0.09 + 0.08 * u) * (1.5 if accent else 1.0)
        place(dry, tick(subseed(60, n_), tock=(n_ % 2 == 1), bright=0.6 + 0.4 * u), tc, lvl, 0.12 if n_ % 2 else -0.12)
        place(send, tick(subseed(60, n_), tock=(n_ % 2 == 1)), tc, lvl * 0.4)
        if accent or step <= 0.2 + 1e-9 and (n_ % 2 == 0 or step > 0.15):
            place(dry, thump(52 if accent else 58, 0.25, 1.8, 0.07 if not accent else 0.1), tc, 0.2 + 0.1 * u)
    for sid, step in plan + [("S15", 0.1), ("S16", 0.1)]:
        nb = sum(1 for x in ticks if x[1] == sid)
        pause = " ; pause pendant la rotation 30,1-31,2 s" if sid == "S15" else ""
        cue(T(sid), sid, f"coupe (plan de {NF[sid] / 10:.1f} s)",
            f"tic-tac métallique tous les {step * 1000:.0f} ms ({nb} coups{pause}), pulsation grave sur les coups forts")

    # ---- S10: activation runs around the ring (one node per image, head = fi * 0.9) -------------
    cx, cy, R = BLD.WHEEL_C[0], BLD.WHEEL_C[1], BLD.WHEEL_R
    for fi in range(2, NF["S10"]):
        kk = int(math.floor(fi * 0.9)) % 12
        x = cx + math.cos(kk * math.pi / 6) * R
        tc = T("S10", fi)
        place(send, glitch(subseed(70, fi), 1.0, 1800, 4000, nseg=2), tc, 0.05, xpos_pan(x))
        place(send, ping(subseed(71, fi), 587.33 * 2 ** (kk / 12), 0.09, 0.3), tc, 0.05, xpos_pan(x))
    cue(T("S10", 2), "S10", "l'activation fait le tour de l'anneau (un nœud par image, 25,2-26,1 s)",
        "arpège chromatique montant de micro-blips (1 par image, hauteur = n° du nœud), panoramique = position")

    # ---- S11: amber power light wakes up (on = 1, 2, 3 at images 3, 4, 5) ----------------------
    lx = BLD.WHEEL_C[0] + 45
    t_led = T("S11", 3)
    place(dry, glitch(subseed(80), 1.0, 2000, 3000, nseg=1), t_led, 0.08, xpos_pan(lx))
    n_ = S(T("S12")) - S(t_led)
    t = np.arange(n_) / SR
    f = 1800 + 600 * np.clip(t / 0.2, 0, 1)
    whine = np.sin(TAU * np.cumsum(f) / SR) * np.clip(t / 0.2, 0, 1) ** 0.5 * (0.6 + 0.4 * np.exp(-t / 0.15))
    whine *= edges(n_, 0.002, 0.01)
    place(dry, whine, t_led, 0.012, xpos_pan(lx))
    cue(t_led, "S11", "le voyant ambre s'allume (3 paliers : 26,5 / 26,6 / 26,7 s)",
        "clic électrique + sifflement de mise sous tension qui monte 1,8 → 2,4 kHz puis tient")

    # ---- S12: sparks reach L and R, then leave to the right -------------------------------------
    src = [i for i in range(len(BLD.NODES)) if BLD.NODES[i][2] == 3]
    lp_, rp_ = BLD.z12(*BLD.NODES[BLD.OUT_L][:2]), BLD.z12(*BLD.NODES[BLD.OUT_R][:2])
    for k, i in enumerate(src):
        x, y = BLD.z12(BLD.NODES[i][0], BLD.NODES[i][1])
        for o, p in ((BLD.OUT_L, lp_), (BLD.OUT_R, rp_)):
            if (k + o) % 2 == 0:
                ts = k % 3
                place(send, glitch(subseed(90, k), 1.0, 1200, 4200, nseg=3), T("S12", ts), 0.08, xpos_pan(x))
                place(send, sizzle(subseed(91, k), 0.4, xpos_pan(x), xpos_pan(p[0]), 1600, 2800), T("S12", ts), 0.03)
    cue(T("S12"), "S12", "7 étincelles partent vers L et R (images 0, 1, 2)", "glitchs + flux granulaires (0,4 s)")
    for side, pan, fq in (("L", -0.35, 587.33), ("R", 0.35, 880.0)):
        place(send, ping(subseed(92, int(fq)), fq, 0.2), T("S12", 5), 0.07, pan)
        place(dry, glitch(subseed(93, int(fq)), 1.0, 2000, 3500, nseg=2), T("S12", 5), 0.06, pan)
    cue(T("S12", 5), "S12", "L et R s'allument (labels allumés)", "verrouillage : deux blips (ré5 à gauche, la5 à droite)")
    place(send, sizzle(subseed(94), 0.3, 0.5, 0.95, 2200, 3600), T("S12", 7), 0.06)
    cue(T("S12", 7), "S12", "les étincelles repartent vers la droite", "flux granulaire qui file à droite jusqu'à la coupe")

    # ---- riser into the wheel turn (28.2 -> 30.1) -------------------------------------------------
    ra, rb = T("S13"), t_turn0
    n_ = S(rb) - S(ra)
    t = np.arange(n_) / SR
    u = t / t[-1]
    z = np.vstack([noise(subseed(100, ch), n_) for ch in range(2)])
    rs = []
    for ch in range(2):
        rs.append(stft_filter(z[ch], lambda tc, f: bp_log(f, 300 * 2 ** (4.0 * np.clip(tc / t[-1], 0, 1)), 0.7)
                              * lp_mag(f, 7000, 2)))
    rs = rms_norm(np.vstack(rs), 0.035) * (u ** 2.2)
    trem = 0.75 + 0.25 * np.sin(TAU * np.cumsum(6 + 18 * u ** 2) / SR)
    fgl = 146.83 * 2 ** (2 * u ** 1.3)
    tone = sum(saw_additive(fgl * 2 ** (dc / 1200), 1200 + 2500 * u, np.ones(n_), 40, seed=subseed(101, dc))
               for dc in (-9, 0, 8))
    tone = rms_norm(tone, 0.028) * u ** 2 * trem
    riser = (rs + tone) * edges(n_, 0.01, 0.003)
    place(dry, riser, ra, 1.0)
    cue(ra, "S13", "début du montage le plus serré", "montée (riser) : souffle qui monte 300 Hz → 4,8 kHz + glissando ré3 → ré5, trémolo qui accélère")
    cue(rb, "S15", "fin de la montée", "la montée s'arrête net (fondu de 3 ms) sur le premier mouvement de la roue")

    # ---- S13: hub tremor (jit at images 3, 4, 5) and falling grains -----------------------------
    hx = BLD.HUB13[0]
    for k, (fi, a) in enumerate(((3, 1.0), (4, 0.64), (5, 0.36))):
        place(send, clank(subseed(110, k), 196.0, 0.8, 0.18, 1.0), T("S13", fi), 0.09 * a, xpos_pan(hx))
        place(dry, thump(62, 0.2, 1.6, 0.05), T("S13", fi), 0.15 * a)
    cue(T("S13", 3), "S13", "le moyeu tressaille (+1,3° / -0,8° / +0,5° aux images 3, 4, 5)", "trois chocs métalliques décroissants + coups sourds")
    g = BLD.Rng(BLD.SEED + 1313)
    for k in range(4):
        x0 = BLD.HUB13[0] + g.uniform(-30, 20)
        g.uniform(-2, 4)
        fi0 = math.floor(3 + k * 0.7) + 1
        place(send, glitch(subseed(111, k), 1.0, 3000, 5200, nseg=1), T("S13", fi0), 0.025, xpos_pan(x0))
    cue(T("S13", 4), "S13", "quelques grains tombent (apparition aux images 4, 4, 5, 6)", "micro-clics de sable")

    # ---- S14: impulse runs along the strut to the hub (29.0 -> 29.5), hub lights ----------------
    ax = BLD.STRUT_A[0]
    place(send, sizzle(subseed(120), 0.5, xpos_pan(ax), xpos_pan(cx), 900, 3200), T("S14"), 0.09)
    place(send, glitch(subseed(121), 1.0, 900, 3600), T("S14", 5), 0.16, xpos_pan(cx))
    place(dry, thump(49, 0.3, 2.4, 0.09), T("S14", 5), 0.3)
    cue(T("S14"), "S14", "l'influx file le long du bras", "flux granulaire qui monte 0,9 → 3,2 kHz et va de gauche au centre")
    cue(T("S14", 5), "S14", "l'influx atteint le moyeu, qui s'allume", "étincelle glitch forte + coup sourd")

    # ---- S15: the wheel turns 14 degrees ---------------------------------------------------------
    place(dry, boom(subseed(130), 36.71, 2.0, 3.0, 0.5), t_turn0, 0.36)
    place(send, clank(subseed(131), 73.42, 2.0, 0.9, 0.7), t_turn0, 0.17, 0.0)
    cue(t_turn0, "S15", "premier mouvement visible de la roue", "impact : boum sub (ré1, chute de hauteur) + choc métallique grave")
    # creak = stick-slip impulses whose rate follows the real angular velocity (smoothstep of build.s_turn)
    ta, tb = T("S15", 3), t_turn1
    n_ = S(tb) - S(ta) + SR // 2
    imp = np.zeros(n_)
    rr = Rng(subseed(132))
    tcur = 0.0
    dur_turn = tb - ta
    while tcur < dur_turn:
        uu = tcur / dur_turn
        v = 6 * uu * (1 - uu)                 # derivative of smoothstep (max 1.5)
        rate = 9 + 42 * v / 1.5
        imp[int(tcur * SR)] += (0.3 + 0.7 * v / 1.5) * rr.uniform(0.5, 1.0) * (1 if rr.unit() < 0.85 else -1)
        tcur += (1.0 / rate) * rr.uniform(0.75, 1.25)
    tir = np.arange(int(0.25 * SR)) / SR
    res = np.zeros(len(tir))
    for f_, d_, a_ in ((523, 0.05, 1.0), (1187, 0.035, 0.7), (1720, 0.028, 0.5), (2490, 0.02, 0.35),
                       (131, 0.09, 1.2), (287, 0.07, 0.9), (401, 0.06, 0.6)):
        res += a_ * np.sin(TAU * f_ * tir) * np.exp(-tir / d_)
    creak = conv(imp, res)[:n_]
    creak = creak / np.abs(creak).max()
    place(dry, creak, ta, 0.13, -0.1)
    place(send, creak, ta, 0.06)
    cue(ta, "S15", "rotation de 14° (30,0 → 31,2 s, vitesse max vers 30,6 s)",
        "grincement : impulsions de friction dont la cadence suit la vitesse réelle de la roue (9 → 51 /s)")
    # sand hiss ~ angular velocity, then the dust of S16 settling
    n_ = S(T("S17")) - S(ta)
    t = np.arange(n_) / SR
    uu = np.clip(t / dur_turn, 0, 1)
    v = np.where(t < dur_turn, 6 * uu * (1 - uu) / 1.5, 0.0)
    # visible dust: summed alpha of the kicked-up grains (S15) and of the settling dust (S16), per image
    g = BLD.Rng(BLD.SEED + 1515)
    for k in range(9):
        g.uniform(-1, 1)
    offs = [(g.uniform(0, 3), g.uniform(-0.9, -0.1), g.uniform(-0.75, -0.25)) for k in range(14)]
    g = BLD.Rng(BLD.SEED + 1616)
    offs16 = []
    for k in range(10):
        u0 = g.uniform(0, 4)
        g.uniform(-6, 2)
        g.uniform(-1, 1)
        offs16.append(u0)
    dfr, dval = [], []
    for fi in range(NF["S15"]):
        dfr.append(T("S15", fi) - ta)
        dval.append(sum(max(0.0, 0.9 - (fi - 5 - o[0]) / 14) for o in offs if 0 < fi - 5 - o[0] < 14))
    for fi in range(NF["S16"]):
        dfr.append(T("S16", fi) - ta)
        dval.append(sum(max(0.0, 0.7 - (fi + 6 + u0) / 26) for u0 in offs16))
    dval = np.array(dval) / max(dval)
    dust = np.interp(t, dfr, dval)
    env = v ** 0.8 + 0.3 * dust
    sand = []
    for ch in range(2):
        z = noise(subseed(133, ch), n_)
        sand.append(fft_filter(z, lambda f: bp_log(f, 3000, 1.0) * lp_mag(f, 7500, 3), pad=0))
    sand = rms_norm(np.vstack(sand), 0.03) * env
    place(dry, sand, ta, 1.0)
    cue(T("S15", 5), "S15", "le sable s'accumule, poussière", "souffle de sable = vitesse de la roue + opacité réelle de la poussière (S15-S16)")
    # grains falling off the tread: landing times from build.s_turn
    g = BLD.Rng(BLD.SEED + 1515)
    lim = BLD.WHEEL_C[1] + BLD.WHEEL_R - 4
    landed = []
    for k in range(9):
        a0 = math.pi * (1.05 + 0.07 * k)
        x0 = BLD.WHEEL_C[0] + math.cos(a0) * (BLD.WHEEL_R + 1) + g.uniform(-1, 1)
        y0 = BLD.WHEEL_C[1] + math.sin(a0) * (BLD.WHEEL_R + 1) + 20
        seen = False
        for fi in range(NF["S15"]):
            tt_ = fi - 5 - k * 0.8
            if tt_ > 0:
                y = y0 + 0.18 * tt_ * tt_
                if y < lim:
                    seen = True
                elif seen:
                    landed.append((fi, x0, k))
                    break
    for fi, x0, k in landed:
        place(send, glitch(subseed(134, k), 1.0, 2500, 5000, nseg=1), T("S15", fi), 0.04, xpos_pan(x0))
        place(dry, tick(subseed(135, k), True, 0.3), T("S15", fi), 0.025, xpos_pan(x0))
    if landed:
        when = " / ".join(f"{T('S15', l[0]):.1f}" for l in landed)
        cue(T("S15", landed[0][0]), "S15", f"{len(landed)} grains touchent le sable ({when} s)",
            "micro-clics de sable, un par grain")

    # ---- S15 end / S16: second build, ticks at 100 ms, then HARD CUT -----------------------------
    ra, rb = t_turn1, t_cut
    n_ = S(rb) - S(ra)
    t = np.arange(n_) / SR
    u = t / t[-1]
    fgl = 293.66 * 2 ** (1.0 * u)
    tone = sum(saw_additive(fgl * 2 ** (dc / 1200), 900 + 2200 * u, np.ones(n_), 40, seed=subseed(140, dc))
               for dc in (-11, 0, 10))
    tone2 = sum(saw_additive(fgl * 2 ** ((dc + 100) / 1200), 900 + 2200 * u, np.ones(n_), 40, seed=subseed(141, dc))
                for dc in (-6, 6))
    trem = 0.7 + 0.3 * np.sin(TAU * np.cumsum(10 + 20 * u) / SR)
    b2 = rms_norm(tone + 0.6 * tone2, 0.03) * (0.15 + 0.85 * u ** 2) * trem
    z = noise(subseed(142), n_)
    nz = stft_filter(z, lambda tc, f: bp_log(f, 500 * 2 ** (3.0 * np.clip(tc / t[-1], 0, 1)), 0.8) * lp_mag(f, 7000, 2))
    b2 = b2 + rms_norm(nz, 0.024) * u ** 2.5
    place(dry, b2 * edges(n_, 0.05, 0.004), ra, 1.0)
    cue(ra, "S15", "la roue s'immobilise", "deuxième montée : cluster ré4 → ré5 (avec seconde mineure) + souffle, tic-tac à 100 ms")
    cue(t_cut, "S17", "fondu au noir", "COUPURE SÈCHE : silence numérique total (0) jusqu'à 34,4 s")

    # ---- title: reverse swell, BRAAM, ringing tail ----------------------------------------------
    ir_big = reverb_ir(subseed(150), 4.5, 4.2, 1.6)
    # reverse swell (reversed reverb of a soft impact), 34.4 -> 34.7
    hit = boom(subseed(151), 36.71, 0.3, 2.0, 0.08)
    rv = np.vstack([conv(hit, ir_big[ch])[:int(1.2 * SR)][::-1] for ch in range(2)])
    L = S(t_title) - S(T("S18"))
    rv = rv[:, -L:] * edges(L, 0.12, 0.002)
    place(dry, rms_norm(rv, 0.06) * np.linspace(0.3, 1, L) ** 2, T("S18"), 1.0)
    cue(T("S18"), "S18", "fond du titre (noir)", "aspiration : réverbération inversée qui monte en 0,3 s")

    n_ = int(4.2 * SR)
    t = np.arange(n_) / SR
    fc = 85 + 1700 * (1 - np.exp(-t / 0.03)) * np.exp(-t / 0.5) + 380 * np.exp(-t / 2.5)
    amp = (1 - np.exp(-t / 0.008)) * (0.25 * np.exp(-t / 0.18) + 0.75 * np.where(t < 0.55, 1.0, np.exp(-(t - 0.55) / 1.3)))
    growl = 1 + 0.2 * np.sin(TAU * 27.5 * t) * np.exp(-t / 1.0)
    braam = np.zeros((2, n_))
    for vi, (f0, a) in enumerate(((36.71, 0.7), (73.42, 0.9), (110.0, 0.65), (146.83, 0.55), (174.61, 0.3),
                                  (220.0, 0.25), (293.66, 0.15))):
        for di, (dc, pan) in enumerate(((-7, -0.55), (0, 0.0), (6, 0.55))):
            fr = f0 * 2 ** (dc / 1200) * (1 + 0.025 * np.exp(-t / 0.06))
            y = saw_additive(fr, fc, amp * a, 260, 3e-4, seed=subseed(160, vi, di))
            gl, gr = pan_gains(pan)
            braam[0] += y * gl
            braam[1] += y * gr
    braam = np.tanh(3.0 * braam * growl / np.abs(braam).max()) / math.tanh(3.0)
    sub = np.sin(TAU * np.cumsum(36.71 * (1 + 0.8 * np.exp(-t / 0.04))) / SR) * np.exp(-t / 1.8) * (1 - np.exp(-t / 0.003))
    imp = noise(subseed(161), n_) * np.exp(-t / 0.02)
    imp = fft_filter(imp, lambda f: lp_mag(f, 1500, 2), pad=0)
    braam = braam * 0.8 + 0.38 * sub + 0.22 * imp / np.abs(imp).max()
    braam *= edges(n_, 0.0, 0.3)
    place(dry, braam, t_title, 0.72)
    place(big, braam, t_title, 0.22)
    cue(t_title, "S18", "« SOL-0 » apparaît (premier palier ambre)",
        "BRAAM : accord de cuivres synthétiques ré1-ré2-la2-ré3-fa3-la3-ré4 (scies additives, filtre qui s'ouvre puis se referme, grondement 27,5 Hz) + sub + impact")
    # ringing tail: inharmonic bell partials on D, with beating pairs
    n_ = int(4.2 * SR)
    t = np.arange(n_) / SR
    ring = np.zeros(n_)
    rr = Rng(subseed(170))
    for ratio, a, d_ in ((0.5, 0.5, 5.0), (1.0, 0.6, 3.6), (1.2, 0.35, 3.0), (1.5, 0.22, 2.4), (2.0, 0.3, 2.2),
                         (2.5, 0.12, 1.4), (2.67, 0.1, 1.2), (3.0, 0.08, 1.0), (4.0, 0.05, 0.7)):
        for det in (-0.35, 0.35):
            ring += a * np.sin(TAU * (587.33 * ratio + det) * t + rr.uniform(0, TAU)) * np.exp(-t / d_)
    ring *= (1 - np.exp(-t / 0.002)) * edges(n_, 0.0, 0.3)
    ring /= np.abs(ring).max()
    place(dry, ring, t_title, 0.05, 0.1)
    place(big, ring, t_title, 0.12)
    cue(t_title, "S18", "le titre s'éclaire par paliers (34,7 → 35,7 s)", "traîne qui sonne : partiels de cloche sur ré5, battements lents, grande réverbération")
    # hook: one last tick and a soft aftershock
    place(dry, tick(subseed(180), False, 0.7), t_hook, 0.12, -0.1)
    place(big, tick(subseed(180), False, 0.7), t_hook, 0.2)
    place(dry, thump(36.71, 0.8, 2.0, 0.25), t_hook, 0.25)
    place(big, ping(subseed(181), 1174.66, 0.9), t_hook, 0.05, 0.2)
    cue(t_hook, "S18", "l'accroche « WATCH IT LEARN. LIVE. 96 SOLS A DAY. » apparaît",
        "un dernier tic (réverbéré) + réplique grave douce + tintement ré6")

    # ---- reverbs -----------------------------------------------------------------------------------
    ir_room = reverb_ir(subseed(190), 2.0, 1.6, 0.7)
    big = np.vstack([fft_filter(ch, lambda f: hp_mag(f, 160, 2), pad=0) for ch in big])    # no sub in the hall
    mix = dry + send * 0.55 + reverb(send, ir_room, 0.9) + reverb(big, ir_big, 1.0)
    return mix, (t_cut, T("S18"), t_title, t_hook)


# ------------------------------------------------------------------------------------------ mastering & measures
B1 = (1.53512485958697, -2.69169618940638, 1.19839281085285)
A1 = (1.0, -1.69065929318241, 0.73248077421585)
B2 = (1.0, -2.0, 1.0)
A2 = (1.0, -1.99004745483398, 0.99007225036621)


def kweight_mag(f):
    z = np.exp(-1j * TAU * f / SR)

    def H(b, a):
        return (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return np.abs(H(B1, A1) * H(B2, A2))


def loudness(x):
    """Approximate BS.1770 integrated loudness (zero-phase K-weighting magnitude, 400 ms gated blocks)."""
    y = np.vstack([fft_filter(ch, kweight_mag, pad=0) for ch in x])
    n = y.shape[1]
    cs = np.concatenate([np.zeros((2, 1)), np.cumsum(y ** 2, axis=1)], axis=1)

    def blocks(sec, hop):
        blk, hp = int(sec * SR), int(hop * SR)
        st = np.arange(0, n - blk + 1, hp)
        z = (cs[:, st + blk] - cs[:, st]) / blk
        return st, z.sum(0)
    st, s = blocks(0.4, 0.1)
    l = -0.691 + 10 * np.log10(s + 1e-20)
    g1 = l > -70
    lr = -0.691 + 10 * np.log10(s[g1].mean()) - 10
    g2 = g1 & (l > lr)
    integ = -0.691 + 10 * np.log10(s[g2].mean())
    st3, s3 = blocks(3.0, 0.1)
    short = -0.691 + 10 * np.log10(s3 + 1e-20)
    return integ, l, short


def limiter(x, ceil, look=0.006):
    """Look-ahead peak limiter (guaranteed ceiling): sliding min of the needed gain + box smoothing,
    combined with a slower release envelope computed on 32-sample blocks."""
    a = np.abs(x).max(0)
    need = np.minimum(1.0, ceil / np.maximum(a, 1e-12))
    W = int(look * SR)
    m = need.copy()
    span = 1
    while span < W:                         # sliding min over [i, i + W)
        sh = min(span, W - span)
        m[:-sh] = np.minimum(m[:-sh], m[sh:])
        span += sh
    cs = np.concatenate([[0.0], np.cumsum(m)])
    idx = np.arange(len(m))
    lo = np.maximum(idx - W + 1, 0)
    box = (cs[idx + 1] - cs[lo]) / (idx + 1 - lo)
    # slow release on blocks
    B = 32
    nb = len(box) // B + 1
    pad = np.concatenate([box, np.ones(nb * B - len(box))])
    bm = pad.reshape(nb, B).min(1)
    rel = math.exp(-B / (0.12 * SR))
    env = np.empty(nb)
    g = 1.0
    for i in range(nb):
        v = bm[i]
        g = v if v < g else v + (g - v) * rel
        env[i] = g
    slow = np.repeat(env, B)[:len(box)]
    gain = np.minimum(box, slow)
    return x * gain, float(gain.min()), int(np.argmin(gain))


def master(mix, cut_times, target=-15.0):
    t_cut, t_s18, t_title, t_hook = cut_times
    x = np.vstack([fft_filter(ch, lambda f: hp_mag(f, 26, 2) * lp_mag(f, 11000, 2), pad=0) for ch in mix])
    fade = auto([(0, 0), (0.6, 1), (N / SR - 2.6, 1), (N / SR, 0)])
    fade = 0.5 - 0.5 * np.cos(np.pi * fade)
    x *= fade
    i0, i1 = S(t_cut), S(t_s18)
    x[:, i0 - int(0.004 * SR):i0] *= np.linspace(1, 0, int(0.004 * SR))
    x[:, i0:i1] = 0.0
    ceil = 10 ** (-1.3 / 20)
    gain = 1.0
    for it in range(6):
        y, gmin, imin = limiter(x * gain, ceil)
        integ, _, _ = loudness(y)
        if abs(integ - target) < 0.15:
            break
        gain *= 10 ** ((target - integ) / 20)
    y[:, i0:i1] = 0.0
    y[:, -1] = 0.0
    y[:, 0] = 0.0
    return y, gain, gmin, integ, imin / SR


def write_wav(path, x):
    q = np.clip(np.round(x * 32767.0), -32768, 32767).astype("<i2")
    inter = np.empty(q.shape[1] * 2, dtype="<i2")
    inter[0::2], inter[1::2] = q[0], q[1]
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(inter.tobytes())
    return q


def report(q, cut_times):
    x = q.astype(np.float64) / 32768.0
    t_cut, t_s18, t_title, t_hook = cut_times
    db = lambda v: 20 * math.log10(max(v, 1e-12))
    print(f"samples: {x.shape[1]} ({x.shape[1] / SR:.4f} s), 48 kHz, 16-bit, stereo")
    pk = np.abs(x).max()
    print(f"sample peak: {db(pk):.2f} dBFS ; clipped samples (|q| = 32767/32768): {int((np.abs(q) >= 32767).sum())}")
    tp = 0.0
    for ch in x:
        X = np.fft.rfft(ch)
        Y = np.zeros(len(ch) * 2 + 1, dtype=complex)
        Y[:len(X)] = X
        tp = max(tp, np.abs(np.fft.irfft(Y, len(ch) * 4) * 4).max())
    print(f"true peak (x4 FFT oversampling, approx.): {db(tp):.2f} dBTP")
    integ, mom, short = loudness(x)
    print(f"integrated loudness (approx. K-weighting, gated): {integ:.1f} LUFS ; max short-term (3 s): {short.max():.1f} LUFS ;"
          f" max momentary (400 ms): {mom.max():.1f} LUFS")
    print("RMS / peak per shot (dBFS):")
    for sid, f0, n in SHOTS:
        a, b = f0 * FRAME, (f0 + n) * FRAME
        seg = x[:, a:b]
        r = math.sqrt(float(np.mean(seg ** 2)))
        mm = mom[f0:f0 + n - 3]                      # 400 ms blocks lying inside the shot
        print(f"  {sid} {f0 / 10:5.1f}-{(f0 + n) / 10:5.1f} s  RMS {db(r):6.1f}  peak {db(float(np.abs(seg).max())):6.1f}"
              f"  max momentary {float(mm.max()):6.1f} LUFS")
    i0, i1 = S(t_cut), S(t_s18)
    print(f"silence {t_cut:.3f}-{t_s18:.3f} s: max |sample| = {int(np.abs(q[:, i0:i1]).max())} (0 = digital silence)")
    print(f"first / last sample: {q[:, 0].tolist()} / {q[:, -1].tolist()} ; first 10 ms peak {db(float(np.abs(x[:, :480]).max())):.1f} dBFS ;"
          f" last 100 ms peak {db(float(np.abs(x[:, -4800:]).max())):.1f} dBFS")
    blk = int(0.4 * SR)
    nb = x.shape[1] // blk
    m = x[:, :nb * blk].mean(0).reshape(nb, blk) * np.hanning(blk)
    P = np.abs(np.fft.rfft(m, axis=1)) ** 2
    f = np.fft.rfftfreq(blk, 1 / SR)
    hf = P[:, f > 12000].sum(1)
    tot = P.sum(1) + 1e-20
    ratio = 10 * np.log10(hf / tot + 1e-20)
    ok = tot > tot.max() * 1e-6
    print(f">12 kHz energy vs block total (400 ms blocks): max {ratio[ok].max():.1f} dB ; blocks above -20 dB: "
          f"{int((ratio[ok] > -20).sum())}/{int(ok.sum())}")
    # onset check on accented cues: biggest rise of a 3 ms energy envelope within +-100 ms
    env = np.sqrt(np.convolve((x ** 2).sum(0), np.ones(144) / 144, mode="same"))
    out = []
    for name, tc in (("S09 cut", T("S09")), ("S12 cut", T("S12")), ("S14 hub", T("S14", 5)), ("wheel 30.1", T("S15", 4)),
                     ("S16 cut", T("S16")), ("braam", t_title), ("hook", t_hook)):
        a, b = S(tc - 0.03), S(tc + 0.3)
        base, top = float(env[a]), float(env[a:b].max())
        k = a + int(np.argmax(env[a:b] >= base + 0.5 * (top - base)))
        out.append(f"{name} {1000 * (k / SR - tc):+.0f} ms ({20 * math.log10(top / max(base, 1e-9)):+.0f} dB)")
    print("onset check (3 ms envelope reaches half its rise, window -30/+300 ms): " + " ; ".join(out))
    return integ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "trailer"))
    ap.add_argument("--gif", default=os.path.join(ROOT, "assets", "trailer.gif"))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--cues", action="store_true")
    a = ap.parse_args()
    ms, nframes = gif_duration_ms(a.gif)
    assert ms * SR // 1000 == N, f"GIF {ms} ms != build schedule {N / SR} s"
    print(f"GIF: {nframes} frames, {ms} ms -> {N} samples")
    mix, cut_times = build_score()
    y, gain, gmin, integ, tmin = master(mix, cut_times)
    print(f"master gain {20 * math.log10(gain):+.1f} dB ; max limiter reduction {20 * math.log10(gmin):.1f} dB at {tmin:.2f} s")
    os.makedirs(a.out, exist_ok=True)
    q = write_wav(os.path.join(a.out, "soundtrack.wav"), y)
    if a.report:
        report(q, cut_times)
    if a.cues:
        print("| t (s) | plan | image | son |")
        print("|---|---|---|---|")
        for t, sid, img, snd in sorted(CUES, key=lambda c: c[0]):
            print(f"| {t:.3f} | {sid} | {img} | {snd} |")


if __name__ == "__main__":
    main()
