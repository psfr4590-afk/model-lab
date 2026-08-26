"""Probe encoding corruption — find and decode a complete corrupted sequence"""
import os, sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out_path = os.path.join(root, 'scripts', '_probe_out.txt')
lines = []

with open(os.path.join(root, 'requirements.txt'), 'rb') as f:
    data = f.read()

# Find a complete valid UTF-8 sequence starting at first high byte
i = 0
while i < len(data):
    b = data[i]
    if b > 127:
        # Determine sequence length from leading byte
        if b & 0xF8 == 0xF0:
            seq_len = 4
        elif b & 0xF0 == 0xE0:
            seq_len = 3
        elif b & 0xE0 == 0xC0:
            seq_len = 2
        else:
            i += 1
            continue
        chunk = data[i:i+seq_len]
        try:
            c = chunk.decode('utf-8')
            lines.append('First multi-byte char at offset %d: U+%04X %r bytes=%s' % (i, ord(c), c, chunk.hex(' ')))
            # Now decode entire line context
            line_start = data.rfind(b'\n', 0, i) + 1
            line_end = data.find(b'\n', i)
            if line_end == -1: line_end = len(data)
            raw_line = data[line_start:line_end]
            lines.append('Raw line hex: ' + raw_line.hex(' '))
            decoded_line = raw_line.decode('utf-8', errors='replace')
            lines.append('UTF-8 line: ' + repr(decoded_line))

            # Now try full-line latin-1 bridge
            try:
                as_latin = raw_line.decode('latin-1')
                # Encode back as raw bytes (latin-1 is byte-transparent)
                raw_back = as_latin.encode('latin-1')
                # Now decode as UTF-8
                restored = raw_back.decode('utf-8', errors='replace')
                lines.append('Latin-1 bridge: ' + repr(restored))
            except Exception as e:
                lines.append('Latin-1 bridge failed: ' + str(e))

            # Full file decode attempt
            try:
                full_str = data.decode('utf-8')
                # Bridge: UTF-8 string -> latin-1 bytes -> UTF-8 string
                lat_bytes = full_str.encode('latin-1')
                restored_full = lat_bytes.decode('utf-8', errors='replace')
                # Count replacement chars
                n_bad = restored_full.count('\ufffd')
                lines.append('Full file latin-1 bridge: OK, replacement chars=%d' % n_bad)
                if n_bad == 0:
                    lines.append('REPAIR STRATEGY: decode UTF-8 -> encode latin-1 -> decode UTF-8')
            except Exception as e:
                lines.append('Full file bridge failed: ' + str(e))
            break
        except Exception:
            i += 1
            continue
    else:
        i += 1

with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
print('Done')
