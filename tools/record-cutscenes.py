#!/usr/bin/env python3
"""record-cutscenes.py - the animations, as animations.

`shoot-flow.py` answers "what does this screen look like". It cannot answer
"what does this MOVE like", and four of the things Madison has asked about
most - the badge unlock, a rank cutscene, the Supernova cutscene, the flight
to the Profile tab - are only animation. A still of any of them is a still of
one arbitrary frame, and picking that frame by hand is how a 20-second
cutscene got reported as "nothing happens".

There is no ffmpeg in the sandbox and Playwright's own recorder only emits
.webm, which is not a safe bet on an iPhone. So frames come straight off the
compositor with CDP `Page.startScreencast` - real paint timing, not a
screenshot loop, which matters because a screenshot loop samples at whatever
rate the screenshots complete and misses the fast parts - and Pillow writes
them out as a GIF. A GIF plays anywhere, including inside a message.

Three things here were each learned by getting them wrong:

  * ONE PALETTE FOR THE WHOLE CLIP, BUILT FROM FRAMES ACROSS IT. Quantising
    against frame 0 means quantising a gold burst against a palette sampled
    from a near-black Home screen: the payoff came out grey, which read as
    the cutscene having no colour rather than as an encoding artifact.
  * NO DITHERING. The noise it adds defeats LZW and roughly doubles the file
    on a screen that is mostly smooth dark gradient.
  * KNOW THE REAL LENGTH BEFORE RECORDING. The Supernova cutscene bursts at
    9s and finishes at 20s, two and a half times any other tier's. A 12s
    capture of it is a recording of the wind-up and nothing else.

    python3 tools/record-cutscenes.py
    python3 tools/record-cutscenes.py --only supernova
    python3 tools/record-cutscenes.py --out /some/dir
"""

import base64
import functools
import http.server
import io
import json
import os
import socket
import sys
import threading
import time

from PIL import Image
from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = __file__.rsplit("/tools/", 1)[0]

PHONE = ("phone", 440, 956)      # iPhone 17 Pro Max
TABLET = ("tablet", 834, 1194)   # iPad Pro 11"

FPS = 12.5
GIF_W = 300

# A used account, for the same reason the sweep's is: on an empty one half
# these screens render their empty state. Identity Crimes sits one hundo
# short of its badge and is the smallest unit in the app (12 questions),
# which is what makes a real, full-unit, 100% run recordable at all.
SEED = {
    "onboardingComplete": True, "firstName": "Madison", "avatarChar": "ninja",
    "tourRev": 99,
    "lifetime": {"points": 41000, "answered": 2100, "correct": 1980,
                 "drillPlays": 60, "examPlays": 12, "gamePlays": 8,
                 "perfectTests": 64, "longestStreak": 44, "currentStreak": 12},
    "unitPerfects": {"Professionalism and Ethics": 35, "TCOLE Rules": 35,
                     "Penal Code": 35, "Racial Profiling": 35,
                     "Victims of Crime": 35, "Identity Crimes": 34},
}


def serve():
    so = socket.socket(); so.bind(("127.0.0.1", 0))
    port = so.getsockname()[1]; so.close()

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", port), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


class Recorder:
    """CDP screencast frames, with the compositor's own timestamps."""

    def __init__(self, page):
        self.cdp = page.context.new_cdp_session(page)
        self.frames = []
        self.on = False
        self.cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, ev):
        try:
            self.cdp.send("Page.screencastFrameAck",
                          {"sessionId": ev["sessionId"]})
        except Exception:
            pass
        if self.on:
            self.frames.append((ev["metadata"].get("timestamp") or time.time(),
                                base64.b64decode(ev["data"])))

    def start(self):
        self.frames = []
        self.on = True
        self.cdp.send("Page.startScreencast",
                      {"format": "jpeg", "quality": 92, "everyNthFrame": 1})

    def stop(self):
        self.on = False
        try:
            self.cdp.send("Page.stopScreencast")
        except Exception:
            pass
        return self.frames


