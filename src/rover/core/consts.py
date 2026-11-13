"""Frozen constants shared by several layers (SPEC 6.2, 3.4, 4.2, 7.1). FROZEN until J6: additions only."""

GTYPE_ROCK, GTYPE_SAND, GTYPE_DUST, GTYPE_ICE = 0, 1, 2, 3
GTYPE_NAMES = ("rock", "sand", "dust", "ice")
RAMP_BASE = {GTYPE_ROCK: 0, GTYPE_SAND: 6, GTYPE_DUST: 12, GTYPE_ICE: 12}
SKY = (18, 21)
DARK = (22, 23)
N_SENSOR_COLORS = 24

# Luminance (2R + 5G + B) // 8 of palette indices 0-23 (SPEC 7.1). Input of M2: never recomputed from the display palette.
CAM_LUT = (16, 35, 54, 75, 104, 135, 24, 65, 108, 151, 168, 186, 36, 90, 144, 199, 214, 229, 166, 147, 121, 99, 3, 18)

MODES = ("BABBLE", "DRIVE", "SEEK_SUN", "SLEEP", "SAFE", "DRILL", "ANALYZE")
MODE_LABELS = {
    "BABBLE": "MOTOR BABBLING",
    "DRIVE": "DRIVE TO TARGET",
    "SEEK_SUN": "SEEK SUN",
    "SLEEP": "SLEEP",
    "SAFE": "SAFE MODE",
    "DRILL": "DRILL",
    "ANALYZE": "ANALYZE",
}

# M0 input vector (24 values, SPEC 3.4): 0-1 enc_L enc_R; 2-3 pitch roll; 4 slip; 5-6 prev u; 7-14 visual features f0..f7;
# 15-17 target (cos, sin, dist); 18-21 battery, elev, cos(hour), sin(hour); 22-23 reserved P2.
_S0 = (0, 1, 4, 5, 6)
_S2 = (0, 1, 2, 3, 4, 5, 6) + tuple(range(7, 15)) + (15, 16, 17)
_S3 = _S2 + (18, 19, 20, 21)
# P2 (SPEC 6.14.1): inputs 22-23 stay masked at stages 4-5 (the arm feeds M4, not M0): same 22 inputs as stage 3.
M0_ACTIVE = (_S0, _S0, _S2, _S3, _S3, _S3)
M0_N_IN = 24

# ---- P2 additions (SPEC 6.14.1) -------------------------------------------------------------------------------------
# Colours 0-23 of the palette (SPEC 7.1), frozen: the arm image shows these indices, the descriptors read these values.
CAM_RGB = ((28, 13, 8), (64, 28, 15), (101, 43, 22), (138, 59, 30), (166, 90, 56), (194, 122, 82), (42, 20, 10), (100, 59, 31),
           (158, 100, 52), (217, 140, 74), (228, 159, 98), (240, 178, 122), (51, 32, 26), (114, 86, 63), (178, 140, 101),
           (242, 195, 139), (247, 211, 165), (253, 227, 192), (227, 154, 104), (216, 133, 79), (201, 103, 58),
           (168, 82, 46), (5, 3, 2), (28, 16, 11))
ARM_PATCH = 16
M4_N_IN = 10
NOVEL_MAX = 150         # window of the stage-4 criterion (samples kept in metrics.novel and metrics.chance)
# Columns of memory.samples (32): 0-4 id sol cx cy gtype | 5-9 features | 10-13 patch descriptors | 14 gain | 15 analysed | 16-31 bands.
SAMPLE_COLS = ("id", "sol", "cx", "cy", "gtype", "hard", "r", "g", "b", "grain", "d_r", "d_g", "d_b", "d_var", "gain",
               "analysed") + tuple("band%02d" % i for i in range(16))
# Structural limits of schema 2 (changing them = new schema).
M5_K_MAX = 15
SAMPLES_MAX = 4096
