#!/usr/bin/env python3
"""Draw the Nova app icon and write it into index.html.

The icon before this was a detailed illustration - a gradient sphere with a
starburst, an orbiting moon and a small N - on a purple field, with rounded
corners baked into the image. It did not read as an iOS icon: too much detail
to survive 60pt, a colour family from nowhere in iOS, and no sense of a lit
surface. The baked corners were an outright bug, because iOS applies its own
mask on top and rounds an already-rounded image.

What replaces it follows what iOS system icons actually do:

  * FULL-BLEED SQUARE, no corner rounding and no transparency. iOS masks the
    icon itself; anything rounded here gets rounded twice.
  * One idea, readable at 60pt - the V from NOVA, nothing else.
  * The dark greys iOS uses for its own dark surfaces (systemGray5 #2C2C2E to
    systemGray6 #1C1C1E), so it sits among them rather than against them.
  * A lit surface, not a flat fill: a soft overhead highlight, a hairline of
    light along the top edge, a shadow under the glyph and a specular pass
    along its upper edges. Subtle - at icon size this reads as depth, and
    anything stronger reads as a sticker.

The V keeps Nova's own gradient (#FFD37A gold to #C23B7A magenta, the same
three stops as the wordmark and the hero sphere), because it is the one thing
that makes the icon Nova's rather than any dark app's.

    python3 tools/gen-app-icon.py --preview out/   # render only, touch nothing
    python3 tools/gen-app-icon.py                  # write into index.html
    python3 tools/gen-app-icon.py --variant white  # see --variant --help

Writes both the apple-touch-icon link and the icons inside the base64
manifest, which must never drift apart. The manifest is decoded, edited as
JSON and re-encoded - never hand-patched.
"""
import argparse
import base64
import io
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")

SS = 4                      # supersampling factor; drawn at 4x then reduced
BASE = 1024                 # master size
BRAND = ["#FFD37A", "#F5804D", "#C23B7A"]

VARIANTS = {
    # name: (background top, background bottom, glyph stops)
    "brand": ("#2C2C2E", "#1A1A1C", BRAND),
    "white": ("#2C2C2E", "#1A1A1C", ["#FFFFFF", "#F2F2F7", "#D8D8DE"]),
    "noir":  ("#1F1F21", "#0A0A0A", BRAND),
}

# Sizes written into the manifest. 180 is what iOS takes; Android and desktop
# browsers pick the larger ones, and a flat-ish icon costs very little at 512.
MANIFEST_SIZES = [180, 192, 512]


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def multi_stop(stops, t):
    """t in 0..1 across an evenly spaced list of hex stops."""
    cols = [hex_rgb(s) for s in stops]
    if len(cols) == 1:
        return cols[0]
    span = 1.0 / (len(cols) - 1)
    i = min(int(t / span), len(cols) - 2)
    return lerp(cols[i], cols[i + 1], (t - i * span) / span)


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (1, size), 0)
    px = img.load()
    a, b = hex_rgb(top), hex_rgb(bottom)
    for y in range(size):
        px[0, y] = lerp(a, b, y / max(1, size - 1))
    return img.resize((size, size), Image.BICUBIC)


def diagonal_gradient(size, stops):
    """A linear gold-to-magenta ramp, top-left to bottom-right.

    Built small and scaled up rather than filled pixel by pixel: a linear
    gradient has no detail to lose, and the direct loop is 16 million Python
    iterations at the 4x working size, which is minutes per variant.
    """
    n = 256
    small = Image.new("RGB", (n, n), 0)
    px = small.load()
    for y in range(n):
        for x in range(n):
            # Weighted towards vertical. On an even diagonal only the
            # bottom-RIGHT corner of the box reaches the last stop, and a V
            # has no mass there - so the apex came out coral and the magenta
            # never appeared at all. Mostly-vertical puts gold along the top
            # edge and full magenta at the point, which is where the eye
            # lands, with enough lateral tilt to still read as lit.
            px[x, y] = multi_stop(stops, (0.26 * x + 0.74 * y) / (n - 1))
    return small.resize((size, size), Image.BICUBIC)


def v_polygon(size):
    """The V, as one closed polygon with parallel arms and a mitred apex."""
    L, R = 0.253 * size, 0.747 * size        # outer top corners
    T, B = 0.292 * size, 0.748 * size        # top edge, apex
    C = size / 2.0
    t = 0.120 * size                          # arm thickness, measured across
    d = (B - T) * t / (C - L)                 # apex inset, keeps arms parallel
    return [(L, T), (C, B), (R, T), (R - t, T), (C, B - d), (L + t, T)]


def v_bbox(size):
    pts = v_polygon(size)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def glyph_mask(size):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).polygon(v_polygon(size), fill=255)
    return m


