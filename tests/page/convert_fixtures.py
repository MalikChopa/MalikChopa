#!/usr/bin/env python3
"""One-off: rewrite the page fixtures (L1 page-side format) into the PRODUCER format of rover.live.views (FIXLIVE, 2026-11-12).
Lossless for what the page draws. Differences handled: so (vector) -> so + sd; m1 flat -> [[pred x3],[meas x3]]; arm string + ad ->
arm {d, p}; w string -> {m0}; lm {g: type+1, 0 unknown} -> {d: type, 255 unknown}; sn triplets -> sn pairs + snt; scan0 pts -> xy/labels/ids.
Idempotent: events already in producer format are left alone. Usage: convert_fixtures.py [dir]"""
import base64, gzip, json, sys
from pathlib import Path


def conv(e):
    if e.get("e") == "sol":
        if isinstance(e.get("w"), str):
            e["w"] = {"m0": e["w"]}
        sc = e.get("scan0")
        if sc and "pts" in sc:
            pts = sc.pop("pts")
            ax = sc.pop("ax")
            sc.update({"n": len(pts), "explained": ax / 100.0, "xy": [[p[1], p[2]] for p in pts], "labels": [p[3] for p in pts],
                       "ids": [p[0] for p in pts]})
    elif e.get("e") == "tick":
        if isinstance(e.get("so"), list):
            so = e["so"]
            e["so"] = so[0]
            e["sd"] = so[1:]
        if e.get("m1") is not None and e["m1"] and not isinstance(e["m1"][0], list):
            e["m1"] = [e["m1"][:3], e["m1"][3:]]
        if "ad" in e or "arm" in e:
            ad = e.pop("ad", None)
            arm = e.pop("arm", None)
            if isinstance(arm, str):
                e["arm"] = {"d": ad, "p": arm}
        if e.get("lm") and "g" in e["lm"]:
            g = base64.b64decode(e["lm"].pop("g"))
            e["lm"]["d"] = base64.b64encode(bytes(255 if v == 0 else v - 1 for v in g)).decode()
        sn = e.get("sn")
        if sn and not isinstance(sn[0], list):
            e["sn"] = [[sn[i], sn[i + 1]] for i in range(0, len(sn), 3)]
            e["snt"] = [sn[i + 2] for i in range(0, len(sn), 3)]
    return e


def main(d):
    for f in sorted(Path(d).glob("*.ndjson.gz")):
        ls = [json.loads(x) for x in gzip.decompress(f.read_bytes()).decode().split("\n") if x]
        out = "".join(json.dumps(conv(e), separators=(",", ":"), allow_nan=False) + "\n" for e in ls).encode()
        f.write_bytes(gzip.compress(out, 9, mtime=0))
        print(f.name, len(ls))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "fixtures")
