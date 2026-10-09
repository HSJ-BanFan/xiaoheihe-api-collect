"""Pure-Python Web signer for Xiaoheihe (Heybox) Web/Creator platform.

Completely independent of Android SO, Java, JAR, or Unidbg.
Reconstructed from Xiaoheihe Creator SPA bundle (index-BQ64EhAG.js).

Provides:
- Web lightweight quadruple generation (_time, nonce, hkey, _rnd)
- Tencent COS V5 upload authorization
"""
from __future__ import annotations

import hashlib
import hmac
import random
import time

R_CHARSET = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"
RND_KEY = "Z7mFG4tQp9Ws2LxB8H"
NONCE_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _ty(e: int) -> int:
    return ((e << 1) ^ 27) & 255 if (e & 128) else (e << 1)


def _da(e: int) -> int:
    return _ty(e) ^ e


def _vs(e: int) -> int:
    return _da(_ty(e))


def _dol_c(e: int) -> int:
    return _vs(_da(_ty(e)))


def _dl(e: int) -> int:
    return _dol_c(e) ^ _vs(e) ^ _da(e)


def _mix_columns(e: list[int]) -> list[int]:
    t = [0, 0, 0, 0]
    t[0] = _dl(e[0]) ^ _dol_c(e[1]) ^ _vs(e[2]) ^ _da(e[3])
    t[1] = _da(e[0]) ^ _dl(e[1]) ^ _dol_c(e[2]) ^ _vs(e[3])
    t[2] = _vs(e[0]) ^ _da(e[1]) ^ _dl(e[2]) ^ _dol_c(e[3])
    t[3] = _dol_c(e[0]) ^ _vs(e[1]) ^ _da(e[2]) ^ _dl(e[3])
    e[0], e[1], e[2], e[3] = t[0], t[1], t[2], t[3]
    return e


def _tw(s: str, charset: str, n: int) -> str:
    sub = charset[:n]
    return "".join(sub[ord(ch) % len(sub)] for ch in s)


def _rw(s: str, charset: str) -> str:
    return "".join(charset[ord(ch) % len(charset)] for ch in s)


def _interleave(arr: list[str]) -> str:
    max_len = max(len(s) for s in arr)
    out = []
    for i in range(max_len):
        for s in arr:
            if i < len(s):
                out.append(s[i])
    return "".join(out)


def calc_hkey(path: str, timestamp: int, nonce: str) -> str:
    """Compute web hkey according to Creator SPA Ow.g logic."""
    clean_path = "/" + "/".join(p for p in path.split("/") if p) + "/"
    t_val = timestamp + 1  # Ow.g uses t + 1
    part_t = _tw(str(t_val), R_CHARSET, -2)
    part_path = _rw(clean_path, R_CHARSET)
    part_nonce = _rw(nonce, R_CHARSET)
    interleaved = _interleave([part_t, part_path, part_nonce])[:20]
    digest = hashlib.md5(interleaved.encode("utf-8")).hexdigest()

    last6 = [ord(ch) for ch in digest[-6:]]
    transformed = _mix_columns(last6)
    u_val = sum(transformed) % 100
    u_str = f"{u_val:02d}"
    l_str = _tw(digest[:5], R_CHARSET, -4)
    return l_str + u_str


def calc_rnd(nonce: str, timestamp: int) -> str:
    """Compute web _rnd (HMAC-SHA256 with fixed secret key)."""
    time_nonce = f"{timestamp}:{nonce}"
    msg = (RND_KEY + nonce + time_nonce).encode("utf-8")
    sig = hmac.new(RND_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return "15:" + sig


def generate_nonce(length: int = 32) -> str:
    return "".join(random.choice(NONCE_CHARS) for _ in range(length))


def sign_web_request(path: str, timestamp: int | None = None, nonce: str | None = None) -> dict[str, str]:
    """Produce the pure Web quadruple dict: _time, nonce, hkey, _rnd, version."""
    now = int(timestamp if timestamp is not None else time.time())
    rnd_nonce = nonce or generate_nonce()
    hkey = calc_hkey(path, now, rnd_nonce)
    rnd = calc_rnd(rnd_nonce, now)
    return {
        "_time": str(now),
        "nonce": rnd_nonce,
        "hkey": hkey,
        "_rnd": rnd,
        "version": "999.0.4",
    }
