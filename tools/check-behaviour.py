#!/usr/bin/env python3
"""Does the app still DO the right thing? (Not: does it still look right.)

The sweep asks "is anything broken on this device", check-positions asks
"did it land where I meant it to", check-fixes asks "is this fix in effect
here", and check-sync asks "does this build still keep people's accounts".
None of them can see a splash that paints in the corner for 250ms, a swipe
that lands on nothing, a back link that renders an empty screen, or a badge
that is only awarded on some of the ways to earn it.

Every check here was written against a build where it FAILED. Run it with
--against on that build to watch it fail, which is the only thing that
makes a green run mean anything:

  python3 tools/check-behaviour.py
  python3 tools/check-behaviour.py --against /path/to/old-index.html

Chromium has no Firestore here (the CDN is blocked in the sandbox), so fbDb
is stubbed where a check needs it. Exits non-zero on any failure.
"""
import functools
import http.server
import io
import os
import re
import socket
import sys
import threading
import time

from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSET_RE = re.compile(r"env\(safe-area-inset-(top|bottom|left|right)(?:\s*,[^()]*)?\)")
SRC = (sys.argv[sys.argv.index("--against") + 1] if "--against" in sys.argv
       else os.path.join(ROOT, "index.html"))

PHONE = ("iPhone 17 Pro Max", 440, 956)
TABLET = ("iPad Pro 11\"", 834, 1194)
DEVICES = [PHONE, TABLET]

FIRESTORE_STUB = """
  window.__stub = function(){
    fbDb = { collection: function(){ return { doc: function(){ return {
      set: function(){ return Promise.resolve(); },
      get: function(){ return Promise.resolve({ exists: false }); },
      update: function(){ return Promise.resolve(); },
      delete: function(){ return Promise.resolve(); }
    }; } }; } };
    onSnapshotResilient = function(ref, onNext){
      setTimeout(function(){ onNext({ forEach: function(){} }); }, 20);
      return function(){};
    };
  };
"""

# A launch where visualViewport reports a box 1.6x too big for the first
# 250ms: content centred inside an oversized box lands low and right, then
# snaps back, which is exactly how this was reported. The recorder samples
# EVERY frame from inside the page - sampling from Playwright missed the
# window on the faster device and reported a pass on a build with the bug.
LAUNCH_LIE = """
(() => {
  const t0 = Date.now();
  const bad = () => Date.now() - t0 < 250;
  const fake = {
    get width(){ return (bad() ? 1.6 : 1) * window.innerWidth; },
    get height(){ return (bad() ? 1.6 : 1) * window.innerHeight; },
    get offsetLeft(){ return 0; }, get offsetTop(){ return 0; },
    get scale(){ return 1; },
    addEventListener(){}, removeEventListener(){},
  };
  Object.defineProperty(window, 'visualViewport', { get: () => fake, configurable: true });
  window.__frames = [];
  (function rec(){
    const g = document.getElementById('splash-group');
    if(g){
      const r = g.getBoundingClientRect();
      window.__frames.push({ o: parseFloat(getComputedStyle(g).opacity),
        cx: r.left + r.width / 2, cy: r.top + r.height / 2,
        vw: window.innerWidth, vh: window.innerHeight });
    }
    if(window.__frames.length < 120) requestAnimationFrame(rec);
  })();
})();
"""

USED_ACCOUNT = (
    '{"firstName":"Madison","avatarChar":"ninja","onboardingComplete":true,'
    '"leaderboardOptIn":true,"lastModified":1700000000000,"seenProfileTour":true,"tourRev":99,'
    '"testHistory":[{"ts":1700000000000,"mode":"exam","label":"Practice test",'
    '"score":92,"total":25,"correct":23,"units":["1"],"answers":[]}],'
    '"lifetime":{"points":14820,"answered":5400,"correct":4980,"drillPlays":64,'
    '"examPlays":22,"gamePlays":9,"perfectTests":141,"currentStreak":23,'
    '"longestStreak":57}}')

BODY = INSET_RE.sub(lambda m: "0px", io.open(SRC, encoding="utf-8").read()) \
    .replace("let fbDb = null;", "let fbDb = null;" + FIRESTORE_STUB, 1)

