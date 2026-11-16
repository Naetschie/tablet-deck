"""Prüft ein entpacktes Stock-Firmware-Paket gegen das, was das Tablet beim Booten verifiziert hat.

Kette: ro.boot.vbmeta.digest (vom Bootloader gemessen, Gerät gesperrt) == sha256(vbmeta.img)
  -> vbmeta ist echt  -> Hash-/Hashtree-Deskriptoren darin prüfen die übrigen Images.

Aufruf: python scripts/verify_stock.py <image-ordner> <vbmeta-digest-vom-gerät> [--hashtree]
Ohne --hashtree werden system/vendor (mehrere GB) übersprungen.
"""
import hashlib
import struct
import sys
from pathlib import Path


def parse_vbmeta(data):
    (magic, _maj, _min, auth_size, aux_size, alg) = struct.unpack(">4sLLQQL", data[:32])
    assert magic == b"AVB0", "kein vbmeta"
    fields = struct.unpack(">" + "Q" * 10, data[32:112])
    desc_off, desc_size = fields[8], fields[9]
    size = 256 + auth_size + aux_size
    aux = 256 + auth_size
    d = data[aux + desc_off: aux + desc_off + desc_size]
    out, i = [], 0
    while i < len(d):
        tag, n = struct.unpack(">QQ", d[i:i + 16])
        body = d[i + 16: i + 16 + n]
        if tag == 2:  # hash
            image_size, = struct.unpack(">Q", body[0:8])
            alg_name = body[8:40].rstrip(b"\0").decode()
            pn_len, salt_len, dig_len, _flags = struct.unpack(">LLLL", body[40:56])
            p = 56 + 60
            name = body[p:p + pn_len].decode(); p += pn_len
            salt = body[p:p + salt_len]; p += salt_len
            out.append(("hash", name, dict(size=image_size, alg=alg_name, salt=salt,
                                           digest=body[p:p + dig_len])))
        elif tag == 1:  # hashtree
            (_ver, image_size, tree_off, tree_size, dbs, hbs, _fec_roots, _fec_off, _fec_size) = \
                struct.unpack(">LQQQLLLQQ", body[0:56])
            alg_name = body[56:88].rstrip(b"\0").decode()
            pn_len, salt_len, dig_len, _flags = struct.unpack(">LLLL", body[88:104])
            p = 104 + 60
            name = body[p:p + pn_len].decode(); p += pn_len
            salt = body[p:p + salt_len]; p += salt_len
            out.append(("hashtree", name, dict(size=image_size, alg=alg_name, salt=salt, dbs=dbs,
                                               hbs=hbs, digest=body[p:p + dig_len])))
        elif tag == 4:
            out.append(("chain", body[8:].split(b"\0")[0].decode(errors="replace"), {}))
        elif tag == 3:
            out.append(("cmdline", "", {}))
        i += 16 + n
    return size, alg, out


def blocks(path, bs):
    """Liefert die Image-Daten blockweise; versteht Android-Sparse-Images (simg)."""
    with open(path, "rb") as f:
        hdr = f.read(28)
        magic, _ma, _mi, fhs, chs, blk, _tb, nchunks, _crc = struct.unpack("<LHHHHLLLL", hdr)
        if magic != 0xED26FF3A:
            f.seek(0)
            while chunk := f.read(bs):
                yield chunk
            return
        assert blk == bs, (blk, bs)
        f.seek(fhs)
        for _ in range(nchunks):
            ctype, _r, csz, tsz = struct.unpack("<HHLL", f.read(12))
            f.seek(chs - 12, 1)
            if ctype == 0xCAC1:      # Rohdaten
                for _ in range(csz):
                    yield f.read(bs)
            elif ctype == 0xCAC2:    # Füllmuster
                fill = f.read(4) * (bs // 4)
                for _ in range(csz):
                    yield fill
            elif ctype == 0xCAC3:    # "egal" = Nullen
                for _ in range(csz):
                    yield bytes(bs)
            else:                    # CRC-Chunk
                f.seek(tsz - chs, 1)


def hashtree_root(path, size, salt, dbs, hbs, alg):
    def h(b):
        return hashlib.new(alg, b)
    # dm-verity: jeder Hash wird auf die nächste Zweierpotenz aufgefüllt (sha1: 20 -> 32 Byte)
    dlen = hashlib.new(alg).digest_size
    pad = b"\0" * ((1 << (dlen - 1).bit_length()) - dlen)
    level = bytearray()
    for n, chunk in enumerate(blocks(path, dbs)):
        if n >= size // dbs:
            break
        level += h(salt + chunk).digest() + pad
    while True:
        if len(level) % hbs:
            level += b"\0" * (hbs - len(level) % hbs)
        if len(level) == hbs:
            return h(salt + bytes(level)).digest()
        level = bytearray(b"".join(h(salt + bytes(level[i:i + hbs])).digest() + pad
                                   for i in range(0, len(level), hbs)))


def main():
    img = Path(sys.argv[1])
    want = sys.argv[2].lower()
    deep = "--hashtree" in sys.argv
    vb = (img / "vbmeta.img").read_bytes()
    size, alg, descs = parse_vbmeta(vb)
    got = hashlib.sha256(vb[:size]).hexdigest()
    ok = got == want
    print(f"vbmeta.img  sha256={got}  {'== Gerät  OK' if ok else '!= Gerät  FEHLER'}  (alg={alg})")
    incomplete = False
    for kind, name, d in descs:
        f = img / f"{name}.img"
        if kind == "cmdline":
            continue
        if kind == "chain":
            # Chains gehören in den Digest und werden hier nicht unterstützt -> Ergebnis ungültig
            print("  chain-Deskriptor gefunden: nicht unterstützt, Prüfung ungültig")
            ok = False
            continue
        if not f.exists():
            print(f"  {kind:9} {name}: Datei fehlt  FEHLER")
            ok = False
            continue
        if kind == "hash":
            data = b"".join(blocks(f, 4096))[:d["size"]]
            r = hashlib.new(d["alg"], d["salt"] + data).digest() == d["digest"]
        else:
            if not deep:
                print(f"  hashtree  {name}: übersprungen (--hashtree)  UNVOLLSTÄNDIG")
                incomplete = True
                continue
            r = hashtree_root(f, d["size"], d["salt"], d["dbs"], d["hbs"], d["alg"]) == d["digest"]
        ok &= r
        print(f"  {kind:9} {name:10} {'OK' if r else 'FEHLER'}")
    print("Hinweis: Echtheit gilt nur für die oben gelisteten, per vbmeta abgedeckten Images.")
    sys.exit(1 if not ok else 2 if incomplete else 0)


if __name__ == "__main__":
    main()
