#!/usr/bin/env python3
"""Audit every screen, on every device, in every orientation, both ways in.

Nova is opened two quite different ways - added to the Home Screen, and from
a browser tab - and they do not lay out the same. A Home Screen app gets the
whole display and real safe-area insets (notch, status bar, home indicator);
a browser tab gets a shorter viewport with the browser's own chrome eating
the top and bottom and essentially no insets. A change can be correct in one
and broken in the other, and most of the bugs found in this app were exactly
that: invisible at 390x844 in a desktop browser, obvious on a real device.

So every combination is checked: each device, portrait and landscape, as an
installed app and as a browser tab.

Chromium reports every env(safe-area-inset-*) as 0 and has no display-mode
emulation, so both are simulated - the insets by substituting real values
into a served copy (the same trick as tools/sim-safe-area.py), standalone by
patching navigator.standalone and the display-mode media query. The inset
figures and the browser-chrome heights below are modelled, not measured from
hardware; they are documented per device so they can be corrected rather than
guessed at again.

What it reports (only defects that would actually be visible):

  * horizontal page scroll
  * an element painting outside the viewport sideways
  * the primary button overlapping, or hidden behind, the bottom tab bar
  * the tab bar off-screen or below the fold
  * interactive controls colliding with the notch or the home indicator
  * uncaught JS errors (the blocked Firebase CDN is expected and ignored)

Elements in a hidden branch, or clipped by an ancestor's overflow, are
skipped - an oversized decorative glow inside overflow:hidden is not a bug,
and counting it buries the ones that are.

    python3 tools/sweep-layout.py              # the whole matrix
    python3 tools/sweep-layout.py --quick      # one representative per family
    python3 tools/sweep-layout.py --only iPad  # substring match on the label

Exits non-zero if anything fails.
"""
import argparse
import functools
import http.server
import io
import os
import re
import socket
import sys
import threading

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("playwright is not installed; this check needs it")

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSET_RE = re.compile(r"env\(safe-area-inset-(top|bottom|left|right)(?:\s*,[^()]*)?\)")

# Browser chrome, in CSS px, taken off the viewport for a browser-tab run.
# iOS Safari's bars in portrait, less in landscape where it compacts; desktop
# browsers keep a tab strip plus an address bar.
CHROME_H = {"ios-phone": (110, 60), "ios-tablet": (90, 90),
            "android": (56, 56), "desktop": (130, 130)}

# name, css w, css h (portrait), platform,
# portrait insets (top,right,bottom,left), landscape insets
DEVICES = [
    ("iPhone SE (1st gen)",     320,  568, "ios-phone",  (20, 0, 0, 0),  (0, 0, 0, 0)),
    ("iPhone SE (2nd/3rd gen)", 375,  667, "ios-phone",  (20, 0, 0, 0),  (0, 0, 0, 0)),
    ("iPhone 13 mini",          375,  812, "ios-phone",  (50, 0, 34, 0), (0, 50, 21, 50)),
    ("iPhone 14 / 15 / 16",     393,  852, "ios-phone",  (59, 0, 34, 0), (0, 59, 21, 59)),
    ("iPhone 16 Pro Max",       440,  956, "ios-phone",  (62, 0, 34, 0), (0, 62, 21, 62)),
    ("iPad mini (6th gen)",     744, 1133, "ios-tablet", (24, 0, 20, 0), (24, 0, 20, 0)),
    ("iPad mini (home button)", 768, 1024, "ios-tablet", (20, 0, 0, 0),  (20, 0, 0, 0)),
    ("iPad 10.2\"",             810, 1080, "ios-tablet", (24, 0, 20, 0), (24, 0, 20, 0)),
    ("iPad Air / iPad 10th",    820, 1180, "ios-tablet", (24, 0, 20, 0), (24, 0, 20, 0)),
    ("iPad Pro 11\"",           834, 1194, "ios-tablet", (24, 0, 20, 0), (24, 0, 20, 0)),
    ("iPad Pro 12.9\"",        1024, 1366, "ios-tablet", (24, 0, 20, 0), (24, 0, 20, 0)),
    ("iPad Pro 13\" (M4)",     1032, 1376, "ios-tablet", (24, 0, 20, 0), (24, 0, 20, 0)),
    ("Android phone",           360,  800, "android",    (24, 0, 24, 0), (0, 24, 24, 24)),
    ("Android tablet",          800, 1280, "android",    (24, 0, 24, 0), (24, 0, 24, 0)),
    ("Dell Latitude",          1366,  768, "desktop",    (0, 0, 0, 0),   (0, 0, 0, 0)),
    ("Dell Latitude FHD",      1920, 1080, "desktop",    (0, 0, 0, 0),   (0, 0, 0, 0)),
    ("MacBook Air",            1440,  900, "desktop",    (0, 0, 0, 0),   (0, 0, 0, 0)),
    ("small laptop",           1280,  800, "desktop",    (0, 0, 0, 0),   (0, 0, 0, 0)),
    ("external display",       2560, 1440, "desktop",    (0, 0, 0, 0),   (0, 0, 0, 0)),
]

