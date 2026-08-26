"""
Encoding repair v2 — direct byte-pattern substitution.
Fixes double-UTF-8 encoding (UTF-8 bytes misread as cp1252, then re-encoded as UTF-8).
"""

import os
import sys

# Force UTF-8 output to avoid cp1252 console errors
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

SUBSTITUTIONS = [
    # ─ U+2500 BOX DRAWINGS LIGHT HORIZONTAL (cp1252 path)
    # e2 94 80 -> cp1252 -> c3a2 e2809d e282ac
    (bytes([0xc3, 0xa2, 0xe2, 0x80, 0x9d, 0xe2, 0x82, 0xac]), b'\xe2\x94\x80', 'U+2500 BOX_H'),

    # → U+2192 RIGHTWARDS ARROW (cp1252 path)
    # e2 86 92 -> cp1252 -> c3a2 e280a0 e28099
    (bytes([0xc3, 0xa2, 0xe2, 0x80, 0xa0, 0xe2, 0x80, 0x99]), b'\xe2\x86\x92', 'U+2192 ARROW'),

    # — U+2014 EM DASH (cp1252: 0x97 -> U+2014, stored e2 80 94)
    # e2 80 94 -> cp1252 -> c3a2 e28094 (0x80=U+20AC=e282ac, 0x94=U+201D=e2809d)
    # Wait: 0x80 in cp1252 = U+20AC, stored as e2 82 ac
    #        0x94 in cp1252 = U+201D, stored as e2 80 9d
    # So e2 80 94 -> c3a2 e282ac e2809d
    (bytes([0xc3, 0xa2, 0xe2, 0x82, 0xac, 0xe2, 0x80, 0x9d]), b'\xe2\x80\x94', 'U+2014 EM_DASH'),

    # – U+2013 EN DASH
    # e2 80 93 -> 0x80=U+20AC(e282ac), 0x93=U+201C(e2809c)
    (bytes([0xc3, 0xa2, 0xe2, 0x82, 0xac, 0xe2, 0x80, 0x9c]), b'\xe2\x80\x93', 'U+2013 EN_DASH'),

    # " U+201C (cp1252 0x93 -> U+201C -> e2809c)
    # e2 80 9c -> c3a2 e282ac c5 93
    # 0x80=U+20AC(e282ac), 0x9c=U+0153(c5 93)
    (bytes([0xc3, 0xa2, 0xe2, 0x82, 0xac, 0xc5, 0x93]), b'\xe2\x80\x9c', 'U+201C LEFT_DQ'),

    # " U+201D (cp1252 0x94 -> U+201D -> e2809d) — same as part of em-dash above
    # e2 80 9d -> c3a2 e282ac e2809d -- this overlaps with EM_DASH pattern, skip standalone

    # ' U+2019 RIGHT SINGLE QUOTE (cp1252 0x92 -> U+2019 -> e28099)
    # e2 80 99 -> c3a2 e282ac e28099 -- 0x80=e282ac, 0x99=e28099? No.
    # 0x80 in cp1252 = U+20AC (e2 82 ac), 0x99 in cp1252 = U+2122 (e2 84 a2)
    # Hmm. Let me derive properly.
    # original: e2 80 99
    # byte e2 = U+00E2 in cp1252... no. e2 as a cp1252 byte = U+00E2 (â)
    # 80 as cp1252 = U+20AC (€)
    # 99 as cp1252 = U+2122 (™)
    # stored as UTF-8: c3a2 e282ac e284a2
    (bytes([0xc3, 0xa2, 0xe2, 0x82, 0xac, 0xe2, 0x84, 0xa2]), b'\xe2\x80\x99', "U+2019 RIGHT_SQ"),

    # ' U+2018 LEFT SINGLE QUOTE
    # original: e2 80 98
    # 0x98 in cp1252 = U+02DC (ˆ... no, 0x98 = U+02DC? Let me check: 0x98 in cp1252 = U+02DC SMALL TILDE)
    # stored as UTF-8: c3a2 e282ac c2b8... hmm, 0x98 not standard
    # Skip for now — not seen in audit output

    # ✓ U+2713 CHECK MARK
    # original: e2 9c 93
    # 0x9c in cp1252 = U+0153 (œ) = c5 93
    # 0x93 in cp1252 = U+201C (") = e2 80 9c
    # stored: c3a2 c593 e2809c
    (bytes([0xc3, 0xa2, 0xc5, 0x93, 0xe2, 0x80, 0x9c]), b'\xe2\x9c\x93', 'U+2713 CHECK'),

    # ✗ U+2717 BALLOT X
    # original: e2 9c 97
    # 0x97 in cp1252 = U+2014 (—) = e2 80 94
    # stored: c3a2 c593 e28094
    (bytes([0xc3, 0xa2, 0xc5, 0x93, 0xe2, 0x80, 0x94]), b'\xe2\x9c\x97', 'U+2717 BALLOT_X'),

    # ● U+25CF BLACK CIRCLE
    # original: e2 97 8f
    # 0x97 in cp1252 = U+2014 = e28094, 0x8f undefined in cp1252 -> skip or use latin fallback
    # 0x8f in cp1252 is undefined; as latin-1 it's U+008F (control) = c2 8f
    # stored: c3a2 e28094 c28f
    (bytes([0xc3, 0xa2, 0xe2, 0x80, 0x94, 0xc2, 0x8f]), b'\xe2\x97\x8f', 'U+25CF CIRCLE'),

    # ═ U+2550 BOX DOUBLE HORIZONTAL
    # original: e2 95 90
    # 0x95 in cp1252 = U+2022 (•) = e28022? no: U+2022 = e2 80 a2
    # 0x90 in cp1252 is undefined -> as latin-1 U+0090 = c2 90
    # stored: c3a2 e280a2 c290
    (bytes([0xc3, 0xa2, 0xe2, 0x80, 0xa2, 0xc2, 0x90]), b'\xe2\x95\x90', 'U+2550 BOX_DH'),

    # • U+2022 BULLET (cp1252 0x95 -> U+2022 -> e280a2)
    # original: e2 80 a2
    # 0x80=U+20AC(e282ac), 0xa2=U+00A2(c2a2)
    # stored: c3a2 e282ac c2a2
    (bytes([0xc3, 0xa2, 0xe2, 0x82, 0xac, 0xc2, 0xa2]), b'\xe2\x80\xa2', 'U+2022 BULLET'),

    # … U+2026 HORIZONTAL ELLIPSIS
    # original: e2 80 a6
    # 0x80=U+20AC(e282ac), 0xa6=U+00A6(c2a6)
    # stored: c3a2 e282ac c2a6
    (bytes([0xc3, 0xa2, 0xe2, 0x82, 0xac, 0xc2, 0xa6]), b'\xe2\x80\xa6', 'U+2026 ELLIPSIS'),
]


