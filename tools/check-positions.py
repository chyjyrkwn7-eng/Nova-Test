#!/usr/bin/env python3
"""Do the positioned things land where they were meant to, on every device?

sweep-layout.py audits for defects (overflow, collisions, insets, JS errors).
This asks a different question, and a green sweep does not answer it: do the
things that were deliberately POSITIONED land where they were meant to, on
every device - not just on the two that happened to get screenshotted.

It reports, per device and per launch mode:

  * the spread between every onboarding screen's Continue button (should be 0)
  * whether any onboarding screen overflows its viewport
  * Home's Start Studying gap above the tagline vs below to the tab bar
  * the daily question button's size, and the Welcome hint's clearance

    python3 tools/check-positions.py              # portrait
    python3 tools/check-positions.py --landscape

Written after a session whose screenshots were only ever taken at 440x956
and 834x1194 shipped three defects a 66/66 sweep had passed.
"""
import functools, http.server, io, os, re, socket, sys, threading
from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = "/home/user/Nova-Test"
INSET_RE = re.compile(r"env\(safe-area-inset-(top|bottom|left|right)(?:\s*,[^()]*)?\)")
CHROME_H = {"ios-phone": (110, 60), "ios-tablet": (90, 90),
            "android": (56, 56), "desktop": (130, 130)}
DEVICES = [
    ("iPhone SE (1st gen)",     320,  568, "ios-phone",  (20, 0, 0, 0)),
    ("iPhone SE (2nd/3rd gen)", 375,  667, "ios-phone",  (20, 0, 0, 0)),
    ("iPhone 13 mini",          375,  812, "ios-phone",  (50, 0, 34, 0)),
    ("iPhone 14 / 15 / 16",     393,  852, "ios-phone",  (59, 0, 34, 0)),
    ("iPhone 16/17 Pro Max",    440,  956, "ios-phone",  (62, 0, 34, 0)),
    ("iPad mini (6th gen)",     744, 1133, "ios-tablet", (24, 0, 20, 0)),
    ("iPad mini (home button)", 768, 1024, "ios-tablet", (20, 0, 0, 0)),
    ("iPad 10.2\"",             810, 1080, "ios-tablet", (24, 0, 20, 0)),
    ("iPad Air / 10th",         820, 1180, "ios-tablet", (24, 0, 20, 0)),
    ("iPad Pro 11\"",           834, 1194, "ios-tablet", (24, 0, 20, 0)),
    ("iPad Pro 12.9\"",        1024, 1366, "ios-tablet", (24, 0, 20, 0)),
    ("iPad Pro 13\" (M4)",     1032, 1376, "ios-tablet", (24, 0, 20, 0)),
    ("Android phone",           360,  800, "android",    (24, 0, 24, 0)),
    ("Android tablet",          800, 1280, "android",    (24, 0, 24, 0)),
    ("Dell Latitude",          1366,  768, "desktop",    (0, 0, 0, 0)),
    ("MacBook Pro 14-inch",    1512,  982, "desktop",    (0, 0, 0, 0)),
    ("MacBook Pro 16-inch",    1728, 1117, "desktop",    (0, 0, 0, 0)),
    ("Dell Latitude FHD",      1920, 1080, "desktop",    (0, 0, 0, 0)),
    ("MacBook Air",            1440,  900, "desktop",    (0, 0, 0, 0)),
    ("small laptop",           1280,  800, "desktop",    (0, 0, 0, 0)),
]
# Deliberately a USED account, not a blank one. With empty stats every
# populated screen - Profile, Rewards, the Leaderboard, the calendar, the
# review list, test history - renders its empty state, so the sweep was
# checking the layout of "nothing here yet" on half the app. Real points,
# a streak, test history and study log make those screens render the
# content people actually see.
SEED = """try{
 localStorage.setItem('class26e.synccode','ABCD-2345');
 var today = new Date(); var day = function(d){
   var t = new Date(today); t.setDate(t.getDate() - d);
   return t.getFullYear()+'-'+String(t.getMonth()+1).padStart(2,'0')+'-'+String(t.getDate()).padStart(2,'0');
 };
 var log = {}; for(var i=0;i<24;i++){ log[day(i)] = { seconds: 600 + i*37, answered: 12 + i }; }
 var hist = []; for(var j=0;j<9;j++){ hist.push({ date: day(j*2), mode: ['drill','exam','game'][j%3],
   score: 12 + j, total: 20, pct: Math.round((12+j)/20*100), seconds: 300 + j*20,
   units: ['Texas Penal Code'] }); }
 localStorage.setItem('class26e.drill.v1', JSON.stringify({name:'T',firstName:'Madison',avatarChar:'a',
   stats:{},testStats:{},studyLog:log,testHistory:hist,onboardingComplete:true,
   lifetime:{answered:840,correct:712,drillPlays:22,examPlays:9,gamePlays:6,perfectTests:3,
             currentStreak:11,longestStreak:17,points:6400},
   leaderboardOptIn:true,
   seenProfileTour:true,seenSettingsTour:true,
   seenRewardsTour:true,seenHomeTour:true,seenLadderTour:true,
   theme:{mode:'dark',accent:'ink',layout:'modern'}}));}catch(e){}"""