QUICK = {"iPhone 14 / 15 / 16", "iPad Pro 11\"", "iPad mini (6th gen)", "Dell Latitude"}

# Every screen that can be mounted cold, which is 26 of the app's 44 - not
# the 6 this started with. That gap is why a regression that left EVERY
# onboarding screen bunched at the top with dead space below it sailed
# through a sweep reporting 62/62 clean: none of those screens was in it.
# A screen that needs run state to mount (showBankProblems, showAnswerReview)
# or renders nothing on its own (showGeneratingProfile) is left out; anything
# else that can be called with no arguments belongs here.
SCREENS = [
    # onboarding, in the order someone actually meets it
    "showWelcome", "showWelcomeIntro", "showWelcomeNamePrompt",
    "showWelcomeCharacterPrompt", "showWelcomeCodeEntry", "showWelcomeCodeReveal",
    # the everyday screens
    "showHome", "showAppearance", "showProfile", "showRewards",
    "showLeaderboard", "showSetup", "showModeSelect", "showClassSelection",
    "showExamOptions", "showCalendar", "showTestReviewList",
    # the rest
    "showInstallGuide", "showInstallPlatformPicker", "showResetWarning",
    "showWhatsNew", "showReleaseHistory",
    "showVirtualRoomChoice", "showVirtualRoomSetup", "showVirtualRoomJoinEntry",
]

SEED = """try{
 localStorage.setItem('class26e.synccode','ABCD-2345');
 localStorage.setItem('class26e.drill.v1', JSON.stringify({name:'T',avatarChar:'a',
   stats:{},testStats:{},studyLog:{},seenProfileTour:true,seenSettingsTour:true,
   seenRewardsTour:true,seenHomeTour:true,seenLadderTour:true,
   theme:{mode:'dark',accent:'ink',layout:'modern'}}));}catch(e){}"""

STANDALONE = """
Object.defineProperty(navigator,'standalone',{get:()=>true,configurable:true});
(function(){ const mm = window.matchMedia.bind(window);
  window.matchMedia = q => /display-mode:\\s*standalone/.test(q)
    ? {matches:true, media:q, addListener(){}, removeListener(){},
       addEventListener(){}, removeEventListener(){}, onchange:null, dispatchEvent(){return false;}}
    : mm(q); })();"""

EXPECTED_ERRORS = ("firebase", "firestore", "gstatic", "Failed to fetch", "net::")