_sock = socket.socket(); _sock.bind(("127.0.0.1", 0))
PORT = _sock.getsockname()[1]; _sock.close()


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


SERVER = http.server.ThreadingHTTPServer(
    ("127.0.0.1", PORT), functools.partial(_Quiet, directory=ROOT))
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/index.html" % PORT

FAILURES = []


def check(name, ok, detail=""):
    print("  %-4s %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  -> " + str(detail)) if detail else ""))
    if not ok:
        FAILURES.append(name)


def open_page(ctx):
    pg = ctx.new_page()
    pg.route("**/index.html", lambda r: r.fulfill(
        status=200, headers={"content-type": "text/html; charset=utf-8"}, body=BODY))
    return pg


def booted(br, w, h, seed=None, init=None, touch=False):
    """A context on Home with the splash gone and Firestore stubbed."""
    ctx = br.new_context(viewport={"width": w, "height": h},
                         has_touch=touch, is_mobile=touch)
    if init:
        ctx.add_init_script(init)
    if seed:
        ctx.add_init_script("try{localStorage.setItem('class26e.freshstart','1');"
                            "localStorage.setItem('class26e.drill.v1', '%s');}catch(e){}" % seed)
    pg = open_page(ctx)
    pg.goto(URL)
    pg.wait_for_timeout(2600)
    pg.evaluate("()=>{document.getElementById('splashscreen')?.remove(); __stub();}")
    return ctx, pg


# --------------------------------------------------------------------------
def check_launch(br):
    print("\n1. the splash is centred from the first frame it is visible")
    for label, w, h in DEVICES:
        ctx = br.new_context(viewport={"width": w, "height": h})
        ctx.add_init_script(LAUNCH_LIE)
        pg = open_page(ctx)
        pg.goto(URL)
        pg.wait_for_timeout(1400)
        frames = pg.evaluate("() => window.__frames || []")
        worst, shown_off = 0, None
        for f in frames:
            off = max(abs(f["cx"] - f["vw"] / 2), abs(f["cy"] - f["vh"] / 2))
            if f["o"] > 0.02:
                worst = max(worst, off)
                if off > 4 and shown_off is None:
                    shown_off = (round(off), round(f["cx"]), round(f["cy"]))
        end = pg.evaluate("""() => {
          const g = document.getElementById('splash-group');
          if(!g) return null;
          const r = g.getBoundingClientRect();
          return { o: parseFloat(getComputedStyle(g).opacity),
                   cx: r.left + r.width/2, cy: r.top + r.height/2,
                   vw: window.innerWidth, vh: window.innerHeight };}""")
        end_off = (max(abs(end["cx"] - end["vw"] / 2), abs(end["cy"] - end["vh"] / 2))
                   if end else 999)
        check("%s never paints off-centre" % label, shown_off is None,
              shown_off or ("worst %dpx" % worst))
        check("%s settles centred and visible" % label,
              end is not None and end["o"] > 0.5 and end_off <= 4,
              "%dpx" % end_off)
        ctx.close()


# --------------------------------------------------------------------------
def _swipe(cdp, x0, y0, dx, dy=0, steps=8):
    """A real touch drag through CDP, not a synthetic DOM event."""
    cdp.send("Input.dispatchTouchEvent",
             {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
    for i in range(1, steps + 1):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [
            {"x": x0 + dx * i / steps, "y": y0 + dy * i / steps}]})
        time.sleep(0.012)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


ACTIVE_TAB = ("()=>{const b=document.querySelector('.panel .navsegment .iconbtn.active');"
              "return b ? b.textContent : null;}")


