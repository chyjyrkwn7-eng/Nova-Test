#!/usr/bin/env python3
"""Check every main screen on every form factor the class actually uses.

Nova is used from a Home Screen app, from Safari and Chrome tabs, on iPhones,
iPads, Android tablets and Windows laptops (several classmates use a Dell
Latitude). A change that reads fine at 390x844 can be broken at 1366x768 -
the Start Studying button spent a while hidden behind the bottom tab bar on
exactly that laptop, because nothing here was ever looked at short and wide.

Reports only defects that are actually visible:

  * horizontal page scroll
  * an element painting outside the viewport sideways
  * the primary button overlapping, or hidden behind, the bottom tab bar
  * the tab bar itself off-screen or below the fold
  * uncaught JS errors (the blocked Firebase CDN is expected and ignored)

Elements inside a hidden branch, or clipped by an ancestor's overflow, are
skipped - an oversized decorative glow inside overflow:hidden is not a bug,
and counting it buries the ones that are.

    python3 tools/sweep-layout.py             # everything
    python3 tools/sweep-layout.py --only 1366 # form factors matching a string

Needs Playwright and the Chromium at CHROME below; exits 1 if anything fails.
"""
import argparse
import http.server
import os
import functools
import socket
import sys
import threading

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("playwright is not installed; this check needs it")

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FORM_FACTORS = [
    ("iPhone SE",              320,  568),
    ("small Android phone",    360,  640),
    ("iPhone 8 / SE 2",        375,  667),
    ("iPhone 14",              390,  844),
    ("iPhone 14 landscape",    844,  390),
    ("iPad mini portrait",     768, 1024),
    ("iPad portrait",          834, 1112),
    ("iPad landscape",        1024,  834),
    ("Android tablet",         800, 1280),
    ("Dell Latitude",         1366,  768),
    ("Dell Latitude in Chrome",1366,  640),
    ("laptop 1280x800",       1280,  800),
    ("laptop FHD",            1920, 1080),
    ("external display",      2560, 1440),
    ("half-height window",    1280,  520),
]

SCREENS = ["showHome", "showAppearance", "showProfile", "showRewards",
           "showLeaderboard", "showSetup"]

SEED = """try{
 localStorage.setItem('class26e.synccode','ABCD-2345');
 localStorage.setItem('class26e.drill.v1', JSON.stringify({name:'T',avatarChar:'a',
   stats:{},testStats:{},studyLog:{},seenProfileTour:true,seenSettingsTour:true,
   seenRewardsTour:true,theme:{mode:'dark',accent:'ink',layout:'modern'}}));}catch(e){}"""

EXPECTED_ERRORS = ("firebase", "firestore", "gstatic", "Failed to fetch", "net::")

AUDIT = """() => {
  const vw = innerWidth, vh = innerHeight, problems = [];
  if (document.documentElement.scrollWidth > vw + 1)
    problems.push(`horizontal page scroll (${document.documentElement.scrollWidth} > ${vw})`);
  const buried = el => {
    let p = el;
    while (p && p !== document.body) {
      const s = getComputedStyle(p);
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return true;
      p = p.parentElement;
    }
    return false;
  };
  const clipped = el => {
    let p = el.parentElement;
    while (p && p !== document.documentElement) {
      const s = getComputedStyle(p);
      if (s.overflow !== 'visible' || s.overflowX !== 'visible') return true;
      p = p.parentElement;
    }
    return false;
  };
  document.querySelectorAll('.wrap *, .bottomtabs, .bottomtabs *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    if (r.right <= vw + 1.5 && r.left >= -1.5) return;
    if (buried(el) || clipped(el)) return;
    problems.push(`${(el.className||el.tagName).toString().split(' ')[0]} painted outside the viewport (${Math.round(r.left)}..${Math.round(r.right)} of ${vw})`);
  });
  const btn = document.querySelector('#nextbtn,.next.playbtn');
  const tabs = document.querySelector('.bottomtabs');
  if (btn && tabs && !buried(tabs)) {
    const a = btn.getBoundingClientRect(), b = tabs.getBoundingClientRect();
    if (a.bottom > b.top + 1 && a.right > b.left && a.left < b.right)
      problems.push(`primary button is behind the tab bar by ${Math.round(a.bottom - b.top)}px`);
    if (a.bottom > vh + 1)
      problems.push(`primary button is below the fold by ${Math.round(a.bottom - vh)}px`);
  }
  if (tabs && !buried(tabs)) {
    const b = tabs.getBoundingClientRect();
    if (b.bottom > vh + 1) problems.push(`tab bar below the fold by ${Math.round(b.bottom - vh)}px`);
    if (b.right > vw + 1 || b.left < -1) problems.push(`tab bar off-screen sideways (${Math.round(b.left)}..${Math.round(b.right)} of ${vw})`);
  }
  return [...new Set(problems)];
}"""


def serve():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=ROOT)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}/index.html"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="only form factors whose label or size contains this")
    args = ap.parse_args()

    factors = [f for f in FORM_FACTORS
               if not args.only or args.only.lower() in f"{f[0]} {f[1]}x{f[2]}".lower()]
    if not factors:
        sys.exit(f"no form factor matches {args.only!r}")

    srv, url = serve()
    failures = 0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            for label, w, h in factors:
                ctx = browser.new_context(viewport={"width": w, "height": h})
                ctx.add_init_script(SEED)
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)[:160]))
                page.goto(url)
                page.wait_for_timeout(3000)
                page.evaluate("document.getElementById('splashscreen')?.remove()")
                found = {}
                for fn in SCREENS:
                    try:
                        if not page.evaluate(f"typeof {fn}==='function'"):
                            found[fn] = [f"{fn} is not defined"]
                            continue
                        page.evaluate(f"{fn}()")
                        page.wait_for_timeout(350)
                        hits = page.evaluate(AUDIT)
                        if hits:
                            found[fn] = hits
                    except Exception as exc:
                        found[fn] = [f"threw: {str(exc)[:80]}"]
                real = [e for e in errors if not any(k in e for k in EXPECTED_ERRORS)]
                if real:
                    found["(console)"] = real[:3]
                if found:
                    failures += 1
                    print(f"FAIL  {label} ({w}x{h})")
                    for fn, hits in found.items():
                        for hit in hits:
                            print(f"        {fn}: {hit}")
                else:
                    print(f"ok    {label} ({w}x{h})")
                ctx.close()
            browser.close()
    finally:
        srv.shutdown()

    print()
    print(f"{len(factors) - failures}/{len(factors)} form factors clean")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
