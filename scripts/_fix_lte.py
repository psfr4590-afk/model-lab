"""Fix remaining â‰¤ -> <= corruption in pipeline_config files.

â‰¤ in file = U+00E2 U+2030 U+00A4
UTF-8: c3 a2 e2 80 b0 c2 a4

Derivation:
  ≤ = U+2264, UTF-8: e2 89 a4
  0xe2 in cp1252 = U+00E2 (â) -> UTF-8: c3 a2
  0x89 in cp1252 = U+2030 (per mille ‰) -> UTF-8: e2 80 b0
  0xa4 in cp1252 = U+00A4 (¤ currency sign) -> UTF-8: c2 a4
"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# corrupted -> correct
SUBST = [
    (bytes([0xc3, 0xa2, 0xe2, 0x80, 0xb0, 0xc2, 0xa4]), b'\xe2\x89\xa4', 'U+2264 <='),
    # Also: >= U+2265, UTF-8: e2 89 a5
    # 0xa5 in cp1252 = U+00A5 (¥) -> UTF-8: c2 a5
    (bytes([0xc3, 0xa2, 0xe2, 0x80, 0xb0, 0xc2, 0xa5]), b'\xe2\x89\xa5', 'U+2265 >='),
]

targets = [
    'pipeline_config.yaml',
    r'config\pipeline_config.yaml',
]

for rel in targets:
    fpath = os.path.join(root, rel)
    with open(fpath, 'rb') as f:
        data = f.read()
    original = data
    counts = {}
    for corrupted, correct, label in SUBST:
        n = data.count(corrupted)
        if n > 0:
            data = data.replace(corrupted, correct)
            counts[label] = n
    if data != original:
        data.decode('utf-8')  # validate
        with open(fpath, 'wb') as f:
            f.write(data)
        print('FIXED %s: %s' % (rel, counts))
    else:
        print('UNCHANGED %s' % rel)
