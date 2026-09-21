#!/usr/bin/env python3
"""Screenshot the app by WALKING it, not by mounting screens.

Mounting an onboarding screen against a seeded account is what put a bottom
tab bar into earlier screenshots of screens that never have one. This clicks
through from a genuinely fresh install, exactly as a person would.
"""
import functools, http.server, io, os, re, socket, sys, threading
from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = "/home/user/Nova-Test"
OUT = os.path.dirname(os.path.abspath(__file__)) + "/walk"
INSET_RE = re.compile(r"env\(safe-area-inset-(top|bottom|left|right)(?:\s*,[^()]*)?\)")
STANDALONE = """
Object.defineProperty(navigator,'standalone',{get:()=>true,configurable:true});
(function(){ const mm = window.matchMedia.bind(window);
  window.matchMedia = q => /display-mode:\\s*standalone/.test(q)
    ? {matches:true, media:q, addListener(){}, removeListener(){},
       addEventListener(){}, removeEventListener(){}, onchange:null, dispatchEvent(){return false;}}
    : mm(q); })();"""

# label, w, h, insets, installed
DEVICES = [
    ("iphone-17-pro-max", 440,  956, (62, 0, 34, 0), True),
    ("ipad-pro-11",       834, 1194, (24, 0, 20, 0), True),
    ("iphone-15-non-max", 393,  852, (59, 0, 34, 0), True),
    ("ipad-mini",         744, 1133, (24, 0, 20, 0), True),
    ("ipad-pro-12-9",    1024, 1366, (24, 0, 20, 0), True),
    ("dell-latitude",    1366,  638, (0, 0, 0, 0),  False),
]

def patched(insets):
    src = io.open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    t, r, b, l = insets
    v = {"top": f"{t}px", "right": f"{r}px", "bottom": f"{b}px", "left": f"{l}px"}
    return INSET_RE.sub(lambda m: v[m.group(1)], src)

def serve():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Q, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}/index.html"

def main():
    os.makedirs(OUT, exist_ok=True)
    srv, url = serve()
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(executable_path=CHROME)
            for label, w, h, ins, installed in DEVICES:
                ctx = br.new_context(viewport={"width": w, "height": h}, device_scale_factor=2)
                if installed:
                    ctx.add_init_script(STANDALONE)
                page = ctx.new_page(); body = patched(ins)
                page.route("**/index.html", lambda route, request, b=body: route.fulfill(
                    status=200, headers={"content-type": "text/html; charset=utf-8"}, body=b))
                errs = []
                page.on("pageerror", lambda e: errs.append(str(e)[:160]))
                page.goto(url); page.wait_for_timeout(3200)
                page.evaluate("document.getElementById('splashscreen')?.remove()")
                page.wait_for_timeout(400)

                def shot(n, name):
                    page.wait_for_timeout(350)
                    page.screenshot(path=f"{OUT}/{label}-{n:02d}-{name}.png")
                    bar = page.evaluate("()=>{const t=document.querySelector('.bottomtabs');"
                                        "return t.hidden?0:Math.round(t.getBoundingClientRect().height);}")
                    if bar: print(f"  !! {label} {name}: TAB BAR VISIBLE ({bar}px)")

                shot(1, "welcome")
                # the sign-in-with-a-code screen, then back
                page.click(".next.ghost.cosmic-welcome-btn"); shot(2, "sign-in-with-code")
                page.click(".synccode-entry-panel .back-link"); page.wait_for_timeout(400)
                # the create-account path
                page.click(".cosmic-welcome-btn.playbtn");            shot(3, "whats-new")
                page.click(".releasenotes-panel .next.playbtn");      shot(4, "what-this-actually-is")
                page.click(".welcomeintro-panel .next.playbtn");      shot(5, "pick-your-class")
                page.click(".classselect-panel .modecard"); page.wait_for_timeout(250)
                page.click(".classselect-panel .next.playbtn");       shot(6, "enter-a-username")
                page.fill(".searchbox", "Madison"); page.wait_for_timeout(250)
                page.click(".onboarding-shortform-panel .next.playbtn"); shot(7, "choose-a-character")
                page.click(".avatarchar-option"); page.wait_for_timeout(250)
                page.click(".charselect-panel .next.playbtn");        shot(8, "youre-all-set")
                page.click(".onboarding-shortform-panel .next.playbtn")
                page.wait_for_timeout(6000)                   # generating-profile overlay
                shot(9, "home-with-tour")
                for _ in range(14):                            # click the tour through
                    if not page.evaluate("()=>!!document.getElementById('tour-next')"): break
                    page.evaluate("()=>document.getElementById('tour-next').click()")
                    page.wait_for_timeout(260)
                page.wait_for_timeout(600)
                shot(10, "home")
                page.evaluate("()=>document.getElementById('bottomtab-settings').click()")
                shot(11, "settings")
                real = [e for e in errs if not any(k in e for k in
                        ("firebase", "firestore", "gstatic", "Failed to fetch", "net::"))]
                print(f"{label}: done" + (f"  ERRORS {real[:2]}" if real else ""))
                ctx.close()
            br.close()
    finally:
        srv.shutdown()

main()