STANDALONE = """
Object.defineProperty(navigator,'standalone',{get:()=>true,configurable:true});
(function(){ const mm = window.matchMedia.bind(window);
  window.matchMedia = q => /display-mode:\\s*standalone/.test(q)
    ? {matches:true, media:q, addListener(){}, removeListener(){},
       addEventListener(){}, removeEventListener(){}, onchange:null, dispatchEvent(){return false;}}
    : mm(q); })();"""

ONBOARDING = ["showWelcomeIntro", "showClassSelection", "showWelcomeNamePrompt",
              "showWelcomeCharacterPrompt", "showWelcomeCodeEntry", "showWelcomeCodeReveal"]

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

ONBOARDING_SCREENS = {
    "showWelcome", "showWhatsNew", "showWelcomeIntro", "showClassSelection",
    "showWelcomeNamePrompt", "showWelcomeCharacterPrompt",
    "showWelcomeCodeEntry", "showWelcomeCodeReveal",
}

def run(page, fn):
    # See the note in sweep-layout.py: an onboarding screen is only ever
    # reached with the tab bar already hidden, and showWelcome() is what
    # hides it. Mounting one cold leaves the bar up and swaps
    # --panel-reserve, moving every button on the screen by 3.5rem.
    if fn in ONBOARDING_SCREENS:
        page.evaluate("showWelcome();")
        page.wait_for_timeout(110)
    page.evaluate(f"{fn}(); scrollTo(0,0);")
    page.wait_for_timeout(230)
    page.evaluate("document.querySelectorAll('.next.playbtn[hidden]').forEach(b=>b.hidden=false)")
    page.wait_for_timeout(90)

