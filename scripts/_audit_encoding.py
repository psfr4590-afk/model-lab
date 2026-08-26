"""
Final encoding audit — check for any remaining double-UTF-8 corruption artifacts.
Writes results to scripts/_audit_out.txt (UTF-8).
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out_path = os.path.join(root, 'scripts', '_audit_out.txt')

TEXT_EXTS = {'.py', '.md', '.txt', '.yaml', '.yml', '.json', '.ps1', '.sh', '.cfg', '.toml', '.ini', '.rst'}
SKIP_DIRS = {'__pycache__', '.git', 'datasets', 'models', 'outputs', '.runtime'}

# The c3 a2 prefix is the UTF-8 encoding of U+00E2 (â), which appears as the
# first byte of all double-encoded sequences (original UTF-8 byte 0xe2 mis-encoded).
CORRUPTION_MARKER = re.compile(rb'\xc3\xa2')

# Also check for leftover mojibake text patterns (after decoding as UTF-8)
MOJIBAKE_PATTERNS = ['Â', 'Ã\x82', 'â€', 'â†', 'â—', 'ðŸ']

issues = []
clean = []

for dirpath, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for fname in files:
        ext = os.path.splitext(fname)[1].lower()
        if ext not in TEXT_EXTS:
            continue
        fpath = os.path.join(dirpath, fname)
        rel = os.path.relpath(fpath, root)
        try:
            with open(fpath, 'rb') as f:
                raw = f.read()

            has_marker = bool(CORRUPTION_MARKER.search(raw))
            if has_marker:
                issues.append((rel, 'byte-level: c3 a2 sequence present'))
                continue

            # Check for mojibake text patterns
            try:
                text = raw.decode('utf-8')
                for pat in MOJIBAKE_PATTERNS:
                    if pat in text:
                        issues.append((rel, 'text-level mojibake: ' + repr(pat)))
                        break
                else:
                    clean.append(rel)
            except UnicodeDecodeError as e:
                issues.append((rel, 'invalid UTF-8: ' + str(e)))

        except Exception as e:
            issues.append((rel, 'read error: ' + str(e)))

lines = []
lines.append('ENCODING AUDIT RESULTS')
lines.append('=' * 60)
lines.append('')
if issues:
    lines.append('ISSUES FOUND (%d):' % len(issues))
    for path, reason in issues:
        lines.append('  ISSUE: %s -- %s' % (path, reason))
else:
    lines.append('CLEAN: No encoding issues found.')
lines.append('')
lines.append('Files checked: %d' % (len(issues) + len(clean)))
lines.append('Issues: %d' % len(issues))
lines.append('Clean: %d' % len(clean))

with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')

print('Audit complete. Results in scripts/_audit_out.txt')
print('Issues: %d / Files checked: %d' % (len(issues), len(issues) + len(clean)))