TEXT_EXTS = {'.py', '.md', '.txt', '.yaml', '.yml', '.json', '.ps1', '.sh', '.cfg', '.toml', '.ini', '.rst'}
SKIP_DIRS = {'__pycache__', '.git', 'datasets', 'models', 'outputs', '.runtime'}


def repair_bytes(data: bytes) -> tuple:
    counts = {}
    for corrupted, correct, label in SUBSTITUTIONS:
        n = data.count(corrupted)
        if n > 0:
            data = data.replace(corrupted, correct)
            counts[label] = n
    return data, counts


def repair_file(fpath: str) -> tuple:
    with open(fpath, 'rb') as f:
        original = f.read()

    if b'\xc3\xa2' not in original:
        return 'SKIP', {}

    fixed, counts = repair_bytes(original)

    if fixed == original:
        return 'UNCHANGED', {}

    try:
        fixed.decode('utf-8')
    except UnicodeDecodeError as e:
        return ('INVALID_UTF8: %s' % e), {}

    with open(fpath, 'wb') as f:
        f.write(fixed)

    return 'FIXED', counts


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print('Repair root:', root)
    print()

    results = {'FIXED': [], 'UNCHANGED': [], 'SKIP': [], 'ERROR': []}

    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in TEXT_EXTS:
                continue
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, root)
            try:
                status, counts = repair_file(fpath)
                if status == 'FIXED':
                    results['FIXED'].append(rel)
                    detail = ', '.join('%s x%d' % (k, v) for k, v in counts.items())
                    print('  FIXED:     %s [%s]' % (rel, detail))
                elif status == 'UNCHANGED':
                    results['UNCHANGED'].append(rel)
                elif status.startswith('INVALID') or status.startswith('ERR'):
                    results['ERROR'].append((rel, status))
                    print('  ERROR:     %s -- %s' % (rel, status))
                else:
                    results['SKIP'].append(rel)
            except Exception as e:
                results['ERROR'].append((rel, str(e)))
                print('  ERROR:     %s -- %s' % (rel, e))

    print()
    print('Fixed:     %d' % len(results['FIXED']))
    print('Unchanged: %d' % len(results['UNCHANGED']))
    print('Skipped:   %d' % len(results['SKIP']))
    print('Errors:    %d' % len(results['ERROR']))
    if results['ERROR']:
        sys.exit(1)


if __name__ == '__main__':
    main()
