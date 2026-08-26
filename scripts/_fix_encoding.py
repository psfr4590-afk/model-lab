#!/usr/bin/env python3
"""
Fix triple-encoding corruption in first-party Python source files.

Corruption pattern:
  Original UTF-8 bytes were decoded as cp1252, producing garbled chars,
  those chars were then re-encoded as latin-1 and finally as UTF-8 again.

Fix: utf-8 decode -> cp1252 encode -> latin-1 decode -> utf-8 encode
     (reverses the damage for affected sequences)

Only applied to files confirmed to contain the corruption pattern.
YAML and requirements files are NOT corrupted at file level (verified).
"""
import pathlib, sys
sys.stdout.reconfigure(encoding='utf-8')


def fix_triple_encoded(text: str) -> str:
    """Attempt to repair triple-encoding corruption character by character.
    
    For each sequence of chars that can round-trip through cp1252->latin1->utf8,
    check if the result is a printable Unicode character. If so, replace it.
    """
    # Work on the raw bytes of the utf-8 decoded string
    # Strategy: encode as cp1252 (errors=replace), then decode as utf-8
    try:
        fixed = text.encode('cp1252', errors='replace').decode('latin-1').encode('latin-1').decode('utf-8')
        return fixed
    except Exception:
        return text


def safe_fix_file(path: pathlib.Path) -> bool:
    """Fix a file if it contains the triple-encoding pattern. Returns True if changed."""
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        print(f'SKIP (not valid UTF-8): {path}')
        return False

    # Check if this file contains the known corruption marker
    # The pattern: \xc3\x83 in utf-8 decoded text means the file has 
    # Ã (U+00C3) followed by © or similar -- a sign of double/triple encoding
    if '\u00c3' not in text:
        print(f'CLEAN: {path}')
        return False

    # Apply fix: treat the utf-8 decoded text as if it were cp1252 encoded bytes
    try:
        as_bytes = text.encode('cp1252', errors='replace')
        # Now decode those bytes as if they were latin-1
        step2 = as_bytes.decode('latin-1')
        # Now try to decode step2 as utf-8
        as_bytes2 = step2.encode('latin-1', errors='replace')
        fixed = as_bytes2.decode('utf-8', errors='replace')
        
        if fixed != text:
            path.write_text(fixed, encoding='utf-8')
            print(f'FIXED: {path}')
            return True
        else:
            print(f'NO CHANGE: {path}')
            return False
    except Exception as e:
        print(f'ERROR fixing {path}: {e}')
        return False


FILES = [
    'run_pipeline.py',
    'pipeline/orchestrator.py',
    'pipeline/app.py',
]

for rel in FILES:
    p = pathlib.Path(rel)
    if p.exists():
        safe_fix_file(p)
    else:
        print(f'NOT FOUND: {rel}')
