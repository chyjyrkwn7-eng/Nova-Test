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
OUT = os.environ.get("SHOOT_OUT", os.path.dirname(os.path.abspath(__file__)) + "/walk")
INSET_RE = re.compile(r"env\(safe-area-inset-(top|bottom|left|right)(?:\s*,[^()]*)?\)")
STANDALONE = """
Object.defineProperty(navigator,'standalone',{get:()=>true,configurable:true});
(function(){ const mm = window.matchMedia.bind(window);
  window.matchMedia = q => /display-mode:\\s*standalone/.test(q)
    ? {matches:true, media:q, addListener(){}, removeListener(){},
       addEventListener(){}, removeEventListener(){}, onchange:null, dispatchEvent(){return false;}}
    : mm(q); })();"""

# A screenshot with no status bar drawn is a screenshot with an unexplained
# band of empty pixels at the top, and it has now been misread twice - once
# as a bug in the bottom tab bar, once as the update banner "not aligned to
# the top". The app genuinely paints under the status bar (viewport-fit=
# cover), so this draws what iOS draws over it: the inset's own height, a
# clock and an indicator blob. Purely a screenshot aid - it is injected by
# this tool and exists nowhere in the app.
STATUS_BAR = """
addEventListener('DOMContentLoaded', function(){
  var s = document.createElement('style');
  s.textContent = '#__statusbar{position:fixed;top:0;left:0;right:0;height:__H__px;z-index:9999;'
    + 'pointer-events:none;display:flex;align-items:center;justify-content:space-between;'
    + 'padding:0 max(22px, env(safe-area-inset-left,0px));font:600 15px/1 ui-sans-serif,system-ui,sans-serif;'
    + 'color:#F3F5F7;text-shadow:0 1px 2px rgba(0,0,0,.45)}'
    + '#__statusbar i{display:block;width:26px;height:12px;border:1.5px solid rgba(243,245,247,.85);'
    + 'border-radius:3px;position:relative}'
    + '#__statusbar i::after{content:"";position:absolute;inset:1.5px;right:7px;background:#F3F5F7;border-radius:1px}';
  document.head.appendChild(s);
  var b = document.createElement('div');
  b.id = '__statusbar';
  b.innerHTML = '<span>9:41</span><i></i>';
  var put = function(){ if(!document.getElementById('__statusbar')) document.body.appendChild(b); };
  put(); setInterval(put, 400);
});"""

# A leaderboard with people on it. The Firebase CDN is blocked in the
# sandbox, so the three Rankings boards would otherwise show exactly one
# row - your own, synthesised by liveEntries() - which is a true picture
# of this machine and a useless picture of the app. This stubs
# window.firebase before any page script runs, so initFirebase() picks it
# up by its normal path and the boards fill with classmates.
#
# It is a SCREENSHOT AID and lives nowhere near the app. Nothing here is
# written back anywhere: every write resolves and discards.
# Characters come from AVATAR_CHARACTERS and nowhere else: ninja, ghost,
# queen, wizard, grizzly, alien, samurai, dragon. buildAvatarCharSVGSafe
# falls back to the default for an id it does not know, so an invented
# one does not fail loudly - it just puts four ninjas on the board.
CLASSMATES = [
    ("MADI-0001", "Madison", "ninja",   23, 4, 141, 0, 640),
    ("DEVO-0002", "Devonte", "ghost",   31, 6, 188, 0, 1180),
    ("ALEX-0003", "Alex",    "grizzly", 47, 9, 262, 0, 2310),
    ("KIMB-0004", "Kim",     "alien",   12, 2,  64, 0, 275),
    ("PATR-0005", "Pat",     "wizard",  58, 11, 310, 0, 1875),
    ("LEEA-0006", "Lee",     "dragon",  72, 15, 402, 3, 3040),
    ("RAYM-0007", "Ray",     "queen",    8, 1,  27, 0, 90),
    ("JOSE-0008", "Jose",    "samurai", 39, 7, 205, 0, 1425),
    ("TARA-0009", "Tara",    "ghost",   19, 3,  96, 0, 510),
    ("BROO-0010", "Brooke",  "queen",   27, 5, 150, 0, 980),
]
FAKE_FIREBASE = """
(function(){
  var ROWS = __ROWS__;
  function snapOf(name){
    var rows = name === 'leaderboard' ? ROWS : [];
    return { forEach: function(cb){ rows.forEach(function(r){
      cb({ id: r.code, data: function(){ return r; } }); }); } };
  }
  function docRef(){
    return {
      get: function(){ return Promise.resolve({ exists:false, data:function(){ return null; } }); },
      set: function(){ return Promise.resolve(); },
      update: function(){ return Promise.resolve(); },
      delete: function(){ return Promise.resolve(); },
      onSnapshot: function(next){
        setTimeout(function(){ next({ exists:false, data:function(){ return null; } }); }, 40);
        return function(){};
      }
    };
  }
  function collRef(name){
    var c = {
      doc: function(){ return docRef(); },
      where: function(){ return c; },
      onSnapshot: function(next){
        setTimeout(function(){ next(snapOf(name)); }, 60);
        return function(){};
      }
    };
    return c;
  }
  window.firebase = {
    apps: [],
    initializeApp: function(){ this.apps.push({}); },
    firestore: function(){ return { collection: collRef }; }
  };
})();"""