AUDIT = """(inset) => {
  const vw = innerWidth, vh = innerHeight, problems = [];
  if (document.documentElement.scrollWidth > vw + 1)
    problems.push(`horizontal page scroll (${document.documentElement.scrollWidth} > ${vw})`);
  const buried = el => { let p = el;
    while (p && p !== document.body) { const s = getComputedStyle(p);
      if (s.display==='none'||s.visibility==='hidden'||s.opacity==='0') return true;
      p = p.parentElement; } return false; };
  const clipped = el => { let p = el.parentElement;
    while (p && p !== document.documentElement) { const s = getComputedStyle(p);
      if (s.overflow!=='visible'||s.overflowX!=='visible') return true;
      p = p.parentElement; } return false; };
  const name = el => (el.className||el.tagName).toString().split(' ')[0] || el.tagName;

  document.querySelectorAll('.wrap *, .bottomtabs, .bottomtabs *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    if (r.right <= vw + 1.5 && r.left >= -1.5) return;
    if (buried(el) || clipped(el)) return;
    problems.push(`${name(el)} painted outside the viewport (${Math.round(r.left)}..${Math.round(r.right)} of ${vw})`);
  });

  const btn = document.querySelector('#nextbtn,.next.playbtn');
  const tabs = document.querySelector('.bottomtabs');
  if (btn && tabs && !buried(tabs)) {
    const a = btn.getBoundingClientRect(), b = tabs.getBoundingClientRect();
    if (a.bottom > b.top + 1 && a.right > b.left && a.left < b.right)
      problems.push(`primary button is behind the tab bar by ${Math.round(a.bottom-b.top)}px`);
    if (a.bottom > vh + 1)
      problems.push(`primary button is below the fold by ${Math.round(a.bottom-vh)}px`);
  }
  if (tabs && !buried(tabs)) {
    const b = tabs.getBoundingClientRect();
    if (b.bottom > vh + 1) problems.push(`tab bar below the fold by ${Math.round(b.bottom-vh)}px`);
    if (b.right > vw + 1 || b.left < -1)
      problems.push(`tab bar off-screen sideways (${Math.round(b.left)}..${Math.round(b.right)} of ${vw})`);
  }

  /* Anything you have to read or tap must clear the notch, the status bar
     and the home indicator. Backgrounds are SUPPOSED to run underneath all
     three, so only controls and text count here.
     Two distinctions that matter, and got this wrong the first time:
     only what is actually ON SCREEN counts - an element 400px down a
     scrollable page is below the fold, not under the home indicator - and
     for the BOTTOM inset only pinned UI counts, because in-flow content
     scrolling past the home indicator is how scrolling works. The top and
     side insets apply to everything visible: the audit resets the scroll
     first, so at rest nothing should sit under the status bar, and
     horizontal insets do not move with scrolling at all. */
  if (inset.top || inset.bottom || inset.left || inset.right) {
    const pinned = el => { let p = el;
      while (p && p !== document.body) { const s = getComputedStyle(p);
        if (s.position === 'fixed' || s.position === 'sticky') return true;
        p = p.parentElement; } return false; };
    const live = '.wrap button, .wrap a, .wrap input, .wrap select, .wrap textarea,'
               + '.wrap h1, .wrap h2, .wrap p, .bottomtab';
    document.querySelectorAll(live).forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return;
      if (r.bottom <= 0 || r.top >= vh) return;
      if (buried(el) || clipped(el)) return;
      if (!el.textContent.trim() && !el.matches('input,select,textarea')) return;
      /* Against the CONTENT box, not the border box. A full-bleed bar
         pinned to the bottom edge is supposed to reach the edge - that is
         what makes it full-bleed - and it clears the home indicator with
         padding, not by stopping short. Measuring the border box called
         every such bar a bug and would have trained us to ignore this
         check. What actually matters is where the text and controls land. */
      const cs = getComputedStyle(el);
      const padT = parseFloat(cs.paddingTop) || 0;
      const padB = parseFloat(cs.paddingBottom) || 0;
      const padL = parseFloat(cs.paddingLeft) || 0;
      const padR = parseFloat(cs.paddingRight) || 0;
      if (inset.top && r.top + padT < inset.top - 0.5)
        problems.push(`${name(el)} under the status bar / notch (content top ${Math.round(r.top + padT)} < ${inset.top})`);
      if (inset.bottom && pinned(el) && r.bottom - padB > vh - inset.bottom + 0.5)
        problems.push(`pinned ${name(el)} under the home indicator (content bottom ${Math.round(r.bottom - padB)} > ${vh - inset.bottom})`);
      if (inset.left && r.left + padL < inset.left - 0.5)
        problems.push(`${name(el)} under the left inset (content ${Math.round(r.left + padL)} < ${inset.left})`);
      if (inset.right && r.right - padR > vw - inset.right + 0.5)
        problems.push(`${name(el)} under the right inset (content ${Math.round(r.right - padR)} > ${vw - inset.right})`);
    });
  }
  return [...new Set(problems)];
}"""