def main():
    landscape = "--landscape" in sys.argv
    srv, url = serve()
    rows, flags = [], []
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(executable_path=CHROME)
            for name, w, h, plat, ins in DEVICES:
                installed = plat != "desktop"
                if landscape:
                    w, h = h, w
                    if plat == "ios-phone": ins = (0, ins[0], 21, ins[0]) if ins[0] > 20 else (0, 0, 0, 0)
                if not installed:
                    h = max(320, h - CHROME_H[plat][1 if landscape else 0]); ins = (0, 0, 0, 0)
                ctx = br.new_context(viewport={"width": w, "height": h})
                ctx.add_init_script(SEED)
                if installed: ctx.add_init_script(STANDALONE)
                page = ctx.new_page(); body = patched(ins)
                page.route("**/index.html", lambda route, request, b=body: route.fulfill(
                    status=200, headers={"content-type": "text/html; charset=utf-8"}, body=b))
                page.goto(url); page.wait_for_timeout(2300)
                page.evaluate("document.getElementById('splashscreen')?.remove()")
                tag = f"{name} {w}x{h}" + (" browser" if not installed else "")

                # 1. every onboarding Continue on the same line
                tops, scrolls = [], []
                for fn in ONBOARDING:
                    run(page, fn)
                    m = page.evaluate("""()=>{const b=document.querySelector('.next.playbtn');
                      const r=b.getBoundingClientRect();
                      return {top:Math.round(r.top), bottom:Math.round(r.bottom),
                              sh:document.documentElement.scrollHeight, vh:innerHeight};}""")
                    tops.append(m["top"])
                    if m["sh"] > m["vh"] + 1: scrolls.append((fn, m["sh"] - m["vh"]))
                spread = max(tops) - min(tops)

                # 2. Welcome: where the hint lands
                run(page, "showWelcome")
                wel = page.evaluate("""()=>{const hint=document.querySelector('.cosmic-welcome-hint');
                  const hero=document.querySelector('.cosmic-hero-wrap');
                  const r=hint.getBoundingClientRect(), hr=hero.getBoundingClientRect();
                  return {hintGap:Math.round(innerHeight-r.bottom), heroTop:Math.round(hr.top),
                          heroH:Math.round(hr.height), gapHeroTitle:Math.round(
                            document.querySelector('.cosmic-welcome-title').getBoundingClientRect().top-hr.bottom),
                          sh:document.documentElement.scrollHeight, vh:innerHeight};}""")

                # 3. Home: Start Studying centred between the tagline and the tab bar
                run(page, "showHome")
                home = page.evaluate("""()=>{const b=document.querySelector('#nextbtn');
                  const tl=document.querySelector('.hometagline'); const tb=document.querySelector('.bottomtabs');
                  const br_=b.getBoundingClientRect();
                  const tlb = tl && tl.getBoundingClientRect().height>0 ? tl.getBoundingClientRect().bottom : null;
                  const tbt = tb && !tb.hidden ? tb.getBoundingClientRect().top : null;
                  const fab=document.querySelector('.daily-question-fab').getBoundingClientRect();
                  return {above: tlb!==null?Math.round(br_.top-tlb):null,
                          below: tbt!==null?Math.round(tbt-br_.bottom):null,
                          fab:[Math.round(fab.width),Math.round(fab.height)],
                          fabClearsTabs: tbt===null?null:Math.round(tbt-fab.bottom)};}""")
                rows.append((tag, spread, tops[0], scrolls, wel, home))

                if spread > 2: flags.append(f"{tag}: onboarding Continue spread {spread}px {tops}")
                if home["above"] is not None and home["below"] is not None:
                    d = abs(home["above"] - home["below"])
                    if d > 45: flags.append(f"{tag}: Start Studying off-centre by {d}px ({home['above']} above / {home['below']} below)")
                if home["below"] is not None and home["below"] < 8:
                    flags.append(f"{tag}: Start Studying only {home['below']}px above the tab bar")
                if wel["hintGap"] < 0: flags.append(f"{tag}: welcome hint off the bottom by {-wel['hintGap']}px")
                if scrolls: flags.append(f"{tag}: scrolls -> {scrolls}")
                ctx.close()
            br.close()
    finally:
        srv.shutdown()

    print(f"{'device':34} {'spread':>7} {'btnTop':>7} {'homeAbove/below':>17} {'fab':>9} {'hintGap':>8} {'heroH':>6}")
    for tag, spread, top, scrolls, wel, home in rows:
        ab = f"{home['above']}/{home['below']}"
        print(f"{tag:34} {spread:>7} {top:>7} {ab:>17} {str(home['fab']):>9} {wel['hintGap']:>8} {wel['heroH']:>6}")
    print()
    if flags:
        print("FLAGS")
        for f in flags: print("  *", f)
    else:
        print("no flags")

main()