def check_swipe(br):
    print("\n2. a thumb swipe changes the top tab, anywhere on the screen")
    for label, w, h in DEVICES:
        ctx, pg = booted(br, w, h, seed=USED_ACCOUNT, touch=True)
        cdp = ctx.new_cdp_session(pg)
        for screen, show in [("Rankings", "()=>showRankings('level')"),
                             ("Profile", "()=>showProfile()")]:
            pg.evaluate(show)
            pg.wait_for_timeout(500)
            start = pg.evaluate(ACTIVE_TAB)
            # Low on the screen and with vertical drift, because that is
            # where a thumb actually lands: on a tablet the panel ends
            # halfway up, and swipes below it used to hit nothing.
            _swipe(cdp, w * 0.75, h * 0.45, -w * 0.5, 18)
            pg.wait_for_timeout(400)
            moved = pg.evaluate(ACTIVE_TAB)
            _swipe(cdp, w * 0.25, h * 0.45, w * 0.5, -18)
            pg.wait_for_timeout(400)
            back = pg.evaluate(ACTIVE_TAB)
            check("%s / %s swipes both ways" % (label, screen),
                  moved != start and back == start,
                  "%s -> %s -> %s" % (start, moved, back))
        # The listeners live on .wrap, which outlives the screen inside it.
        pg.evaluate("()=>showRankings('level')"); pg.wait_for_timeout(250)
        pg.evaluate("()=>showHome()"); pg.wait_for_timeout(250)
        pg.evaluate("()=>showRankings('level')"); pg.wait_for_timeout(400)
        _swipe(cdp, w * 0.75, h * 0.45, -w * 0.5, 18)
        pg.wait_for_timeout(400)
        once = pg.evaluate(ACTIVE_TAB)
        pg.evaluate("()=>showHome()"); pg.wait_for_timeout(400)
        _swipe(cdp, w * 0.75, h * 0.45, -w * 0.5, 18)
        pg.wait_for_timeout(400)
        still_home = pg.evaluate("()=>!!document.querySelector('.panel.home')")
        check("%s a second visit still steps exactly one tab" % label,
              once == "Badges", once)
        check("%s leaving detaches the swipe" % label, still_home)
        ctx.close()


# --------------------------------------------------------------------------
VISIBLE = """()=>{
  const p = document.querySelector('#stage .panel');
  if(!p) return { panel:false };
  const vis = [...p.children].filter(c => !c.hidden && c.getBoundingClientRect().height > 0).length;
  return { panel:true, visibleChildren:vis, height:Math.round(p.getBoundingClientRect().height),
           activeTab:(document.querySelector('.panel .navsegment .iconbtn.active')||{}).textContent||null };}"""


def check_navigation(br):
    print("\n3. a back link lands on a screen with something on it")
    ctx, pg = booted(br, TABLET[1], TABLET[2], seed=USED_ACCOUNT)
    for label, show in [("test review -> Back to Profile", "()=>showTestReviewList()"),
                        ("calendar -> Back to Profile", "()=>showCalendar()")]:
        pg.evaluate(show)
        pg.wait_for_timeout(300)
        if not pg.query_selector(".back-link"):
            check(label, False, "no back link on the screen")
            continue
        pg.click(".back-link")
        pg.wait_for_timeout(400)
        st = pg.evaluate(VISIBLE)
        # A blank Profile is a real, shipped shape: the panel is there and
        # holds only its tab strip, ~112px tall, with no tab marked active.
        check(label, st["panel"] and st["visibleChildren"] >= 2
              and st["height"] > 200 and bool(st["activeTab"]), st)
    ctx.close()


# --------------------------------------------------------------------------
EARN_A_BADGE = """(a)=>{
  const { mode, nUnits, startAt, vroom } = a;
  const topics = [...new Set(QUESTIONS.map(q => (q.topic||'').trim()))].filter(Boolean);
  const chosen = topics.slice(0, nUnits);
  store.unitPerfects = {}; chosen.forEach(t => { store.unitPerfects[t] = startAt; });
  store.pendingBadgeUnlocks = []; store.lifetime.perfectTests = 0;
  if(vroom){ beginVirtualRoomTest(chosen, null, null); }
  else {
    cfg.mode = mode; cfg.source = 'all'; cfg.units = chosen.slice();
    order = [].concat(...chosen.map(t => QUESTIONS.map((q,i) => [q,i])
      .filter(([q]) => (q.topic||'').trim() === t).map(([,i]) => i)));
    runTrackable = true; timedOut = false; runMode = mode; runLabel = null;
  }
  attempts = {}; picked = {}; timedOutSet = {};
  order.forEach(qi => { attempts[qi] = 1; picked[qi] = optionOrder(qi).indexOf(QUESTIONS[qi].answer); });
  summarize();
  return { queue:(store.pendingBadgeUnlocks||[]).slice(),
           banners:[...document.querySelectorAll('.badgebanner')].length,
           hundos: store.lifetime.perfectTests };}"""


