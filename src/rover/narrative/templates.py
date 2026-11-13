"""Template choice, conditions and filling (SPEC 8.1): variant = u64(derive(seed, "journal", sol, crc32(id))) mod len."""
from __future__ import annotations

import re

import numpy as np

from rover.core.rng import derive, u64

_MARK = re.compile(r"\{(\w+)(?::(\d+))?\}")
_COND = re.compile(r"^(!?)(\w+)(?:(>=|<=|==|!=|>|<|=|:)(.+))?$")


def pick(variants: list, seed: int, sol: int, tid: str) -> str:
    key = derive(seed, "journal", sol, tid)
    return variants[int(u64(key, np.asarray(0))[()]) % len(variants)]


def _round_perm(n: int, seed: int, rnd: int, tid: str) -> list:
    """Fisher-Yates permutation of range(n), keyed by (seed, round, id)."""
    key = derive(seed, "journal-round", rnd, tid)
    perm = list(range(n))
    for i in range(n - 1, 0, -1):
        j = int(u64(key, np.asarray(i))[()]) % (i + 1)
        perm[i], perm[j] = perm[j], perm[i]
    return perm


def pick_index(n: int, seed: int, sol: int, tid: str) -> int:
    """Variant index of a line for a sol (stateless, deterministic).

    Sols are cut in rounds of n: each round plays every variant once, in a permutation drawn from (seed, round, id), so
    the variants are used evenly and two consecutive sols never get the same one (a round never starts with the last
    variant of the round before). n = 1 -> 0; n = 2 -> alternation whose phase is drawn from (seed, id). This replaces
    the plain `u64(...) mod n` of SPEC 8.1, which repeated a variant on a third of the sols for n = 3 (contract note).
    """
    if n <= 1:
        return 0
    if n == 2:
        return (int(u64(derive(seed, "journal-round", 0, tid), np.asarray(0))[()]) + sol) % 2
    rnd, pos = divmod(sol, n)
    perm = _round_perm(n, seed, rnd, tid)
    if pos <= 1 and rnd > 0 and perm[0] == _round_perm(n, seed, rnd - 1, tid)[-1]:
        perm[0], perm[1] = perm[1], perm[0]
    return perm[pos]


def markers(template: str) -> list:
    return [m.group(1) for m in _MARK.finditer(template)]


THIN_NBSP = "\u202f"      # FR thousands separator (narrow no-break space); EN uses ","


def group_thousands(s: str, lang: str) -> str:
    """Thousands separators on the integer part of a plain decimal string, the same rule in both languages."""
    sign = "-" if s.startswith("-") else ""
    body = s[len(sign):]
    ip, dot, frac = body.partition(".")
    if len(ip) > 3 and ip.isdigit():
        sep = THIN_NBSP if lang == "fr" else ","
        head = len(ip) % 3
        parts = ([ip[:head]] if head else []) + [ip[i:i + 3] for i in range(head, len(ip), 3)]
        ip = sep.join(parts)
    return sign + ip + ("," if lang == "fr" else ".") * bool(dot) + frac


def fmt_number(v, lang: str, decimals: int | None) -> str:
    if isinstance(v, bool) or isinstance(v, int):
        s = str(int(v))
    else:
        s = "%.*f" % (decimals, v) if decimals is not None else "%.6g" % v  # no silent rounding
    return group_thousands(s, lang)


def fill(template: str, facts: dict, lang: str, words: dict | None = None) -> str:
    """Fill {name} / {name:decimals}. A str value goes through words[name][lang] when that table exists."""
    words = words or {}

    def rep(m):
        name, dec = m.group(1), m.group(2)
        if name not in facts or facts[name] is None:
            raise KeyError(f"journal marker without fact: {name}")
        v = facts[name]
        if isinstance(v, (list, dict)):
            raise TypeError(f"journal marker {name} is not a scalar")
        if isinstance(v, str):
            tab = words.get(name)
            if tab is not None:
                return tab[lang][v]
            return v
        return fmt_number(v, lang, None if dec is None else int(dec))
    return _MARK.sub(rep, template)


def holds(cond: str, facts: dict) -> bool:
    """Evaluate one condition of a line's `when` list (see config/narrative/journal.toml header)."""
    m = _COND.match(cond)
    if m is None:
        raise ValueError(f"bad condition: {cond!r}")
    neg, key, op, arg = m.groups()
    v = facts.get(key)
    if op is None:
        ok = bool(v)
        return (not ok) if neg else ok
    if neg:
        raise ValueError(f"bad condition: {cond!r}")
    if op == ":":
        return isinstance(v, (list, tuple)) and arg in v
    if op == "=":
        return isinstance(v, str) and v == arg
    if v is None or isinstance(v, (str, list, dict)):
        return False
    x = float(arg)
    return {">=": v >= x, "<=": v <= x, "==": v == x, "!=": v != x, ">": v > x, "<": v < x}[op]


def condition_keys(cond: str) -> str:
    m = _COND.match(cond)
    if m is None:
        raise ValueError(f"bad condition: {cond!r}")
    return m.group(2)