def render(variant, size=BASE):
    top, bottom, stops = VARIANTS[variant]
    S = size * SS
    white = Image.new("RGBA", (S, S), (255, 255, 255, 255))
    black = Image.new("RGBA", (S, S), (0, 0, 0, 255))

    icon = vertical_gradient(S, top, bottom).convert("RGBA")

    # Overhead light. Deliberately faint - an iOS icon's surface is a dark
    # grey that happens to be lit, not a grey with a visible gloss band on
    # it. The first pass here used four times this and turned the top half
    # to mid-grey, which read as a gradient wallpaper rather than a surface.
    glow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow).ellipse([-0.40 * S, -0.85 * S, 1.40 * S, 0.52 * S], fill=24)
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.13))
    icon = Image.composite(white, icon, glow)

    # Hairline of light along the very top edge.
    rim = Image.new("L", (S, S), 0)
    ImageDraw.Draw(rim).rectangle([0, 0, S, S * 0.008], fill=30)
    rim = rim.filter(ImageFilter.GaussianBlur(S * 0.005))
    icon = Image.composite(white, icon, rim)

    mask = glyph_mask(S)

    # Contact shadow: tight and low, so the glyph sits on the surface rather
    # than floating over it with a halo.
    shadow = mask.filter(ImageFilter.GaussianBlur(S * 0.012)).point(lambda v: int(v * 0.34))
    shadow = shadow.transform(shadow.size, Image.AFFINE, (1, 0, 0, 0, 1, -S * 0.009))
    icon = Image.composite(black, icon, shadow)

    # The brand ramp is mapped across the GLYPH's own box, not the canvas.
    # Across the canvas the V only ever covered the middle of the ramp, so
    # it came out uniformly salmon with the gold and the magenta both off
    # the edges of the shape - the whole identity, missing.
    x0, y0, x1, y1 = v_bbox(S)
    bw, bh = int(round(x1 - x0)), int(round(y1 - y0))
    fill = Image.new("RGB", (S, S), hex_rgb(stops[0]))
    fill.paste(diagonal_gradient(max(bw, bh), stops).resize((bw, bh), Image.BICUBIC),
               (int(round(x0)), int(round(y0))))
    icon.paste(fill.convert("RGBA"), (0, 0), mask)

    # Light from above, on the glyph itself: a soft vertical falloff over its
    # top third, masked to the shape so it cannot spill onto the background.
    spec = Image.new("L", (S, S), 0)
    sd = ImageDraw.Draw(spec)
    band = (y1 - y0) * 0.55
    for i in range(int(band)):
        sd.rectangle([0, y0 + i, S, y0 + i + 1], fill=int(58 * (1 - i / band) ** 2))
    spec = Image.composite(spec, Image.new("L", (S, S), 0), mask)
    spec = spec.filter(ImageFilter.GaussianBlur(S * 0.004))
    icon = Image.composite(white, icon, spec)

    return icon.convert("RGB").resize((size, size), Image.LANCZOS)


def masked(img):
    """A preview only - what iOS will show once it applies its own mask.

    The shipped icon is a plain opaque square; the rounding is the system's
    job. This exists so the corners can be eyeballed without guessing, and
    so nobody is ever tempted to bake the corners in again (the icon this
    replaced had them baked in, and got rounded twice on device).
    Approximates the squircle with a large-radius rounded rectangle - close
    enough to judge, not the real superellipse.
    """
    n = img.size[0]
    m = Image.new("L", (n * 4, n * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, n * 4 - 1, n * 4 - 1],
                                        radius=int(n * 4 * 0.2237), fill=255)
    m = m.resize((n, n), Image.LANCZOS)
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.paste(img.convert("RGBA"), (0, 0), m)
    return out


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def data_uri(img):
    return "data:image/png;base64," + base64.b64encode(png_bytes(img)).decode("ascii")


def write_into_index(variant):
    master = render(variant, BASE)
    src = io.open(INDEX, encoding="utf-8").read()

    apple = data_uri(master.resize((180, 180), Image.LANCZOS))
    new_src, n = re.subn(r'(<link rel="apple-touch-icon" href=")[^"]+(")',
                         lambda m: m.group(1) + apple + m.group(2), src, count=1)
    if not n:
        sys.exit("could not find the apple-touch-icon link in index.html")

    m = re.search(r'(href="data:application/manifest\+json;base64,)([^"]+)(")', new_src)
    if not m:
        sys.exit("could not find the manifest link in index.html")
    manifest = json.loads(base64.b64decode(m.group(2)))
    manifest["icons"] = []
    for size in MANIFEST_SIZES:
        uri = data_uri(master.resize((size, size), Image.LANCZOS))
        manifest["icons"].append({"src": uri, "sizes": f"{size}x{size}",
                                  "type": "image/png", "purpose": "any"})
    # One maskable copy. The V sits inside the middle 45% of the canvas, well
    # within the safe circle Android crops to, so the same art works as-is.
    manifest["icons"].append({"src": data_uri(master.resize((512, 512), Image.LANCZOS)),
                              "sizes": "512x512", "type": "image/png", "purpose": "maskable"})
    encoded = base64.b64encode(json.dumps(manifest, separators=(",", ":")).encode()).decode()
    new_src = new_src[:m.start(2)] + encoded + new_src[m.end(2):]

    io.open(INDEX, "w", encoding="utf-8").write(new_src)
    total = len(apple) + sum(len(i["src"]) for i in manifest["icons"])
    print(f"wrote the {variant} icon: apple-touch-icon at 180, "
          f"manifest at {MANIFEST_SIZES} plus a 512 maskable ({total/1024:.0f} KB of data URIs)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="brand", choices=sorted(VARIANTS),
                    help="brand: Nova's gold-to-magenta V (default). "
                         "white: a monochrome V. noir: the same V on near-black.")
    ap.add_argument("--preview", metavar="DIR",
                    help="render every variant to DIR and leave index.html alone")
    args = ap.parse_args()

    if args.preview:
        os.makedirs(args.preview, exist_ok=True)
        for name in sorted(VARIANTS):
            img = render(name, BASE)
            img.save(os.path.join(args.preview, f"icon_{name}_1024.png"))
            img.resize((180, 180), Image.LANCZOS).save(
                os.path.join(args.preview, f"icon_{name}_180.png"))
            masked(img).save(os.path.join(args.preview, f"icon_{name}_masked.png"))
            print(f"{name}: {os.path.join(args.preview, f'icon_{name}_1024.png')}")
        return

    write_into_index(args.variant)


if __name__ == "__main__":
    main()
