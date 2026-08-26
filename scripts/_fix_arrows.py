#!/usr/bin/env python3
"""
Fix remaining double-UTF-8-encoded arrow characters in run_pipeline.py.

The pattern b'\xc3\xa2\xe2\x80\xa0\xe2\x80\x99' (= â†' double-encoded)
should be replaced with b'\xe2\x86\x92' (= → U+2192).

Also handles other common double-encoded sequences found in this file.
"""
import pathlib, sys
sys.stdout.reconfigure(encoding='utf-8')

# Map from double-encoded UTF-8 bytes -> correct UTF-8 bytes
# Each key is the double-encoded bytes found in the file
BYTE_FIXES = [
    # â†' (double-encoded →)
    (b'\xc3\xa2\xe2\x80\xa0\xe2\x80\x99', '→'.encode('utf-8')),
    # Fallback partial patterns from earlier triple-encode fix
    # a2 e2 80 a0 e2 80 99 (same pattern, latin-1 a2 prefix)
    (b'\xa2\xe2\x80\xa0\xe2\x80\x99', '→'.encode('utf-8')),
]

files = ['run_pipeline.py']

for rel in files:
    p = pathlib.Path(rel)
    if not p.exists():
        print(f'NOT FOUND: {rel}')
        continue
    raw = p.read_bytes()
    original = raw
    for bad_bytes, good_bytes in BYTE_FIXES:
        count = raw.count(bad_bytes)
        if count:
            raw = raw.replace(bad_bytes, good_bytes)
            print(f'Replaced {count}x {bad_bytes.hex()} with {good_bytes.hex()} in {rel}')
    if raw != original:
        p.write_bytes(raw)
        print(f'FIXED: {rel}')
    else:
        print(f'NO CHANGE: {rel}')
    
    # Verify the result reads correctly as UTF-8
    try:
        text = p.read_bytes().decode('utf-8')
        print(f'UTF-8 verify: OK ({len(text)} chars)')
    except UnicodeDecodeError as e:
        print(f'UTF-8 verify FAILED: {e}')