def check_badges(br):
    print("\n4. a badge is earned by every route to 35, and only then")
    ctx, pg = booted(br, TABLET[1], TABLET[2])
    cases = [
        ("drill, one unit, 34 -> 35", {"mode": "drill", "nUnits": 1, "startAt": 34, "vroom": False}, 1, 1),
        ("exam, two units, 34 -> 35", {"mode": "exam", "nUnits": 2, "startAt": 34, "vroom": False}, 2, 2),
        ("game, one unit at 10", {"mode": "game", "nUnits": 1, "startAt": 10, "vroom": False}, 0, 0),
        ("Virtual Room, two units, 34", {"mode": "exam", "nUnits": 2, "startAt": 34, "vroom": True}, 2, 2),
        ("a unit already at 35", {"mode": "drill", "nUnits": 1, "startAt": 35, "vroom": False}, 0, 0),
    ]
    for label, args, want_queue, want_banners in cases:
        r = pg.evaluate(EARN_A_BADGE, args)
        check(label, len(r["queue"]) == want_queue and r["banners"] == want_banners,
              "queued %s, %d banner(s)" % (r["queue"], r["banners"]))
    ctx.close()


# --------------------------------------------------------------------------
def check_cutscene(br):
    print("\n5. queued badges play on the main menu, back to back")
    seed = ('{"firstName":"Madison","avatarChar":"ninja","onboardingComplete":true,'
            '"lastModified":1700000000000,"seenProfileTour":true,"tourRev":99,'
            '"pendingBadgeUnlocks":["Professionalism and Ethics","TCOLE Rules"],'
            '"unitPerfects":{"Professionalism and Ethics":35,"TCOLE Rules":35},'
            '"lifetime":{"points":14820,"correct":880,"perfectTests":141}}')
    for label, w, h in DEVICES:
        ctx, pg = booted(br, w, h, seed=seed)
        pg.evaluate("()=>showHome()")
        pg.wait_for_timeout(1500)
        first = pg.evaluate("""()=>{const o=document.getElementById('badge-cutscene');
          if(!o) return null; const a=o.querySelector('.badge-cutscene-art').getBoundingClientRect();
          return { name:(o.querySelector('.badge-cutscene-name')||{}).textContent,
                   inView: a.top >= 0 && a.bottom <= window.innerHeight,
                   queue:(store.pendingBadgeUnlocks||[]).length };}""")
        check("%s the first badge plays, on screen" % label,
              bool(first) and first["inView"] and first["queue"] == 1, first)
        pg.wait_for_timeout(2600)
        second = pg.evaluate("""()=>{const o=document.getElementById('badge-cutscene');
          return o ? (o.querySelector('.badge-cutscene-name')||{}).textContent : null;}""")
        check("%s the second follows it" % label, second == "TCOLE Rules", second)
        pg.wait_for_timeout(3200)
        after = pg.evaluate("()=>({overlay:!!document.getElementById('badge-cutscene'),"
                            " queue:(store.pendingBadgeUnlocks||[]).length})")
        check("%s the queue drains and the overlay goes" % label,
              not after["overlay"] and after["queue"] == 0, after)
        ctx.close()


