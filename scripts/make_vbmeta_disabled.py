"""Erzeugt ein leeres AVB-vbmeta-Image mit abgeschalteter Prüfung (wie
`avbtool make_vbmeta_image --flags 3 --padding_size 4096`).

Header-Layout laut AOSP external/avb/libavb/avb_vbmeta_image.h (big-endian, 256 Byte).
Aufruf: python scripts/make_vbmeta_disabled.py <ausgabe.img>
"""
import struct
import sys

FLAGS = 1 | 2  # HASHTREE_DISABLED | VERIFICATION_DISABLED

header = struct.pack(
    ">4sLLQQL" + "Q" * 10 + "QLL48s80s",
    b"AVB0",
    1, 0,          # required libavb version major/minor
    0, 0,          # authentication / auxiliary block size
    0,             # algorithm NONE
    *([0] * 10),   # hash/signature/public key/metadata/descriptors offsets+sizes
    0,             # rollback_index
    FLAGS,
    0,             # rollback_index_location
    b"avbtool 1.3.0".ljust(48, b"\0"),
    b"\0" * 80,
)
assert len(header) == 256, len(header)
out = sys.argv[1]
with open(out, "wb") as f:
    f.write(header.ljust(4096, b"\0"))
print(f"{out}: 4096 Byte, flags={FLAGS}")