def write_gif(frames, path, fps=FPS, width=GIF_W):
    """Resample onto a uniform clock and write a GIF."""
    if not frames:
        print("  !! no frames captured")
        return
    t0 = frames[0][0]
    span = frames[-1][0] - t0
    step = 1.0 / fps
    n = max(1, int(span / step) + 1)
    imgs, j = [], 0
    for i in range(n):
        want = t0 + i * step
        while j + 1 < len(frames) and frames[j + 1][0] <= want:
            j += 1
        im = Image.open(io.BytesIO(frames[j][1])).convert("RGB")
        if im.width != width:
            im = im.resize((width, round(im.height * width / im.width)),
                           Image.LANCZOS)
        imgs.append(im)
    k = max(1, len(imgs) // 24)
    sample = imgs[::k]
    tile = Image.new("RGB", (imgs[0].width, imgs[0].height * len(sample)))
    for i, im in enumerate(sample):
        tile.paste(im, (0, i * imgs[0].height))
    pal = tile.quantize(colors=256, method=Image.MEDIANCUT)
    conv = [im.quantize(palette=pal, dither=Image.NONE) for im in imgs]
    conv[0].save(path, save_all=True, append_images=conv[1:],
                 duration=int(step * 1000), loop=0, optimize=True, disposal=1)
    print("  %-34s %3d frames  %4.1fs  %6.0f KB"
          % (os.path.basename(path), len(conv), span,
             os.path.getsize(path) / 1024))


def new_page(br, port, w, h, seed):
    ctx = br.new_context(viewport={"width": w, "height": h},
                         device_scale_factor=1)
    pg = ctx.new_page()
    pg.add_init_script(
        "Object.defineProperty(navigator,'standalone',{get:()=>true});")
    # freshstart: without it the class-wide reset wipes the fixture at boot.
    # frame.ok: otherwise the re-add notice sits over the top of every clip.
    pg.add_init_script(
        "try{localStorage.setItem('class26e.freshstart','1');"
        "localStorage.setItem('class26e.frame.ok','go-live-1');"
        "localStorage.setItem('class26e.daily.seen','x');"
        "localStorage.setItem('class26e.drill.v1',%s)}catch(e){}"
        % json.dumps(json.dumps(seed)))
    pg.goto("http://127.0.0.1:%d/index.html" % port)
    pg.wait_for_timeout(2200)
    pg.evaluate("()=>document.getElementById('splashscreen')?.remove()")
    pg.wait_for_timeout(300)
    return ctx, pg


# ---------------------------------------------------------------- driving

def start_unit_run(pg, unit):
    pg.evaluate("""(unit)=>{
      cfg.source='all'; cfg.mode='drill'; cfg.units=[unit];
      beginRun(QUESTIONS.map((q,i)=>i)
        .filter(i => (QUESTIONS[i].topic||'').trim() === unit));
    }""", unit)


def answer_all(pg, upto=0):
    """Answer a running drill correctly, stopping `upto` questions short.

    Waits on the DOM rather than on a fixed delay at every step: beginRun()
    puts a ~3s LOADING TEST screen up first, and the slide between questions
    briefly has two questions mounted at once, so a click on a timer lands on
    the outgoing one and registers as a wrong answer.
    """
    pg.wait_for_selector(".choice", timeout=25000)
    stop = pg.evaluate("()=>order.length") - upto
    for _ in range(stop):
        p = pg.evaluate("()=>pos")
        pg.evaluate("""()=>{const r=correctSlot(order[pos]);
            document.querySelector('.choice[data-index="'+r+'"]').click();}""")
        pg.wait_for_timeout(420)
        if not pg.evaluate("()=>!!document.getElementById('nextbtn')"):
            break
        pg.evaluate("()=>document.getElementById('nextbtn').click()")
        for _ in range(30):
            pg.wait_for_timeout(120)
            if pg.evaluate("()=>pos") != p or \
               not pg.evaluate("()=>document.querySelector('.choice')"):
                break
        if not pg.evaluate("()=>document.querySelector('.choice')"):
            break


# ---------------------------------------------------------------- scenes

def badge_cutscene(pg, rec):
    pg.evaluate("()=>showHome()")
    pg.wait_for_timeout(700)
    rec.start(); pg.wait_for_timeout(400)
    pg.evaluate("()=>{store.pendingBadgeUnlocks=['Identity Crimes'];"
                "playQueuedBadgeCutscenes()}")
    pg.wait_for_timeout(4800)


def badge_queue(pg, rec):
    """Three in a row - the queue is per badge, not per test."""
    pg.evaluate("()=>showHome()")
    pg.wait_for_timeout(700)
    rec.start(); pg.wait_for_timeout(400)
    pg.evaluate("()=>{store.pendingBadgeUnlocks="
                "['Identity Crimes','Victims of Crime','Verbal Communication'];"
                "playQueuedBadgeCutscenes()}")
    pg.wait_for_timeout(10500)


def rank_cutscene(key):
    def body(pg, rec):
        pg.evaluate("()=>showHome()")
        pg.wait_for_timeout(700)
        rec.start(); pg.wait_for_timeout(400)
        pg.evaluate("(k)=>{store.pendingTierCutscene=k; playTierCutscene(k)}",
                    key)
        pg.wait_for_timeout(11800)   # 8s cutscene, then the RANK UP banner
    return body


def supernova(pg, rec):
    pg.evaluate("()=>showHome()")
    pg.wait_for_timeout(700)
    rec.start(); pg.wait_for_timeout(400)
    pg.evaluate("()=>{store.pendingSupernovaCutscene=true;"
                "playSupernovaCutscene()}")
    pg.wait_for_timeout(23500)       # burst 9s, settle 13.5s, finish 20s


def test_to_badge(pg, rec):
    """The whole earn, walked rather than mounted: the last question of a
    full-unit run, the 100% card with the badge on it, Main menu, and both
    cutscenes it triggers. Eleven questions are answered before the camera
    starts - the clip is about the reward, not about typing."""
    pg.evaluate("()=>showHome()")
    pg.wait_for_timeout(400)
    start_unit_run(pg, "Identity Crimes")
    answer_all(pg, upto=1)
    rec.start()
    pg.wait_for_timeout(900)
    pg.evaluate("""()=>{const r=correctSlot(order[pos]);
        document.querySelector('.choice[data-index="'+r+'"]').click();}""")
    pg.wait_for_timeout(1500)
    pg.evaluate("()=>document.getElementById('nextbtn').click()")
    pg.wait_for_timeout(6800)
    pg.evaluate("""()=>{const b=[...document.querySelectorAll('button')]
        .find(x=>/main menu/i.test(x.textContent||'')); b && b.click();}""")
    # This run is the 6th badge AND level 30, so it tips Gold as well: the
    # rank cutscene takes Home first and the badge cutscene follows it.
    pg.wait_for_timeout(15500)


SCENES = [
    ("badge-unlock",   PHONE,  badge_cutscene,            FPS, GIF_W),
    ("badge-unlock",   TABLET, badge_cutscene,            FPS, 340),
    ("badge-queue",    PHONE,  badge_queue,               10,  GIF_W),
    ("test-to-badge",  PHONE,  test_to_badge,             10,  GIF_W),
    ("rank-rookie",    PHONE,  rank_cutscene("rookie"),   10,  GIF_W),
    ("rank-ranger",    PHONE,  rank_cutscene("ranger"),   10,  GIF_W),
    ("rank-veteran",   PHONE,  rank_cutscene("veteran"),  10,  GIF_W),
    ("rank-vanguard",  PHONE,  rank_cutscene("vanguard"), 10,  GIF_W),
    ("rank-adept",     PHONE,  rank_cutscene("adept"),    10,  GIF_W),
    ("rank-elite",     PHONE,  rank_cutscene("elite"),    10,  GIF_W),
    ("rank-vanguard",  TABLET, rank_cutscene("vanguard"), 10,  340),
    ("supernova",      PHONE,  supernova,                 8,   GIF_W),
    ("supernova",      TABLET, supernova,                 8,   340),
]


def main(argv):
    only = argv[argv.index("--only") + 1].lower() if "--only" in argv else None
    out = argv[argv.index("--out") + 1] if "--out" in argv else ROOT + "/recordings"
    os.makedirs(out, exist_ok=True)

    srv, port = serve()
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path=CHROME)
        for key, dev, body, fps, width in SCENES:
            if only and only not in key:
                continue
            label, w, h = dev
            name = "%s-%s" % (key, label)
            print("%s  %dx%d" % (name, w, h))
            ctx, pg = new_page(br, port, w, h, SEED)
            rec = Recorder(pg)
            body(pg, rec)
            write_gif(rec.stop(), "%s/%s.gif" % (out, name),
                      fps=fps, width=width)
            ctx.close()
        br.close()
    srv.shutdown()
    print("\nwritten to %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
