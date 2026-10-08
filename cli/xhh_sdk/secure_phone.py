"""RSA phone-number encryption for the app login endpoints.

The app does not send phone numbers in clear text. `com.max.xiaoheihe.utils.n0`
encrypts them with RSA/ECB/PKCS1Padding and Base64, using a public key that the
native library (`libnative-lib.so`, `NDKTools.getrsakey`) assembles at runtime
from a prefix held in .rodata, a 128-byte block, and a string passed from Java.

That DER key is embedded below (1024-bit, e=65537) so the same ciphertext can be
produced without the APK. Base64 keeps the trailing newline that Android's
`Base64.encodeToString(bytes, Base64.DEFAULT)` appends.
"""
from __future__ import annotations

import base64
import os
import re

from .exceptions import XhhConfigError

RSA_PUBLIC_DER = base64.b64decode(
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDZgjVwAiKTjZ55nG+mW6r3TSU4ECvNYqDMIS/bhCj"
    "2QaH5GI/KZb2TBp+CBvUj9SLFnmJQ0kzHzHoGZCQ88VevCffF7JePGF9cmKQqotlfTKbV4oxV5iLz"
    "7JSG6b/Vg7AXtrTolNtWsa8HiB0tI0YClYaQlOXm4UxLeSxQwSFETwIDAQAB")
_MODULUS_PREFIX = b"\x02\x81\x81"
_EXPONENT = b"\x02\x03\x01\x00\x01"
_PAD_BYTES = 128


def _public_numbers() -> tuple[int, int]:
    match = re.search(re.escape(_MODULUS_PREFIX) + b".{129}", RSA_PUBLIC_DER, re.S)
    if not match or _EXPONENT not in RSA_PUBLIC_DER:
        raise XhhConfigError("embedded RSA public key is malformed")
    modulus = int.from_bytes(match.group(0)[3:], "big")
    return modulus, 65537


def encrypt_phone(text: str, *, rng=os.urandom) -> str:
    """Encrypt a phone string the way the app does; returns Base64 plus newline."""
    message = str(text).encode("utf-8")
    if not message or len(message) > _PAD_BYTES - 11:
        raise XhhConfigError("phone value cannot be encrypted with this key")
    modulus, exponent = _public_numbers()
    padding = bytearray()
    while len(padding) < _PAD_BYTES - 3 - len(message):
        byte = rng(1)[0]
        if byte:
            padding.append(byte)
    block = b"\x00\x02" + bytes(padding) + b"\x00" + message
    cipher = pow(int.from_bytes(block, "big"), exponent, modulus)
    return base64.b64encode(cipher.to_bytes(_PAD_BYTES, "big")).decode("ascii") + "\n"