# The account the post-onboarding screens are shot with. A fresh sign-up
# renders every one of them as its EMPTY state, which is half the app
# photographed as "nothing here yet".
# __WEEK__ is substituted for this week's Monday when the seed is
# written, so the This Week board has something on it. A hard-coded key
# would age out and read 0 XP the following Monday.
SEED = ('{"firstName":"Madison","avatarChar":"ninja","onboardingComplete":true,'
        '"weekKey":"__WEEK__","weekPoints":640,'
        '"leaderboardOptIn":true,"lastModified":1700000000000,'
        '"tourRev":99,"seenProfileTour":true,"seenModeSelectTour":true,"seenUnitSelectTour":true,'
        '"seenMainMenuTour":true,"seenRankingsTour":true,"seenAppearanceTour":true,'
        '"unitPerfects":{"Professionalism and Ethics":35,"Professional Policing":35,'
        '"TCOLE Rules":35,"Penal Code":35,"Racial Profiling":22,"Victims of Crime":14,'
        '"Verbal Communication":31,"Identity Crimes":8,"Civil Process and Liability":19},'
        '"lifetime":{"points":12400,"answered":5400,"correct":4980,"drillPlays":64,'
        '"examPlays":22,"gamePlays":9,"perfectTests":141,"currentStreak":23,'
        '"longestStreak":57}}')

