#!/usr/bin/env python3
"""check-tours.py - do the app's tooltips still point at things that exist?

The fourth question, after "is anything broken" (the sweep), "did it land
where I meant it to" (check-positions) and "does the app still DO the right
thing" (check-behaviour). This one is narrower and it exists because of a
specific, silent failure mode:

    renderStep() does `if(!el){ advance(); return; }`

A tour step whose target selector no longer matches anything is SKIPPED, in
silence. Nothing throws, nothing logs, the tour still runs and still looks
fine - it is just shorter than it was written to be. That is how the Profile
tour lost its calendar step: the row was rebuilt as .profile-classline and
the step went on pointing at .cal-profile-row, which is a Settings class.
Four steps were declared, three were ever shown, and the only way to notice
was to count them.

So this counts them. For every tour in the app it walks the real thing on a
real screen and asserts:

  - every step declared in the source actually renders (no silent skips);
  - each tooltip lands fully inside the viewport;
  - the tour ends rather than looping.

It also asserts that every `startSimpleTour` call site in index.html is
covered by a scenario below, on the same principle as SCREENS in
sweep-layout.py: a green run is only worth what it looked at, and a tour
added without a scenario here is a tour nothing checks.

Run on both reference devices, since a tooltip that fits a 440px phone can
still be pushed off a 834px iPad (and the other way round).

    python3 tools/check-tours.py
    python3 tools/check-tours.py --only profile
"""

import functools
import http.server
import json
import re
import socket
import sys
import threading

from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = __file__.rsplit("/tools/", 1)[0]
INDEX = ROOT + "/index.html"

DEVICES = [("iPhone 17 Pro Max", 440, 956), ("iPad Pro 11\"", 834, 1194)]

# Each scenario arms one tour and drives the app to the screen that runs it.
# `flag` is the store field the screen checks; `setup` is evaluated in the
# page to reach that screen. `source` is the line the declared step count is
# read from, so the two can never drift apart by hand.
SCENARIOS = [
    # The one tour with no store flag at all: it is gated by
    # `pendingMainMenuTour`, a module-level variable set when onboarding
    # finishes, so there is nothing to seed and it has to be called by hand
    # from Home. (Seeding a "seenMainMenuTour" does nothing - no such field
    # exists, which is worth knowing before anyone adds one.)
    {"key": "mainmenu", "flag": None, "source": "startMainMenuTour",
     "setup": "showHome(); startMainMenuTour()",
     "note": "the bottom bar, the daily question, the flares"},
    {"key": "modeselect", "flag": "seenModeSelectTour", "source": "showModeSelect",
     "setup": "showModeSelect()", "note": "Drill / Exam / Game / Virtual Room"},
    {"key": "unitselect", "flag": "seenUnitSelectTour", "source": "showSetup",
     "setup": "cfg.mode='drill'; showSetup()", "note": "unit cards, the count, Start"},
    {"key": "vroomunits", "flag": "seenUnitSelectTour", "source": "showVirtualRoomSetup",
     "setup": "showVirtualRoomSetup()", "note": "same steps, reached a different way"},
    {"key": "settings", "flag": "seenSettingsTour", "source": "showAppearance",
     "setup": "showAppearance()", "note": "one step per section"},
    {"key": "profile", "flag": "seenProfileTour", "source": "showProfile",
     "setup": "showProfile('profile')", "note": "avatar, calendar, Stats, Badges, Rank"},
    {"key": "rankings", "flag": "seenRewardsTour", "source": "showRankings",
     "setup": "showRankings()", "note": "the three boards, search, Find me"},
    # summarize() runs at the end of a test and needs a finished run behind
    # it, which no cold mount can produce. Declared here so the coverage
    # check below still sees it, and skipped in the walk.
    {"key": "firstresults", "flag": "seenFirstResultsTour", "source": "summarize",
     "setup": None, "note": "end of the first test - needs a real run"},
]

SEED = {
    "onboardingComplete": True, "firstName": "Madison", "avatarChar": "ninja",
    "points": 12400, "tourRev": 99,
    "lifetime": {"points": 12400, "answered": 2100, "correct": 1840, "drillPlays": 40,
                 "examPlays": 9, "gamePlays": 6, "perfectTests": 51,
                 "longestStreak": 44, "currentStreak": 12},
    "unitPerfects": {"Professionalism and Ethics": 35, "TCOLE Rules": 35,
                     "Penal Code": 35, "Racial Profiling": 22},
}


