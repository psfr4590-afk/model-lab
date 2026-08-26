"""Check remaining c3 a2 occurrences in pipeline_config files and old scripts"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

targets = [
    'pipeline_config.yaml',
    r'config\pipeline_config.yaml',
    r'scripts\_diagnose_encoding.py',
    r'scripts\_fix_arrows.py',
]

for rel in targets:
    fpath = os.path.join(root, rel)
    try:
        with open(fpath, 'rb') as f:
            raw = f.read()
        # Find all c3 a2 occurrences and show context
        i = 0
        occurrences = []
        while True:
            idx = raw.find(b'\xc3\xa2', i)
            if idx == -1:
                break
            context = raw[max(0,idx-10):idx+20]
            try:
                ctx_str = context.decode('utf-8', errors='replace')
            except:
                ctx_str = context.hex(' ')
            occurrences.append('  offset %d: %s' % (idx, ctx_str))
            i = idx + 1

        print('%s: %d occurrence(s)' % (rel, len(occurrences)))
        for o in occurrences[:5]:
            print(o)
        print()
    except Exception as e:
        print('%s: ERROR %s' % (rel, e))