def patched_html(insets):
    src = io.open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    top, right, bottom, left = insets
    values = {"top": f"{top}px", "right": f"{right}px", "bottom": f"{bottom}px", "left": f"{left}px"}
    return INSET_RE.sub(lambda m: values[m.group(1)], src)


def serve():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}/index.html"


def combinations(devices):
    for name, w, h, platform, ins_p, ins_l in devices:
        modes = ("browser",) if platform == "desktop" else ("home screen", "browser")
        for orientation in ("portrait", "landscape"):
            vw, vh = (w, h) if orientation == "portrait" else (h, w)
            insets = ins_p if orientation == "portrait" else ins_l
            for mode in modes:
                if mode == "browser":
                    chrome = CHROME_H[platform][0 if orientation == "portrait" else 1]
                    yield name, orientation, mode, vw, max(320, vh - chrome), (0, 0, 0, 0)
                else:
                    yield name, orientation, mode, vw, vh, insets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring of the device label")
    ap.add_argument("--quick", action="store_true", help="one representative per family")
    ap.add_argument("--verbose", action="store_true", help="print every passing combination")
    args = ap.parse_args()

    devices = DEVICES
    if args.quick:
        devices = [d for d in devices if d[0] in QUICK]
    if args.only:
        devices = [d for d in devices if args.only.lower() in d[0].lower()]
    if not devices:
        sys.exit(f"no device matches {args.only!r}")

    combos = list(combinations(devices))
    srv, url = serve()
    failures = 0
    cache = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            for label, orientation, mode, vw, vh, insets in combos:
                ctx = browser.new_context(viewport={"width": vw, "height": vh})
                ctx.add_init_script(SEED)
                if mode == "home screen":
                    ctx.add_init_script(STANDALONE)
                page = ctx.new_page()
                if any(insets):
                    if insets not in cache:
                        cache[insets] = patched_html(insets)
                    body = cache[insets]
                    # the handler is called with (route, request); binding the
                    # body as a third default keeps request out of the way
                    page.route("**/index.html", lambda route, request, b=body: route.fulfill(
                        status=200, headers={"content-type": "text/html; charset=utf-8"}, body=b))
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)[:160]))
                page.goto(url)
                page.wait_for_timeout(2600)
                page.evaluate("document.getElementById('splashscreen')?.remove()")
                ins = {"top": insets[0], "right": insets[1], "bottom": insets[2], "left": insets[3]}
                found = {}
                for fn in SCREENS:
                    try:
                        if not page.evaluate(f"typeof {fn}==='function'"):
                            found[fn] = [f"{fn} is not defined"]
                            continue
                        page.evaluate(f"{fn}(); scrollTo(0,0);")
                        page.wait_for_timeout(300)
                        hits = page.evaluate(AUDIT, ins)
                        if hits:
                            found[fn] = hits
                    except Exception as exc:
                        found[fn] = [f"threw: {str(exc)[:80]}"]
                real = [e for e in errors if not any(k in e for k in EXPECTED_ERRORS)]
                if real:
                    found["(console)"] = real[:3]
                tag = f"{label}, {orientation}, {mode} ({vw}x{vh})"
                if found:
                    failures += 1
                    print(f"FAIL  {tag}")
                    for fn, hits in found.items():
                        for hit in hits[:4]:
                            print(f"        {fn}: {hit}")
                elif args.verbose:
                    print(f"ok    {tag}")
                ctx.close()
            browser.close()
    finally:
        srv.shutdown()

    print()
    print(f"{len(combos)-failures}/{len(combos)} combinations clean "
          f"({len(devices)} devices x orientation x launch mode)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