def declared_steps(src):
    """How many steps each tour's source actually declares.

    Counts `target:` inside the array literal handed to startSimpleTour,
    matching brackets rather than guessing, so a step carrying a nested
    object or an array cannot throw the count off.
    """
    out = {}
    for m in re.finditer(r"startSimpleTour\(\s*\[", src):
        i = m.end() - 1
        depth, j = 0, i
        while j < len(src):
            if src[j] == "[":
                depth += 1
            elif src[j] == "]":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        block = src[i:j]
        # which function is this call inside?
        fn = None
        for f in re.finditer(r"^function ([A-Za-z0-9_]+)\(", src[:m.start()], re.M):
            fn = f.group(1)
        out.setdefault(fn, 0)
        out[fn] += len(re.findall(r"\btarget\s*:", block))
    # startMainMenuTour builds `steps` as a variable and passes it by name.
    m = re.search(r"function startMainMenuTour\(\)\{(.*?)\n\}", src, re.S)
    if m:
        out["startMainMenuTour"] = len(re.findall(r"\btarget\s*:", m.group(1)))
    return out


def serve(src_path):
    so = socket.socket(); so.bind(("127.0.0.1", 0))
    port = so.getsockname()[1]; so.close()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)

    class Quiet(handler.func if hasattr(handler, "func") else http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", port),
        functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def walk_tour(pg):
    """Click through a running tour, one step at a time."""
    steps = []
    for _ in range(16):
        st = pg.evaluate("""()=>{
          const tt=document.getElementById('tour-tooltip');
          if(!tt) return null;
          const r=tt.getBoundingClientRect();
          return { text:(document.getElementById('tour-text')||{}).textContent||'',
                   onScreen: r.top>=-1 && r.bottom<=innerHeight+1
                             && r.left>=-1 && r.right<=innerWidth+1 };}""")
        if not st:
            break
        steps.append(st)
        pg.evaluate("()=>document.getElementById('tour-next')?.click()")
        pg.wait_for_timeout(650)
    return steps


def main(argv):
    only = None
    if "--only" in argv:
        only = argv[argv.index("--only") + 1].lower()

    src = open(INDEX, encoding="utf-8").read()
    declared = declared_steps(src)

    # Coverage: every startSimpleTour call site needs a scenario.
    sites = set(declared) - {None}
    covered = {s["source"] for s in SCENARIOS}
    missing = sorted(sites - covered)
    failures = []
    if missing:
        failures.append("tours with no scenario in this file: %s" % ", ".join(missing))
        print("MISSING SCENARIO for: %s" % ", ".join(missing))

    srv, port = serve(INDEX)
    checked = 0
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path=CHROME)
        for dev, w, h in DEVICES:
            print("\n%s  %dx%d" % (dev, w, h))
            for sc in SCENARIOS:
                if only and only not in sc["key"]:
                    continue
                want = declared.get(sc["source"], 0)
                if sc["setup"] is None:
                    print("  %-12s  skipped (%s), %d step(s) declared"
                          % (sc["key"], sc["note"], want))
                    continue
                seed = dict(SEED)
                if sc["flag"]:
                    seed[sc["flag"]] = False
                for other in SCENARIOS:
                    if other["flag"] and other["flag"] != sc["flag"]:
                        seed[other["flag"]] = True
                ctx = br.new_context(viewport={"width": w, "height": h})
                pg = ctx.new_page()
                pg.add_init_script(
                    "Object.defineProperty(navigator,'standalone',{get:()=>true});")
                pg.add_init_script(
                    "try{localStorage.setItem('class26e.freshstart','1');localStorage.setItem('class26e.frame.ok','go-live-1');localStorage.setItem('class26e.drill.v1',%s)}catch(e){}"
                    % json.dumps(json.dumps(seed)))
                pg.goto("http://127.0.0.1:%d/index.html" % port)
                pg.wait_for_timeout(2000)
                pg.evaluate("()=>document.getElementById('splashscreen')?.remove()")
                pg.evaluate("()=>{%s}" % sc["setup"])
                pg.wait_for_timeout(1500)
                got = walk_tour(pg)
                ctx.close()
                checked += 1
                off = [i + 1 for i, s in enumerate(got) if not s["onScreen"]]
                bad = []
                if len(got) != want:
                    bad.append("%d of %d steps rendered - a target matched nothing"
                               % (len(got), want))
                if off:
                    bad.append("tooltip off-screen at step(s) %s"
                               % ", ".join(map(str, off)))
                if bad:
                    for b in bad:
                        failures.append("%s / %s: %s" % (dev, sc["key"], b))
                    print("  %-12s  FAIL  %s" % (sc["key"], "; ".join(bad)))
                else:
                    print("  %-12s  ok    %d/%d steps, all on screen"
                          % (sc["key"], len(got), want))
        br.close()
    srv.shutdown()

    print("\n%d tour run(s) checked across %d device(s)" % (checked, len(DEVICES)))
    if failures:
        print("\nFAILURES")
        for f in failures:
            print("  * %s" % f)
        return 1
    print("every declared step renders, and no tooltip leaves the viewport")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
