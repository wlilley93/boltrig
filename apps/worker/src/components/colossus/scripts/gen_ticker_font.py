#!/usr/bin/env python3
"""Emit Colossus's ticker glyph atlas -- GLSL and TypeScript from ONE table.

WHY NOT REUSE JARVIS'S. His atlas lives inside bundles/jarvis/jarvis.frag, which
is byte-pinned by sha256 in jarvisBundle.test.ts, and its glyph ids are the
numbers his label tables are written against. Adding punctuation there would
break the pin and renumber his labels to give a different character a comma.
So Colossus gets his own, generated from the same 5x7 shapes plus the marks a
ticker actually needs.

BOTH SIDES FROM ONE SOURCE. A ticker is text uploaded as glyph INDICES, so the
CPU needs a char->id map and the GPU needs the bitmaps, and the two agreeing is
the whole thing working. Generating them separately is how a panel ends up
spelling something else. This writes one file exporting both.
"""

import sys

# The 26+10+3 shapes are Jarvis's, unchanged -- same font, so the two panels
# look like they came out of the same parts bin, which they did.
GLYPHS = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    # New for the ticker. A comma and a colon because his lines are clauses; a
    # slash and a plus and a percent because the readout is an instrument; and a
    # centred diamond as the separator between ticker phrases, which is what the
    # Forbin panels use to break one message from the next.
    ",": ["00000", "00000", "00000", "00000", "01100", "01100", "01000"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "%": ["11001", "11010", "00010", "00100", "01000", "01011", "10011"],
    "*": ["00000", "00100", "01110", "11111", "01110", "00100", "00000"],
}

# Index order IS the shader's glyph id AND the TypeScript map's value. Append
# only: a ticker string is compiled to ids on the CPU, so renumbering silently
# changes what the panel says.
ORDER = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-,:/+%*")

NAMES = {" ": "space", ".": "period", "-": "hyphen", ",": "comma",
         ":": "colon", "/": "slash", "+": "plus", "%": "percent",
         "*": "diamond"}


def pack(rows):
    """Two uints: .x holds rows 0..3, .y rows 4..6, MSB of each 5 = leftmost."""
    lo = hi = 0
    for n, row in enumerate(rows):
        bits = int(row, 2)
        if n < 4:
            lo |= bits << (5 * n)
        else:
            hi |= bits << (5 * (n - 4))
    return lo, hi


def main():
    for name, rows in GLYPHS.items():
        assert len(rows) == 7, f"{name}: expected 7 rows, got {len(rows)}"
        for row in rows:
            assert len(row) == 5 and set(row) <= {"0", "1"}, f"{name}: bad row {row!r}"
    assert len(ORDER) == len(set(ORDER)), "duplicate in ORDER"
    for ch in ORDER:
        assert ch in GLYPHS, f"ORDER names {ch!r} with no bitmap"

    n = len(ORDER)
    out = ['// Colossus\'s ticker glyph atlas.',
           '//',
           '// GENERATED by components/colossus/scripts/gen_ticker_font.py -- do not',
           '// hand-edit. Both halves come out of one table on purpose: the CPU compiles a',
           '// ticker string to glyph ids and the GPU draws the bitmaps for those ids, so a',
           '// map and an atlas that disagree is a panel confidently spelling something',
           '// else. Regenerate rather than patching one side.',
           '//',
           f'// {n} glyphs: 0..25 A-Z, 26..35 0-9, 36 space, then punctuation.',
           '',
           '/** Char -> glyph id. Anything absent becomes a space, never an exception:',
           ' *  a ticker is decoration on a running system and must not throw over a',
           ' *  character somebody typed. */',
           'const INDEX: Readonly<Record<string, number>> = {']
    for i, ch in enumerate(ORDER):
        key = '" "' if ch == " " else f'"{ch}"'
        out.append(f'  {key}: {i},')
    out += ['};', '',
            'export const TICKER_GLYPH_COUNT = %d;' % n,
            '',
            '/** Compile text to glyph ids. Case-folded up, unknowns to space. */',
            'export function glyphIds(text: string): number[] {',
            '  const upper = text.toUpperCase();',
            '  const ids: number[] = [];',
            '  for (const ch of upper) ids.push(INDEX[ch] ?? INDEX[" "]);',
            '  return ids;',
            '}',
            '',
            '/** The atlas and its sampler, spliced into the panel fragment shader. */',
            'export const GLYPH_GLSL = `',
            f'const int GLYPH_COUNT = {n};',
            f'const uvec2 FONT[{n}] = uvec2[{n}](']
    for i, ch in enumerate(ORDER):
        lo, hi = pack(GLYPHS[ch])
        comma = "," if i < n - 1 else ""
        out.append(f'    uvec2(0x{lo:05X}u, 0x{hi:04X}u){comma:<1}  // {i:2d}  {NAMES.get(ch, ch)}')
    out += [');',
            '',
            '// uv is 0..1 across one 5x7 cell. Returns 1 for a lit lamp, 0 for dark --',
            '// the CALLER decides what dark looks like, because on this panel an unlit',
            '// lamp is still faintly visible and that is most of the 70s in it.',
            'float glyphBit(int gid, vec2 uv) {',
            '    if (gid < 0 || gid >= GLYPH_COUNT) return 0.0;',
            '    if (uv.x < 0.0 || uv.x >= 1.0 || uv.y < 0.0 || uv.y >= 1.0) return 0.0;',
            '    int cx = int(uv.x * 5.0);',
            '    int ry = 6 - int(uv.y * 7.0);          // row 0 is the TOP row',
            '    uvec2 g = FONT[gid];',
            '    uint bits = (ry < 4) ? (g.x >> uint(5 * ry)) : (g.y >> uint(5 * (ry - 4)));',
            '    bits &= 31u;',
            '    return float((bits >> uint(4 - cx)) & 1u);',
            '}',
            '`;',
            '']
    sys.stdout.write("\n".join(out))


if __name__ == "__main__":
    main()
