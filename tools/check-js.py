#!/usr/bin/env python3
"""Extract every inline <script> from index.html and run `node --check` on it.

HTML comments are stripped FIRST: the Firebase comment in this file contains
the literal text "<script>", so a naive regex matches inside it and reports a
phantom syntax error on prose.
"""
import re, subprocess, io, os, sys, tempfile
path = sys.argv[1] if len(sys.argv) > 1 else 'index.html'
s = io.open(path, encoding='utf-8').read()
s = re.sub(r'<!--.*?-->', '', s, flags=re.S)
blocks = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', s, re.S)
ok = True
for i, b in enumerate(blocks, 1):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(b); p = f.name
    r = subprocess.run(['node', '--check', p], capture_output=True, text=True)
    if r.returncode: ok = False
    print(f"  block {i}: {len(b.splitlines()):6d} lines  {'OK' if r.returncode == 0 else 'FAIL'}")
    if r.returncode: print(r.stderr[:600])
    os.unlink(p)
print(f"{len(blocks)} inline blocks — " + ("ALL PASS" if ok else "SYNTAX ERRORS"))
sys.exit(0 if ok else 1)
