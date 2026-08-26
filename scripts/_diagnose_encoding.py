#!/usr/bin/env python3
"""Diagnose the exact encoding corruption in run_pipeline.py."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

seq = bytes.fromhex('c383c2a2c3a2e282acc2a0c3a2e282ace284a2')
step1 = seq.decode('utf-8')
print('step1 repr:', repr(step1))
print('step1 ords:', [hex(ord(c)) for c in step1])
# The codepoints are: C3 A2 = â, E2 20AC = â€ (euro sign mixed), A0 = NBSP, E2 20AC = â€, 2122 = ™
# This is: Ã¢â€šÂ¢ ... pattern = classic triple encoding of something
# The original arrow → is U+2192 = E2 86 92 in UTF-8
# Encoded as latin-1 then utf-8 once: gives Ã¢â€ ’ pattern
# Let's check if decoding step1 bytes via cp1252 then utf-8 works
try:
    step2 = step1.encode('cp1252', errors='replace').decode('utf-8', errors='replace')
    print('via cp1252:', repr(step2))
except Exception as e:
    print('cp1252 attempt:', e)

# The raw bytes: c383 c2a2  c3a2 e282ac  c2a0  c3a2 e282ac  e284a2
# Decoded as UTF-8:  0xC3 0xA2 = â    0xE2 0x20AC = â€   0xA0 = \xa0  0xE2 0x20AC = â€  0x2122 = ™
# Chars: C3=Ã, A2=¢ BUT decoded as UTF-8 pair: Ã+¢ = \u00c3 \u00a2  
# WAIT: the raw bytes when decoded utf-8 give these codepoints:
# c383 -> 0xC3 (Ã) -- single byte interpreted as utf-8 char C3 83 = Ã
# So the FULL utf-8 decode gives: Ã â€ \xa0 â€ ™
# In latin-1: Ã=\xc3, â=\xe2, €=\x80\xac can't be latin-1...
# Actually step1 contains \u20ac (euro sign) which is NOT in latin-1
# So this is a Windows-1252 encoding artifact
# In cp1252: \x80 = €  
# The original character was likely → (U+2192), stored as UTF-8 (e2 86 92)
# Then mis-decoded as cp1252: e2->â, 86->†, 92->  (ANSI)
# Then re-encoded differently...
# Let's just verify: what's the intended content based on context?
print()
print('Context shows: "Crawl web, GitHub, ArXiv [CORRUPT] 01_crawled.jsonl"')
print('The [CORRUPT] should be an arrow character: → or ➜')
print('U+2192 = →  (standard right arrow)')
print('U+279C = ➜  (heavy round-tipped rightwards arrow)')
print()
# Check if the original might have been U+279C ➜
arrow_279c = '\u279c'.encode('utf-8')
print('U+279C UTF-8 bytes:', arrow_279c.hex())
# e2 9e 9c -- that's a candidate
# What about ➡ U+27A1?
arrow_27a1 = '\u27a1'.encode('utf-8')
print('U+27A1 UTF-8 bytes:', arrow_27a1.hex())
