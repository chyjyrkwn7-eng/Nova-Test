#!/usr/bin/env python3
"""Write a copy of index.html with real safe-area insets baked in.

Chromium always reports env(safe-area-inset-*) as 0, so every one of them
collapses to its fallback and any layout that only misbehaves once the insets
are non-zero is invisible in local testing. This substitutes real iPhone
values textually, so serving the copy exercises the inset paths for real.

    python3 tools/sim-safe-area.py out/index.html
    python3 -m http.server 8733 --directory out

Defaults are an iPhone with a notch and a home indicator, portrait. Pass
--bottom/--top/--left/--right to model another device or orientation (an iPad
in landscape, for instance, has a bottom inset but no top one).
"""
import argparse
import io
import os
import re

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")
PATTERN = re.compile(r"env\(safe-area-inset-(top|bottom|left|right)(?:\s*,[^()]*)?\)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="path to write the patched copy to")
    ap.add_argument("--top", default="59px")
    ap.add_argument("--bottom", default="34px")
    ap.add_argument("--left", default="0px")
    ap.add_argument("--right", default="0px")
    ap.add_argument("--src", default=SRC)
    args = ap.parse_args()

    insets = {"top": args.top, "bottom": args.bottom, "left": args.left, "right": args.right}
    src = io.open(args.src, encoding="utf-8").read()
    found = len(PATTERN.findall(src))
    out = PATTERN.sub(lambda m: insets[m.group(1)], src)
    left = len(PATTERN.findall(out))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    io.open(args.out, "w", encoding="utf-8").write(out)
    print(f"{found} env(safe-area-inset-*) references -> {insets}")
    print(f"{left} left unsubstituted")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
