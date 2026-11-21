"""Build the bootable 128K TAP and debugger snapshot using SjASMPlus."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
from struct import pack

from course import FONT, generate

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def executable(explicit, variable, name, local_path):
    options = (explicit, os.getenv(variable), shutil.which(name), Path.home()/local_path)
    for option in options:
        if option and Path(option).is_file():
            return Path(option).resolve()
    raise SystemExit(f"Set {variable} to {name} or pass its path explicitly.")


def tape_block(flag, data):
    checksum = flag
    for byte in data:
        checksum ^= byte
    return pack("<HB", len(data)+2, flag) + data + bytes([checksum])


def header(kind, name, data, param1, param2):
    return (tape_block(0, pack("<B10sHHH", kind, name.ljust(10,b" "), len(data), param1, param2))
            + tape_block(255, data))


def basic_number(value):
    return str(value).encode() + b"\x0e\0\0" + pack("<H", value) + b"\0"


def build(assembler, out=BUILD):
    out.mkdir(parents=True, exist_ok=True)
    pages = generate(out)
    (out/"digits.bin").write_bytes(bytes(int(row,8)<<3 for n in range(10)
                                         for row in "0"+FONT[str(n)]+"0"))

    def assemble(source):
        subprocess.run([assembler, "--nologo", f"--inc={out}", f"--sym={source.stem}.sym", source],
                       cwd=out, check=True)

    assemble(ROOT/"src/racer.asm")
    blocks = [(0x10, 0x8000, "core.bin"), (0x10, 0x4000, "screen0.bin"),
              (0x17, 0xc000, "screen1.bin")]
    blocks += [(0x10+page, 0xc000, f"page{page}.bin") for page in pages]
    (out/"blocks.inc").write_text("".join(f"    db {latch}\n    dw {addr},{(out/file).stat().st_size}\n"
                                         for latch,addr,file in blocks))
    assemble(ROOT/"src/loader.asm")
    # CLEAR 28671 : LOAD "" CODE : RANDOMIZE USR 28672
    line = b'\xfd'+basic_number(0x6fff)+b':\xef""\xaf:\xf9\xc0'+basic_number(0x7000)+b'\r'
    basic = b"\x00\x0a" + pack("<H",len(line)) + line
    tap = header(0,b"Coast Run",basic,10,len(basic))
    tap += header(3,b"COAST RUN", (out/"loader.bin").read_bytes(),0x7000,0x8000)
    tap += b"".join(tape_block(255,(out/file).read_bytes()) for _,_,file in blocks)
    # SjASMPlus serialises the same bank payloads to its 128K SNA format.
    snapshot = out/"snapshot.asm"
    snapshot.write_text("    device ZXSPECTRUM128\n" + "".join(
        f'    page {latch & 7}\n    org {addr}\n    incbin "{file}"\n' for latch,addr,file in blocks)
        + '    page 0\n    savesna "coast-run.sna",#8000\n')
    assemble(snapshot)
    (out/"coast-run.tap").write_bytes(tap)
    print(f"Built {out/'coast-run.tap'} ({len(tap):,} bytes) and coast-run.sna")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembler", type=Path)
    args = parser.parse_args()
    build(executable(args.assembler,"SJASMPLUS","sjasmplus","Desktop/_temp/sjasmplus-1.20.2.win/sjasmplus.exe"))