# --------------------------------------------------------------------------
def check_ranks(br):
    """The Ranks tab, which replaced the Mastery Ladder and Unlocks.

    Written against the build where it did not exist, so every check
    here fails on --against. The one that matters most is the fill: the
    whole point of the rewrite is that a rank part-way earned is
    part-way lit, and a clip-path that never moves off its CSS default
    looks identical to one that works until you measure it.
    """
    print("\n6. ranks: what you are, what you have, what is next")
    # Level 23 (12,400 XP on the 300 @ +5% curve) and 4 badges reaches
    # Veteran (20 / 4) and leaves Vanguard (30 / 6) as the next one.
    seed = ('{"firstName":"Madison","avatarChar":"ninja","onboardingComplete":true,'
            '"lastModified":1700000000000,"seenProfileTour":true,"tourRev":99,'
            '"unitPerfects":{"Professionalism and Ethics":35,"Professional Policing":35,'
            '"TCOLE Rules":35,"Penal Code":35},'
            '"lifetime":{"points":12400,"correct":4980,"perfectTests":141}}')
    ctx, pg = booted(br, 834, 1194, seed=seed)
    got = pg.evaluate("""()=>({level:levelOf(store), badges:badgeCountOf(store),
                              rank:rankOf(store)})""")
    check("the seed holds the rank its numbers earn",
          got["level"] == 23 and got["badges"] == 4 and got["rank"] == "veteran", got)

    # Boundary behaviour, cheap and worth having: one short of a rank is
    # the rank below, and both halves have to be met.
    edges = pg.evaluate("""()=>({
      exact: rankOfStats(20, 4, 0), levelShort: rankOfStats(19, 4, 0),
      badgeShort: rankOfStats(20, 3, 0), nothing: rankOfStats(1, 0, 0),
      top: rankOfStats(70, 14, 0), topShort: rankOfStats(70, 13, 0)})""")
    # The third argument is the old Secret Flare count. It is passed as 0
    # everywhere now and the top rank reaches anyway, which is the whole
    # point of the check: nothing gates on it any more.
    check("a rank needs both halves of its rule, and only those two",
          edges["exact"] == "veteran" and edges["levelShort"] == "ranger" and
          edges["badgeShort"] == "ranger" and edges["nothing"] is None and
          edges["top"] == "titan" and edges["topShort"] == "elite", edges)

    pg.evaluate("()=>showProfile('ranks')")
    pg.wait_for_timeout(1500)
    tabs = pg.evaluate("""()=>[...document.querySelectorAll('.profiletabs .iconbtn')]
                              .map(b=>b.textContent)""")
    # Stats before Badges, and the last one is "Ladder" - the bottom bar
    # already says Rankings and two things called the same was reported
    # as confusing. The key is still "ranks"; only the label moved.
    check("four tabs, in the order asked for, and no second Rankings",
          tabs == ["Profile", "Stats", "Badges", "Ladder"], tabs)

    cards = pg.evaluate("""()=>[...document.querySelectorAll('.rankcard')].map(c=>({
      name:c.querySelector('.rankcard-name').textContent,
      state:c.className.match(/is-\\w+/g).join(' '),
      chip:c.querySelector('.rankcard-state').textContent,
      meter:!!c.querySelector('.rankcard-meter'),
      rewards:c.querySelectorAll('.rankcard-rewards li').length}))""")
    check("seven ranks, named as ranks and not as flares",
          [c["name"] for c in cards] ==
          ["Iron", "Bronze", "Silver", "Gold", "Sapphire", "Amethyst", "Supernova"],
          [c["name"] for c in cards])
    # The states are the whole point of the rewrite: "what you are, what
    # you have, and what is to come" has to read without decoding a
    # colour, so each card says it in a word.
    check("every card says which of the three states it is in",
          [c["chip"] for c in cards] ==
          ["Reached", "Reached", "You are here", "Up next", "Locked", "Locked", "Locked"],
          [c["chip"] for c in cards])
    check("the rank you hold is the one marked is-here",
          [i for i, c in enumerate(cards) if "is-here" in c["state"]] == [2],
          [c["state"] for c in cards])
    # A reached rank is not a progress bar. It was, for one build, and
    # that was the thing explicitly asked against.
    # ONLY the next one up. Every unreached rank carried a meter, which
    # put a half-full bar on Supernova while you were working on Gold -
    # progress towards something you are not working towards.
    check("only the rank you are climbing to carries a meter",
          [c["meter"] for c in cards] == [False, False, False, True, False, False, False],
          [c["meter"] for c in cards])
    # Three rewards on the bottom three, FOUR on the top four - those
    # each hand over a character as well (Officer, Clown, Robot,
    # Astronaut). The list is exactly what you get rather than a fixed
    # shape with a gap in it, so this asserts the shape per rank rather
    # than one number across all seven.
    check("every rank lists what it hands over, top four include the character",
          [c["rewards"] for c in cards] == [3, 3, 3, 4, 4, 4, 4],
          [c["rewards"] for c in cards])
    chars = pg.evaluate("""()=>({
      count: AVATAR_CHARACTERS.length,
      gated: AVATAR_CHARACTERS.filter(c=>c.unlock).map(c=>c.unlock),
      lockedGated: AVATAR_CHARACTERS.filter(c=>c.unlock).map(c=>isLockedCharacter(c.id)),
      lockedFree: AVATAR_CHARACTERS.filter(c=>!c.unlock).map(c=>isLockedCharacter(c.id))})""")
    check("four characters, gated on the top four ranks",
          chars["count"] == 12 and
          chars["gated"] == ["vanguard", "adept", "elite", "titan"], chars)
    # The seed holds Silver, so none of the four is reachable yet and
    # none of the original eight is ever locked.
    check("a rank you have not reached keeps its character locked",
          all(chars["lockedGated"]) and not any(chars["lockedFree"]), chars)

    # A locked rank still shows its colour. Four of the seven used to be
    # redrawn in grey, so you could not see what you were heading for.
    hues = pg.evaluate("""()=>[...document.querySelectorAll('.rankcard')].map(c=>
      c.style.getPropertyValue('--rank-color').trim())""")
    check("every rank carries its own colour, reached or not",
          len(set(hues)) == 7 and all(h.startswith("#") for h in hues), hues)

    # ONE ROW PER RANK ON EVERY DEVICE. The upright four-across card is
    # gone: seven of them wrapped four-then-three on a tablet, so the
    # climb read left-to-right and then left-to-right again. The phone
    # arrangement was already the simple one and was already liked, so a
    # wide screen gets the same thing with more room - which means the
    # emblem stays BESIDE the name at every width, and a rank's card
    # spans the track whatever the screen is.
    lay = pg.evaluate("""()=>{const cs=[...document.querySelectorAll('.rankcard')];
      const t=document.querySelector('.ranktrack').getBoundingClientRect();
      const c=cs[0];
      const r=s=>c.querySelector(s).getBoundingClientRect();
      return {beside: r('.rankcard-head').left >= r('.rankcard-art').right - 1,
              perRow:cs.filter(x=>Math.abs(x.getBoundingClientRect().top -
                                           c.getBoundingClientRect().top) < 2).length,
              full:Math.round(c.getBoundingClientRect().width) >= Math.round(t.width) - 2};}""")
    check("one full-width row per rank on a tablet too",
          lay["beside"] and lay["perRow"] == 1 and lay["full"], lay)

    # SEVEN DIFFERENT MARKS, not one mark at seven sizes - and not the
    # chevron set that replaced it either ("I'm not a fan of the iron
    # bronze silver icons after all"). They are seven celestial bodies
    # now: a dead rock, a ringed world, a crescent, a sun, a comet, a
    # galaxy, and the burst. The check is structural rather than a look:
    # no two ranks produce the same shape signature, and the top one is
    # the most elaborate thing in the set.
    shapes = pg.evaluate("""()=>{
      const out={};
      TIER_ORDER_FULL.forEach(k=>{
        const svg=buildRankEmblemSVG(k);
        const ds=[...svg.querySelectorAll('path')].map(p=>p.getAttribute('d')||'');
        out[k]={n:ds.length, sig:ds.join('|').length};
      });
      return out;}""")
    order = ["rookie", "ranger", "veteran", "vanguard", "adept", "elite", "titan"]
    check("no two ranks draw the same thing",
          len({shapes[k]["sig"] for k in order}) == 7,
          {k: shapes[k]["sig"] for k in order})
    check("the top rank is the busiest mark in the set",
          shapes["titan"]["n"] > max(shapes[k]["n"] for k in order[:6]),
          {k: shapes[k]["n"] for k in order})

    # The Secret Flares are gone: the hunt, the Eclipse colour it
    # unlocked, and the clause it put on the top rank's requirement.
    # "The mystery flares should be scrapped and moved. That means the
    # requirement they have, the theme, the unlock."
    gone = pg.evaluate("""()=>({
      box: !!document.querySelector('.ranks-tab .unlock-row'),
      anyMention: /Secret Flare/i.test(document.querySelector('.ranks-tab').textContent),
      topReq: [...document.querySelectorAll('.rankcard-req')].pop().textContent,
      eclipse: ACCENTS.indexOf('mystery') !== -1
    })""")
    check("no unlock box and nothing on the tab mentions a Secret Flare",
          not gone["box"] and not gone["anyMention"], gone)
    check("the top rank asks for levels and badges and nothing else",
          "Secret" not in gone["topReq"] and "Level" in gone["topReq"], gone["topReq"])
    check("the Eclipse colour is off the list of themes",
          not gone["eclipse"], gone)
    ctx.close()
    ctx2, pg2 = booted(br, 393, 852, seed=seed)
    pg2.evaluate("()=>showProfile('ranks')")
    pg2.wait_for_timeout(1200)
    lay2 = pg2.evaluate("""()=>{const cs=[...document.querySelectorAll('.rankcard')];
      const t=document.querySelector('.ranktrack').getBoundingClientRect();
      const c=cs[0];
      const r=s=>c.querySelector(s).getBoundingClientRect();
      return {beside: r('.rankcard-head').left >= r('.rankcard-art').right - 1,
              perRow:cs.filter(x=>Math.abs(x.getBoundingClientRect().top -
                                           c.getBoundingClientRect().top) < 2).length,
              full:Math.round(c.getBoundingClientRect().width) >= Math.round(t.width) - 2};}""")
    check("one full-width row per rank on a phone, name beside the emblem",
          lay2["beside"] and lay2["perRow"] == 1 and lay2["full"], lay2)
    ctx2.close()
    ctx, pg = booted(br, 834, 1194, seed=seed)
    pg.evaluate("()=>showProfile('ranks')")
    pg.wait_for_timeout(1200)

    # The rank has to show up where people are listed, or it is a tab
    # nobody else ever sees.
    row = pg.evaluate("""()=>{const a=document.createElement('span');
      a.className='lb-avatar'; a.appendChild(buildAvatarCharSVGSafe('ninja'));
      decorateAvatar(a, 34, 6, 0);
      const un=document.createElement('span'); un.className='lb-avatar';
      decorateAvatar(un, 1, 0, 0);
      return {rank:(a.querySelector('.lb-rankmark')||{}).title,
              level:!!a.querySelector('.vroom-level'),
              unranked:!un.querySelector('.lb-rankmark'),
              unrankedExtras:un.childNodes.length};}""")
    check("a person's row carries their rank", row["rank"] == "Gold", row)
    # The small blue level number beside the character was asked for,
    # built, and then asked against. Two marks on one 42px character is
    # one too many, and a board that ranks on the number is already
    # printing it.
    check("no level number beside the character", not row["level"], row)
    check("somebody below the first rank gets nothing at all",
          row["unranked"] and row["unrankedExtras"] == 0, row)

    # And on the REAL screen, not just through the helper. The three
    # Rankings boards had a second row builder of their own with its own
    # level chip, so when the number came off everywhere it stayed on the
    # screen it is most visible on - and the rank emblem never arrived
    # there at all. Testing the builder alone is what missed it.
    # With no network the board carries exactly the row liveEntries()
    # synthesises for you, which is one row and enough to check.
    pg.evaluate("()=>{ store.leaderboardOptIn = true; syncCode = 'MADI-0001';"
                "      document.getElementById('bottomtab-rewards').click(); }")
    pg.wait_for_timeout(1200)
    board = pg.evaluate("""()=>{
      const rows = [...document.querySelectorAll('.rank-row')];
      return {rows:rows.length,
              marks:rows.filter(r=>r.querySelector('.lb-rankmark')).length,
              levelChips:document.querySelectorAll('.rank-level').length};}""")
    check("a rankings row carries the rank emblem and no level chip",
          board["rows"] >= 1 and board["marks"] == board["rows"]
          and board["levelChips"] == 0, board)
    ctx.close()
    ctx.close()


def main():
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path=CHROME)
        try:
            check_launch(br)
            check_swipe(br)
            check_navigation(br)
            check_badges(br)
            check_cutscene(br)
            check_ranks(br)
        finally:
            br.close()
    SERVER.shutdown()
    print("\n%s  (%d failure(s))"
          % ("ALL PASS" if not FAILURES else "FAILED: " + ", ".join(FAILURES),
             len(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
