"""
Encoding repair script — fixes triple-encoded UTF-8 in first-party text files.

Triple-encoding pattern:
  Original UTF-8 bytes -> interpreted as cp1252 -> re-encoded as UTF-8
  e.g. → (E2 86 92) becomes C3 A2 E2 80 A0 E2 80 99 in the file

Fix: decode as UTF-8 -> encode as cp1252 -> decode as latin-1 -> that's valid UTF-8 bytes -> decode as UTF-8
"""

import os
import sys

TEXT_EXTS = {'.py', '.md', '.txt', '.yaml', '.yml', '.json', '.ps1', '.sh', '.cfg', '.toml', '.ini', '.rst'}
SKIP_DIRS = {'__pycache__', '.git', 'datasets', 'models', 'outputs', '.runtime'}

def fix_triple_encoding(data: bytes) -> bytes:
    """
    Attempt to fix triple-encoded UTF-8.
    Strategy: decode UTF-8 -> encode cp1252 -> decode latin-1 -> that gives original UTF-8 bytes.
    Only apply if the round-trip produces valid UTF-8 and reduces non-ASCII byte count.
    """
    try:
        # Step 1: decode the corrupted bytes as UTF-8
        as_str = data.decode('utf-8')
    except UnicodeDecodeError:
        return data  # not valid UTF-8 at all, skip

    try:
        # Step 2: encode as cp1252 (reverses the last mis-encoding step)
        as_cp1252_bytes = as_str.encode('cp1252')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return data  # can't round-trip through cp1252, skip

    try:
        # Step 3: decode as latin-1 (reverses the middle mis-encoding step)
        # latin-1 is byte-transparent so this always succeeds
        fixed_str = as_cp1252_bytes.decode('latin-1')
    except Exception:
        return data

    try:
        # Step 4: encode back to UTF-8 — this is the original file content
        fixed_bytes = fixed_str.encode('utf-8')
    except Exception:
        return data

    # Sanity check: the fixed version must be valid UTF-8
    try:
        fixed_bytes.decode('utf-8')
    except UnicodeDecodeError:
        return data

    # Only accept if we reduced the high-byte density (encoding got cleaner)
    orig_high = sum(1 for b in data if b > 127)
    fixed_high = sum(1 for b in fixed_bytes if b > 127)
    if fixed_high <= orig_high:
        return fixed_bytes

    return data


def needs_repair(data: bytes) -> bool:
    """Quick check: does this file contain triple-encoding artifacts?"""
    import re
    return bool(re.search(rb'\xc3[\x80-\xbf]', data))


def repair_file(fpath: str) -> str:
    with open(fpath, 'rb') as f:
        original = f.read()

    if not needs_repair(original):
        return 'SKIP'

    fixed = fix_triple_encoding(original)

    if fixed == original:
        return 'UNCHANGED'

    with open(fpath, 'wb') as f:
        f.write(fixed)

    return 'FIXED'


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"Repair root: {root}")
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
                status = repair_file(fpath)
                results[status].append(rel)
                if status == 'FIXED':
                    print(f"  FIXED:     {rel}")
            except Exception as e:
                results['ERROR'].append((rel, str(e)))
                print(f"  ERROR:     {rel} -- {e}")

    print()
    print(f"Fixed:     {len(results['FIXED'])}")
    print(f"Unchanged: {len(results['UNCHANGED'])}")
    print(f"Skipped:   {len(results['SKIP'])}")
    print(f"Errors:    {len(results['ERROR'])}")

    if results['ERROR']:
        sys.exit(1)


if __name__ == '__main__':
    main()
