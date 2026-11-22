"""Pack complete road strokes and roadside silhouettes as lossless bitmap tiles."""

from collections import defaultdict
from functools import lru_cache
from struct import pack

from course import actors, sprite_shape
from kerbs import FIRST, LINES, bands, masks, ribbons, surface
from route import drift

EMPTY = bytes(8)
SHAPE_BASE = 0xc000  # Bank 6
ATLAS = 0xc000       # Bank 0


@lru_cache(None)
def object_cells(pose, course):
    objects = []
    for kind, height, x, top, first, end, scale in actors(pose, course):
        # Keep the parallax depth with each sprite. Align its origin to a ULA
        # column and its cropped crest silhouette to a four-line boundary.
        x = (x + 4) // 8 * 8
        top = (top + 2) // 4 * 4
        cells = defaultdict(lambda: [0, bytearray(8)])
        rows = sprite_shape(kind, height)[1]
        for i, (style, runs) in enumerate(rows[first:end], first):
            y = top + i
            if not FIRST <= y < FIRST + LINES:
                continue
            for dx, length in runs:
                for pixel in range(x + dx, x + dx + length):
                    cell = cells[y // 8 - FIRST // 8, pixel // 8]
                    cell[0] = style
                    cell[1][y % 8] |= 128 >> (pixel % 8)
        objects.append((scale, tuple((row, col, style, bytes(bits))
                                     for (row, col), (style, bits) in cells.items())))
    return objects


def depth_data(rows):
    # A nibble normally advances by 0..14 in inverse depth. Escape absolute
    # phases at the distant end. The Z80 reads the stream from the tyres upward.
    nibbles = []
    previous = 0
    for row in reversed(rows):
        if row is None:
            continue
        value = row[2]
        delta = (value - previous) & 31
        if delta < 15:
            nibbles.append(delta)
        else:
            nibbles.extend((15, value >> 4, value & 15))
        previous = value
    if len(nibbles) % 2:
        nibbles.append(0)
    return bytes((a << 4) + b for a, b in zip(nibbles[::2], nibbles[1::2]))


def compile_scene(out, course):
    uses = set()
    width_pairs = {(2, 2)}
    extents = defaultdict(set)
    for pose in range(256):
        _, points = bands(pose, course)
        for a, b in zip(points, points[1:]):
            for lane in range(8, 249):
                for start, end, width, next_width, _ in ribbons(a, b, lane):
                    slope = end - start
                    pair = width, next_width
                    extents[pair].add(slope)
                    if max(start, end) * 2 + max(pair) > 128 and min(start, end) * 2 < 384:
                        uses.add((slope, width, next_width, 2 * (start % 4)))
                        width_pairs.add(pair)

    pairs = sorted(width_pairs)
    slope_tables = {}
    table_size = 2 * len(pairs)
    for pair in pairs:
        low, high = min(extents[pair]), max(extents[pair])
        assert -32 <= low <= high < 32, "Slope exceeds the Z80 table index"
        slope_tables[pair] = SHAPE_BASE + table_size - 8 * (low + 32)
        table_size += 8 * (high - low + 1)
    tables = bytearray(table_size)
    for i, pair in enumerate(pairs):
        tables[2*i:2*i+2] = pack("<H", slope_tables[pair])

    packets = bytearray()
    packet_address = {}
    atlas = {EMPTY: 0}

    def glyph(bits):
        if bits not in atlas:
            atlas[bits] = len(atlas)
        return ATLAS + 8 * atlas[bits]

    for slope, width, next_width, phase in sorted(uses):
        origin, tiles = masks(slope, width, next_width, phase)
        assert -7 <= origin <= 0 and len(tiles) < 16
        style = 2 if width == 2 else 1
        packet = bytes([(-origin << 4) | len(tiles)]) + b"".join(
            pack("<H", glyph(tile) | style if any(tile) else 0) for tile in tiles
        )
        if packet not in packet_address:
            packet_address[packet] = SHAPE_BASE + len(tables) + len(packets)
            packets.extend(packet)
        index = slope_tables[width, next_width] - SHAPE_BASE + (slope + 32) * 8 + phase
        tables[index:index+2] = pack("<H", packet_address[packet])

    empty_packet = SHAPE_BASE + len(tables) + len(packets)
    packets.extend(bytes(2))
    for i in range(2 * len(pairs), len(tables), 2):
        if tables[i:i+2] == bytes(2):
            tables[i:i+2] = pack("<H", empty_packet)
    shapes = tables + packets
    if SHAPE_BASE + len(shapes) > 0xfe00:
        raise ValueError(f"{course} stroke lookup exceeds the free space in bank 6")
    (out / "shapes.bin").write_bytes(shapes)

    records = []
    meta = bytearray(2 * (LINES // 8 + 1))
    for pose in range(256):
        first, points = bands(pose, course)
        levels = depth_data(surface(pose, course))
        record = bytearray((first, len(points) - 1, len(levels))) + levels
        for i, (scale, left, right, mark, width, painted, _) in enumerate(points):
            table = 0 if i == len(points) - 1 else 2 * pairs.index((width, points[i+1][4]))
            j = 2 * (first // 8 + i)
            meta[j:j+2] = bytes((scale | (128 if painted else 0), table))
            record.extend((left, right, mark))
        objects = object_cells(pose, course)
        record.append(len(objects))
        for scale, cells in objects:
            record.extend((scale, len(cells)))
            for row, col, style, mask in cells:
                record.extend((row, col & 255))
                record.extend(pack("<H", glyph(mask) | style))
        assert len(record) <= 384, "Road record exceeds the native scene buffer"
        records.append(pack("<H", len(record)) + record)

    if len(atlas) > 2048:
        raise ValueError(f"{course} needs {len(atlas)} glyphs, exceeding bank 0")
    (out / "glyphs.bin").write_bytes(b"".join(atlas))

    # Reserve 1 KiB in bank 1 for the random-access course index.
    limits = {1: 15360, 3: 16384, 4: 16384}
    pages = {page: bytearray() for page in limits}
    index = [None] * 256
    for pose in sorted(range(256), key=lambda q: -len(records[q])):
        page = max(pages, key=lambda n: limits[n] - len(pages[n]))
        address = 0xc000 + len(pages[page])
        pages[page].extend(records[pose])
        assert len(pages[page]) <= limits[page], f"{course} overflows course bank {page}"
        steering = drift(pose // 4, course) * (1 if pose % 2 else 2)
        index[pose] = f"    dw {address}\n    db {16+page},{steering & 255}"
    for page, data in pages.items():
        (out / f"page{page}.bin").write_bytes(data)
    (out / "band-meta.bin").write_bytes(meta)
    (out / "course.inc").write_text("\n".join(index) + "\n")
    (out / "shape-layout.inc").write_text(
        f"CENTRE_BASE equ {slope_tables[2, 2]}\nSHAPE_BASE equ {SHAPE_BASE}\n"
    )
    print(course, "glyphs", len(atlas), "shape bytes", len(shapes),
          "course bytes", sum(map(len, records)), flush=True)