# label, w, h, insets, installed
DEVICES = [
    ("iphone-17-pro-max", 440,  956, (62, 0, 34, 0), True),
    ("ipad-pro-11",       834, 1194, (24, 0, 20, 0), True),
    ("iphone-15-non-max", 393,  852, (59, 0, 34, 0), True),
    ("ipad-mini",         744, 1133, (24, 0, 20, 0), True),
    ("ipad-pro-12-9",    1024, 1366, (24, 0, 20, 0), True),
    ("dell-latitude",    1366,  638, (0, 0, 0, 0),  False),
    ("macbook-pro-14",   1512,  852, (0, 0, 0, 0),  False),
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

def week_key_now():
    """The same key weekKeyNow() builds in the app: the Monday of this
    week, as YYYY-MM-DD. A row whose week is anything else counts as 0
    on the This Week board - which is correct behaviour and made every
    fake classmate read "0 XP this week" in the screenshots until this
    existed."""
    import datetime
    d = datetime.date.today()
    d -= datetime.timedelta(days=d.weekday())
    return d.isoformat()

def rows_json():
    import json
    wk = week_key_now()
    return json.dumps([
        {"code": c, "firstName": n, "avatarChar": a, "level": lv,
         "badges": bd, "hundos": hu, "mystery": my, "correct": hu * 34,
         "week": wk, "weekPoints": wp}
        for (c, n, a, lv, bd, hu, my, wp) in CLASSMATES])


def new_page(br, ins, installed, seeded):
    """One context, set up the way a real device would arrive at it."""
    ctx = br.new_context(viewport={"width": new_page.w, "height": new_page.h},
                         device_scale_factor=2)
    if installed:
        ctx.add_init_script(STANDALONE)
    ctx.add_init_script(FAKE_FIREBASE.replace("__ROWS__", rows_json()))
    if seeded:
        ctx.add_init_script(
            "try{localStorage.setItem('class26e.freshstart','1');localStorage.setItem('class26e.drill.v1', %s);"
            "localStorage.setItem('class26e.synccode','MADI-0001');"
            "localStorage.setItem('class26e.frame.ok','go-live-1');"
            "localStorage.setItem('class26e.daily.seen','x');}catch(e){}"
            % ("'" + SEED.replace("__WEEK__", week_key_now()) + "'"))
    page = ctx.new_page()
    body = patched(ins)
    page.route("**/index.html", lambda route, request, b=body: route.fulfill(
        status=200, headers={"content-type": "text/html; charset=utf-8"}, body=b))
    if ins[0]:
        page.add_init_script(STATUS_BAR.replace("__H__", str(ins[0])))
    return ctx, page


def main():
    os.makedirs(OUT, exist_ok=True)
    # Madison asked for the two reference devices only, so that is the
    # default: an iPhone 17 Pro Max and an iPad Pro 11". The other five
    # are still here and still correct - "--all" runs the lot, and a
    # substring runs one.
    args = [a for a in sys.argv[1:]]
    every = "--all" in args
    args = [a for a in args if not a.startswith("--")]
    only = args[0] if args else None
    if not only and not every:
        only = ("iphone-17-pro-max", "ipad-pro-11")
    srv, url = serve()
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(executable_path=CHROME)
            for label, w, h, ins, installed in DEVICES:
                if only and (label not in only if isinstance(only, tuple)
                             else only not in label): continue
                new_page.w, new_page.h = w, h
                errs = []

                def shot(page, n, name, bar_ok=False):
                    page.wait_for_timeout(350)
                    page.screenshot(path=f"{OUT}/{label}-{n:04.1f}-{name}.png")
                    bad = page.evaluate("""()=>{
                        const t = document.querySelector('.bottomtabs');
                        const loading = document.getElementById('genprofile-overlay')
                                     || document.getElementById('splashscreen');
                        return {bar: (!t || t.hidden) ? 0 : Math.round(t.getBoundingClientRect().height),
                                tourOverLoading: !!(loading && document.getElementById('tour-tooltip'))};}""")
                    # Home and everything past it is supposed to have a tab
                    # bar; an onboarding screen never is.
                    if bad["bar"] and not bar_ok:
                        print(f"  !! {label} {name}: TAB BAR ON AN ONBOARDING SCREEN ({bad['bar']}px)")
                    if not bad["bar"] and bar_ok:
                        print(f"  !! {label} {name}: TAB BAR MISSING")
                    if bad["tourOverLoading"]:
                        print(f"  !! {label} {name}: TOOLTIP OVER A LOADING SCREEN")

                # ---------- 1. a genuinely fresh install, walked ----------
                ctx, page = new_page(br, ins, installed, seeded=False)
                page.on("pageerror", lambda e: errs.append(str(e)[:160]))
                page.goto(url)
                # The splash IS a screen and it is one of the ones asked
                # for. The Firebase CDN is blocked here so it never clears
                # itself, which for once is convenient.
                page.wait_for_timeout(900)
                shot(page, 0, "splash")
                page.wait_for_timeout(2400)
                page.evaluate("document.getElementById('splashscreen')?.remove()")
                page.wait_for_timeout(400)

                shot(page, 1, "welcome")
                # the sign-in-with-a-code screen, then back
                page.click(".next.ghost.cosmic-welcome-btn"); shot(page, 2, "sign-in-with-code")
                page.fill(".synccode-entry-panel .searchbox", "MADI-0001"); page.wait_for_timeout(250)
                shot(page, 2.5, "sign-in-with-code-filled")
                page.click(".synccode-entry-panel .back-link"); page.wait_for_timeout(400)
                # the create-account path
                page.click(".cosmic-welcome-btn.playbtn");            shot(page, 3, "whats-new")
                page.click(".releasenotes-panel .next.playbtn");      shot(page, 4, "what-this-actually-is")
                page.click(".welcomeintro-panel .next.playbtn");      shot(page, 5, "pick-your-class")
                page.click(".classselect-panel .modecard"); page.wait_for_timeout(250)
                shot(page, 5.5, "pick-your-class-picked")
                page.click(".classselect-panel .next.playbtn");       shot(page, 6, "enter-a-username")
                page.fill(".searchbox", "Madison"); page.wait_for_timeout(250)
                # The armed state as well as the gated one: these screens
                # hide Continue until something is chosen, and where it
                # lands once it appears is the thing worth looking at.
                shot(page, 6.5, "enter-a-username-filled")
                page.click(".onboarding-shortform-panel .next.playbtn"); shot(page, 7, "choose-a-character")
                page.click(".avatarchar-option"); page.wait_for_timeout(250)
                shot(page, 7.5, "choose-a-character-picked")
                page.click(".charselect-panel .next.playbtn");        shot(page, 8, "youre-all-set")
                page.click(".onboarding-shortform-panel .next.playbtn")
                # The loading screen, caught while it is still up. Waiting
                # for it to detach is what stops a Settings tour being
                # photographed on top of it; catching it first is how it
                # gets photographed at all.
                page.wait_for_selector("#genprofile-overlay", timeout=8000)
                page.wait_for_timeout(900)
                shot(page, 8.5, "generating-profile")
                page.wait_for_selector("#genprofile-overlay", state="detached", timeout=25000)
                page.wait_for_timeout(1200)
                shot(page, 9, "home-with-tour", bar_ok=True)
                for _ in range(16):                            # click the tour through
                    if not page.evaluate("()=>!!document.getElementById('tour-next')"): break
                    page.evaluate("()=>document.getElementById('tour-next').click()")
                    page.wait_for_timeout(260)
                page.wait_for_timeout(900)
                shot(page, 10, "home-brand-new", bar_ok=True)
                ctx.close()

                # ---------- 2. a used account, walked from Home ----------
                # Everything past onboarding is shot against a real one. A
                # fresh sign-up renders Profile, Badges, Ranks and all three
                # boards as their EMPTY states, which is half the app
                # photographed as "nothing here yet".
                ctx, page = new_page(br, ins, installed, seeded=True)
                page.on("pageerror", lambda e: errs.append(str(e)[:160]))
                page.goto(url); page.wait_for_timeout(3000)
                page.evaluate("document.getElementById('splashscreen')?.remove()")
                page.wait_for_timeout(600)
                shot(page, 20, "home", bar_ok=True)

                def home(pg):
                    pg.evaluate("()=>document.getElementById('bottomtab-home').click()")
                    pg.wait_for_timeout(500)

                # the daily question, and Home's own "?" is how you get there
                page.click(".daily-question-fab"); page.wait_for_timeout(700)
                shot(page, 21, "daily-question", bar_ok=False)
                home(page)

                # Start Studying -> mode -> units
                page.click(".panel.home.screen-home-actual .playbtn"); page.wait_for_timeout(600)
                shot(page, 22, "mode-selection", bar_ok=True)
                page.click(".modeselect .modecard"); page.wait_for_timeout(600)
                shot(page, 23, "unit-selection", bar_ok=True)
                # the start sheet that unit selection opens
                page.evaluate("""()=>{const b=[...document.querySelectorAll('.screen-setup button')]
                  .find(x=>/start/i.test(x.textContent)); if(b) b.click();}""")
                page.wait_for_timeout(700)
                shot(page, 23.5, "unit-selection-start-sheet", bar_ok=True)
                home(page)

                # the three boards
                page.evaluate("()=>document.getElementById('bottomtab-rewards').click()")
                page.wait_for_timeout(900)
                # The bottom tab is Leaderboard now and its first board is
                # This Week, not Level. The filenames say so - a screenshot
                # named for a board that no longer exists is a screenshot
                # nobody can match to the app.
                for i, (key, name) in enumerate([("week", "week"), ("badges", "badges"),
                                                 ("hundos", "hundos")]):
                    page.evaluate("""(n)=>{const b=[...document.querySelectorAll('.profiletabs .iconbtn')][n];
                      if(b) b.click();}""", i)
                    page.wait_for_timeout(700)
                    shot(page, 24 + i * 0.1, "leaderboard-" + name, bar_ok=True)

                # the four Profile tabs
                page.evaluate("()=>document.getElementById('bottomtab-profile').click()")
                page.wait_for_timeout(900)
                # Whole numbers per tab, halves for a scrolled view. The
                # first version numbered them 25 + i/10 and added 0.05 for
                # the scroll, which rounds two different screens to the same
                # filename - one silently overwrote the other.
                # THE ORDER IS THE BUTTONS' ORDER, and this list had it
                # wrong: the tabs run Profile, Stats, Badges, Rank, so
                # index 1 was being saved as "badges" while showing Stats
                # and index 2 the other way round. A mislabelled
                # screenshot is worse than a missing one - it gets
                # reported as a bug on the screen it is not of.
                for i, name in enumerate(["profile", "stats", "badges", "rank"]):
                    page.evaluate("""(n)=>{const b=[...document.querySelectorAll('.profiletabs .iconbtn')][n];
                      if(b) b.click();}""", i)
                    page.wait_for_timeout(800)
                    shot(page, 25 + i, "profile-" + name, bar_ok=True)
                    if name in ("badges", "rank"):
                        page.evaluate("()=>window.scrollTo(0, document.documentElement.scrollHeight)")
                        page.wait_for_timeout(450)
                        shot(page, 25 + i + 0.5, "profile-" + name + "-scrolled", bar_ok=True)
                        page.evaluate("()=>window.scrollTo(0,0)"); page.wait_for_timeout(300)

                # settings, top and bottom
                page.evaluate("()=>document.getElementById('bottomtab-settings').click()")
                page.wait_for_timeout(900)
                shot(page, 29, "settings", bar_ok=True)
                page.evaluate("()=>window.scrollTo(0, document.documentElement.scrollHeight)")
                page.wait_for_timeout(500)
                shot(page, 29.5, "settings-scrolled", bar_ok=True)

                real = [e for e in errs if not any(k in e for k in
                        ("firebase", "firestore", "gstatic", "Failed to fetch", "net::"))]
                print(f"{label}: done" + (f"  ERRORS {real[:2]}" if real else ""))
                ctx.close()
            br.close()
    finally:
        srv.shutdown()

main()
