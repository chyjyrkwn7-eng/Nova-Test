#!/usr/bin/env python3
"""Two devices in one Virtual Room, for real.

Everything else in tools/ drives one page. A Virtual Room is the only
part of this app whose whole job is two devices agreeing, and the two
things reported about it - ready-up not showing up on the other device,
and the host seeing the test before everybody else - are both invisible
to a one-page harness. So this runs TWO TABS.

They are two real tabs in one browser context, which means they share an
origin and therefore share localStorage and its `storage` event. That is
the whole trick: the fake Firestore below keeps the room document in
localStorage and pushes snapshots on write, so a write in tab A reaches
tab B the way a Firestore write reaches another phone - asynchronously,
through something outside the page, with a latency this harness can dial
up on purpose. The app's own code is untouched by it; fbDb is simply
pointed at the fake.

  python3 tools/check-vroom.py
  python3 tools/check-vroom.py --against /path/to/old-index.html
  python3 tools/check-vroom.py --latency 400   # a bad connection

Exits non-zero on any failure.
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

from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSET_RE = re.compile(r"env\(safe-area-inset-(top|bottom|left|right)(?:\s*,[^()]*)?\)")

# A Firestore that lives in localStorage. Only the surface the Virtual
# Room actually uses: one document per room, set/get/update/onSnapshot,
# and dotted field paths, which is how ready-up and progress are written.
FAKE_FIRESTORE = """
(() => {
  const KEY = c => "fakefs::" + c;
  const LATENCY = window.__fakeLatency || 60;
  const listeners = [];

  function read(coll, id){
    try {
      const all = JSON.parse(localStorage.getItem(KEY(coll)) || "{}");
      return all[id] || null;
    } catch(e){ return null; }
  }
  function writeAll(coll, all){
    localStorage.setItem(KEY(coll), JSON.stringify(all));
    // Same-tab listeners get no storage event, so they are told directly.
    // Other tabs get the real one, which is the point of the exercise.
    setTimeout(() => notify(coll), 0);
  }
  function write(coll, id, data){
    let all = {};
    try { all = JSON.parse(localStorage.getItem(KEY(coll)) || "{}"); } catch(e){}
    all[id] = data;
    writeAll(coll, all);
  }
  function setDeep(obj, path, value){
    const parts = path.split(".");
    let cur = obj;
    for(let i = 0; i < parts.length - 1; i++){
      if(typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = value;
  }
  function notify(coll){
    listeners.filter(l => l.coll === coll).forEach(l => {
      const data = read(l.coll, l.id);
      l.cb({ exists: !!data, id: l.id, data: () => JSON.parse(JSON.stringify(data || {})) });
    });
  }
  window.addEventListener("storage", e => {
    if(e && e.key && e.key.indexOf("fakefs::") === 0) notify(e.key.slice(8));
  });

  function later(fn){ return new Promise(res => setTimeout(() => res(fn()), LATENCY)); }

  window.__fakeDb = {
    collection(coll){
      return {
        doc(id){
          return {
            set(data){ return later(() => { write(coll, id, JSON.parse(JSON.stringify(data))); }); },
            get(){ return later(() => {
              const d = read(coll, id);
              return { exists: !!d, id: id, data: () => JSON.parse(JSON.stringify(d || {})) };
            }); },
            update(fields){ return later(() => {
              /* Read AND write inside the same tick of this callback, so an
                 update behaves the way Firestore's does: whatever is on
                 disk when it runs is what it appends to. That is what lets
                 the concurrent-chat check below mean something - two sends
                 issued at the same moment resolve one after the other
                 here, and arrayUnion has to survive that. */
              const d = read(coll, id) || {};
              Object.keys(fields).forEach(k => {
                const v = fields[k];
                if(v && typeof v === "object" && v.__arrayUnion){
                  const parts = k.split(".");
                  let cur = d;
                  for(let i = 0; i < parts.length - 1; i++){
                    if(typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {};
                    cur = cur[parts[i]];
                  }
                  const leaf = parts[parts.length - 1];
                  const arr = Array.isArray(cur[leaf]) ? cur[leaf].slice() : [];
                  /* Firestore de-duplicates by deep equality. */
                  const seen = JSON.stringify(v.__arrayUnion);
                  if(!arr.some(x => JSON.stringify(x) === seen)) arr.push(v.__arrayUnion);
                  cur[leaf] = arr;
                } else {
                  setDeep(d, k, v);
                }
              });
              write(coll, id, d);
            }); },
            delete(){ return later(() => {
              let all = {};
              try { all = JSON.parse(localStorage.getItem(KEY(coll)) || "{}"); } catch(e){}
              delete all[id];
              writeAll(coll, all);
            }); },
            onSnapshot(cb, err){
              const l = { coll: coll, id: id, cb: cb };
              listeners.push(l);
              setTimeout(() => {
                const d = read(coll, id);
                cb({ exists: !!d, id: id, data: () => JSON.parse(JSON.stringify(d || {})) });
              }, LATENCY);
              return () => { const i = listeners.indexOf(l); if(i >= 0) listeners.splice(i, 1); };
            }
          };
        }
      };
    }
  };
  /* The app reaches for firebase.firestore.FieldValue.arrayUnion when it
     sends a chat message. The real SDK is blocked in the sandbox, so
     without this the send path throws and the chat checks would fail for
     a reason that has nothing to do with the chat. */
  window.firebase = window.firebase || {};
  window.firebase.firestore = window.firebase.firestore || {};
  window.firebase.firestore.FieldValue = {
    arrayUnion: function(v){ return { __arrayUnion: v }; }
  };
  window.__useFake = function(){ fbDb = window.__fakeDb; };
})();
"""

# One seed for both tabs. Identity is applied PER TAB after boot instead,
# because two tabs in one context share localStorage - so a per-tab seed
# would have the second tab's name overwrite the first's on disk, and the
# two would then share a sync code, which is the participant key. Two real
# devices have two codes; the harness has to arrange that itself.
SEED = ('{"firstName":"Anonymous","avatarChar":"ninja","onboardingComplete":true,'
        '"leaderboardOptIn":true,"lastModified":1700000000000,'
        '"tourRev":99,"seenProfileTour":true,"seenModeSelectTour":true,"seenUnitSelectTour":true,'
        '"lifetime":{"points":1000,"answered":400,"correct":380,"perfectTests":9}}')

FAILURES = []


def check(name, ok, detail=""):
    print("  %-4s %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  -> " + str(detail)) if detail else ""))
    if not ok:
        FAILURES.append(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--against", help="run against a different index.html")
    ap.add_argument("--latency", type=int, default=60,
                    help="simulated one-way write latency, ms")
    args = ap.parse_args()
    src = args.against or os.path.join(ROOT, "index.html")
    body = INSET_RE.sub(lambda m: "0px", io.open(src, encoding="utf-8").read())

    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]; sock.close()

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", port), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/index.html" % port

    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path=CHROME)
        # ONE context, so the two tabs share an origin and therefore share
        # localStorage and its storage event.
        ctx = br.new_context(viewport={"width": 440, "height": 956})
        ctx.add_init_script("window.__fakeLatency = %d;" % args.latency)
        ctx.add_init_script(FAKE_FIRESTORE)

        ctx.add_init_script("try{localStorage.setItem('class26e.freshstart','1');localStorage.setItem('class26e.frame.ok','go-live-1');"
                            "localStorage.setItem('class26e.drill.v1', '%s');}catch(e){}" % SEED)

        def open_tab(name, avatar, points, code, badges=0):
            pg = ctx.new_page()
            pg.route("**/index.html", lambda r: r.fulfill(
                status=200, headers={"content-type": "text/html; charset=utf-8"},
                body=body))
            pg.goto(url)
            pg.wait_for_timeout(2600)
            pg.evaluate("""(a)=>{
              document.getElementById('splashscreen')?.remove();
              __useFake();
              store.firstName = a.name;
              store.avatarChar = a.avatar;
              store.lifetime.points = a.points;
              /* Badges as well as points, because a rank needs both and
                 the lobby shows the rank. Mastering the first N units
                 is the cheapest way to hold a given one. */
              store.unitPerfects = {};
              topicsIn(QUESTIONS).slice(0, a.badges).forEach(u => {
                store.unitPerfects[u] = BADGE_THRESHOLD;
              });
              syncCode = a.code;
            }""", {"name": name, "avatar": avatar, "points": points, "code": code,
                   "badges": badges})
            return pg

        # Different ranks on purpose: Madison clears Silver (level 20,
        # 4 badges) and Devonte only Iron (level 5, 1 badge), so a row
        # showing the wrong emblem cannot pass by showing the same one
        # twice.
        host = open_tab("Madison", "ninja", 14820, "HOST-0001", 4)
        guest = open_tab("Devonte", "ghost", 3100, "GUES-0002", 1)
        # Only one tab can be in front, and a background tab has its rAF
        # throttled - which showed up as the host "starting a second late"
        # when it was simply not being given frames. Two phones are both
        # foreground, so the harness has to say so. This is about the
        # HARNESS being honest, not about the app.
        for pg in (host, guest):
            cdp = ctx.new_cdp_session(pg)
            cdp.send("Page.setWebLifecycleState", {"state": "active"})

        print("\n1. a lobby, and a second device joining it")
        code = host.evaluate("""()=>{
          const units = topicsIn(QUESTIONS).slice(0, 1);
          createVirtualRoomLobby(units, null);
          return null;}""")
        host.wait_for_timeout(900)
        code = host.evaluate("()=>vroomCode")
        check("the host lands in a lobby with a code", bool(code), code)

        guest.evaluate("(c)=>joinVirtualRoomLobby(c)", code)
        guest.wait_for_timeout(1200)
        if os.environ.get("VROOM_DEBUG"):
            print("   guest:", guest.evaluate("""()=>({code:vroomCode, key:vroomMyKey,
              screen:(document.querySelector('#stage .panel')||{}).className,
              rows:document.querySelectorAll('.vroom-row').length,
              doc: JSON.parse(localStorage.getItem('fakefs::vrooms')||'{}')})"""))
            print("   host :", host.evaluate("""()=>({code:vroomCode, key:vroomMyKey,
              rows:document.querySelectorAll('.vroom-row').length})"""))
        rows = host.evaluate("()=>document.querySelectorAll('.vroom-row').length")
        check("the host sees the guest arrive", rows == 2, "%d row(s)" % rows)

        print("\n2. ready-up reaches the other device")
        # The guest readies up; the HOST's screen has to change without
        # anybody touching it. This is the reported bug.
        guest.evaluate("()=>document.querySelector('.vroom-readyup-btn')?.click()")
        host.wait_for_timeout(600)
        seen = host.evaluate("""()=>{
          const rows=[...document.querySelectorAll('.vroom-row')];
          return { ready: rows.filter(r=>r.classList.contains('is-ready')).length,
                   count:(document.querySelector('.vroom-readycount')||{}).textContent||"" };}""")
        check("the host sees the guest's ready without reloading",
              seen["ready"] >= 1, seen)

        print("\n3. the lobby says who you are up against")
        # The small blue level number that used to sit here is gone -
        # that used to sit here is gone - asked for, built, and then
        # asked against. The rank emblem is what stayed.
        ranks = host.evaluate("""()=>[...document.querySelectorAll('.vroom-row')]
          .map(r=>{const m=r.querySelector('.lb-rankmark'); return m ? m.title : null;})""")
        check("every row carries its person's rank",
              sorted(r for r in ranks if r) == ["Iron", "Silver"], ranks)
        check("no level number beside the character",
              host.evaluate("()=>!document.querySelector('.vroom-level')"), "none")

        print("\n4. everybody starts at the same instant")
        host.evaluate("()=>document.querySelector('.vroom-readyup-btn')?.click()")
        # Both devices install a per-frame recorder BEFORE the countdown, so
        # the moment each one uncovers its question is measured rather than
        # polled for. Polling from here cannot resolve the difference this
        # is about: the report was that the host saw the test first.
        for pg in (host, guest):
            pg.evaluate("""()=>{
              window.__revealSeen = null; window.__revealGone = null;
              (function watch(){
                const up = !!document.getElementById('vroom-reveal-overlay');
                if(up && window.__revealSeen === null) window.__revealSeen = Date.now();
                if(!up && window.__revealSeen !== null && window.__revealGone === null){
                  window.__revealGone = Date.now(); return;
                }
                requestAnimationFrame(watch);
              })();
            }""")
        starts = {}
        for label, pg in [("host", host), ("guest", guest)]:
            pg.wait_for_function("() => typeof vroomStartAt === 'number' && vroomStartAt",
                                 timeout=20000)
            starts[label] = pg.evaluate("()=>vroomStartAt")
        check("both devices share one start instant",
              starts["host"] and starts["host"] == starts["guest"], starts)

        # Wait past the shared instant, then compare what each recorded.
        host.wait_for_timeout(1000)
        for pg in (host, guest):
            pg.wait_for_function("() => window.__revealGone !== null", timeout=25000)
        seen = {k: pg.evaluate("()=>({up:window.__revealSeen, gone:window.__revealGone})")
                for k, pg in [("host", host), ("guest", guest)]}
        check("the question was covered on both while the countdown ran",
              all(v["up"] for v in seen.values()), seen)
        # EARLY is the bug. The report was the host seeing the test first
        # while everybody else was still loading, and the fix for it is
        # that every device computes the same instant from the same
        # shared startAt - so the assertion is that nobody uncovers
        # before it, not that the two land on the same millisecond.
        #
        # Late is measured too, but only on the tab that is in front.
        # Chromium throttles requestAnimationFrame in a background tab
        # and the app's own countdown runs on rAF, so a backgrounded tab
        # genuinely does hold its overlay a beat longer - an artefact of
        # two tabs in one browser, not of two phones. Asserting a tight
        # skew across both would be asserting something the harness
        # cannot honestly measure.
        early = {k: starts["host"] - v["gone"] for k, v in seen.items()}
        check("neither device uncovers the question early",
              all(v <= 50 for v in early.values()),
              {k: "%dms early" % v for k, v in early.items()})
        front = seen["guest"]["gone"] - starts["host"]
        check("the foreground device uncovers on the shared instant",
              -50 <= front <= 250, "%dms after startAt" % front)

        # ---- 5. the chat cannot lose a message -----------------------
        # The bug this is written against: send() used to .get() the whole
        # document, push onto the array it found, and .update() the result.
        # Two people typing at once each read the array BEFORE the other's
        # message existed, so whoever wrote second erased the first. In a
        # lobby whose whole purpose is agreeing on units, that is the one
        # failure that matters.
        print("\n5. two people typing at once")
        for pg in (host, guest):
            pg.evaluate("()=>{ if(window.__chatKill) window.__chatKill(); "
                        "const box=document.createElement('div');"
                        "box.id='chatprobe';document.body.appendChild(box);"
                        "window.__chatKill = buildVroomChatPanel(box); }")
        host.wait_for_timeout(400)
        # Fired without awaiting each other, which is the whole point.
        host.evaluate("()=>{ const i=document.querySelector('#chatprobe .vroom-chat-input');"
                      "i.value='from the host'; "
                      "document.querySelector('#chatprobe .vroom-chat-send').click(); }")
        guest.evaluate("()=>{ const i=document.querySelector('#chatprobe .vroom-chat-input');"
                       "i.value='from the guest'; "
                       "document.querySelector('#chatprobe .vroom-chat-send').click(); }")
        host.wait_for_timeout(1200 + args.latency * 4)
        texts = host.evaluate("()=>[...document.querySelectorAll('#chatprobe .vroom-chat-msg')]"
                              ".map(e=>e.textContent)")
        joined = " | ".join(texts)
        check("both messages survive a simultaneous send",
              ("from the host" in joined) and ("from the guest" in joined), joined)
        seen_on_guest = guest.evaluate(
            "()=>[...document.querySelectorAll('#chatprobe .vroom-chat-msg')]"
            ".map(e=>e.textContent).join(' | ')")
        check("and both reach the other device",
              ("from the host" in seen_on_guest) and ("from the guest" in seen_on_guest),
              seen_on_guest)

        # ---- 6. two lobbies at once ----------------------------------
        # Each lobby is its own document keyed by its join code, so they
        # should never see each other - but "should" is not a check, and
        # ~40 classmates can easily have two rooms open at the same time.
        print("\n6. two lobbies at the same time")
        second = open_tab("Rosa", "queen", 4000, "CCCC-3333", badges=2)
        second.evaluate("()=>{ vroomCode='ZZZZ-9999'; vroomMyKey='CCCC-3333';"
                        " vroomIsHost=true;"
                        " fbDb.collection('vrooms').doc('ZZZZ-9999')"
                        "   .set({ host:'CCCC-3333', participants:{}, chatMessages:[] }); }")
        second.wait_for_timeout(300 + args.latency * 2)
        second.evaluate("()=>{ const box=document.createElement('div');"
                        "box.id='chatprobe';document.body.appendChild(box);"
                        "window.__chatKill = buildVroomChatPanel(box); }")
        second.wait_for_timeout(300 + args.latency * 2)
        second.evaluate("()=>{ const i=document.querySelector('#chatprobe .vroom-chat-input');"
                        "i.value='other room only'; "
                        "document.querySelector('#chatprobe .vroom-chat-send').click(); }")
        second.wait_for_timeout(800 + args.latency * 4)
        bleed = host.evaluate("()=>[...document.querySelectorAll('#chatprobe .vroom-chat-msg')]"
                              ".map(e=>e.textContent).join(' | ')")
        check("the second lobby's chat does not reach the first",
              "other room only" not in bleed, bleed)
        own = second.evaluate("()=>[...document.querySelectorAll('#chatprobe .vroom-chat-msg')]"
                              ".map(e=>e.textContent).join(' | ')")
        check("and the second lobby sees only its own",
              ("other room only" in own) and ("from the host" not in own), own)
        codes = host.evaluate("()=>vroomCode") , second.evaluate("()=>vroomCode")
        check("the two lobbies are two different documents",
              codes[0] != codes[1], codes)

        # ---- 7. the results screen -----------------------------------
        # THE ONE SCREEN WITH NO OTHER COVERAGE. It needs run state, so it
        # cannot be mounted cold and is therefore not in sweep-layout's
        # SCREENS - which is exactly why five separate things were wrong
        # on it at once: the tab bar was showing inside a test, the race
        # line stayed up with the results out, the two exits were
        # different sizes with an arrow on one, "Review your answers"
        # opened an empty box on a clean run, and there was no sign of
        # the XP the run had earned.
        #
        # Driven here rather than mounted: both tabs finish for real, so
        # the screen is reached the way a person reaches it.
        print("\n7. the results screen, reached by finishing")
        for pg in (host, guest):
            pg.evaluate("""()=>{
              /* EVERY ANSWER RIGHT, on purpose. The bug in "Review your
                 answers" was only ever on the clean-run path: the list
                 was built when something had been missed, so the one
                 case where the button said "all correct" was the case
                 where it expanded nothing. A run with misses in it takes
                 the other branch and cannot see that at all. */
              order.forEach(qi => {
                const oo = optionOrder(qi);
                picked[qi] = oo.indexOf(QUESTIONS[qi].answer);
              });
              /* A real finish writes the score and hands over to the
                 finale, which hands over to the results screen. */
              summarize();
            }""")
        host.wait_for_timeout(600)
        # Both are finished as far as the room document is concerned, so
        # the results screen can be asked for directly - what is under
        # test is the screen, not the route to it.
        for pg in (host, guest):
            pg.evaluate("()=>{ showVirtualRoomResults(); }")
        host.wait_for_timeout(900 + args.latency * 4)

        # THE RACE LINE, on the path that was actually broken. Hiding it
        # on the FIRST render always worked; what did not was every
        # render after it, because the hide sat past an early return that
        # fires once the standings are up. So: put the bar back, poke the
        # room document to force another snapshot, and see whether the
        # screen takes it down again.
        host.evaluate("()=>{ document.getElementById('vroomracebar').hidden = false; }")
        host.evaluate("()=>{ fbDb.collection('vrooms').doc(vroomCode)"
                      "  .update({ nudge: Date.now() }); }")
        host.wait_for_timeout(700 + args.latency * 4)
        race_again = host.evaluate("()=>document.getElementById('vroomracebar').hidden")

        got = host.evaluate("""()=>{
          const R = e => e ? e.getBoundingClientRect() : null;
          const btns = [...document.querySelectorAll('.vroom-exit-row .vroom-exit-btn')];
          const bar = document.querySelector('.bottomtabs');
          const race = document.getElementById('vroomracebar');
          const lvl = document.querySelector('.results-level');
          const toggle = [...document.querySelectorAll('button')]
            .find(b => /Review your answers/.test(b.textContent));
          if(toggle) toggle.click();
          const list = toggle ? toggle.nextElementSibling : null;
          const chat = document.querySelector('.vroom-chat-toggle');
          const panel = document.querySelector('#stage .panel');
          return {
            exits: btns.map(b => Math.round(R(b).width)),
            exitLabels: btns.map(b => b.textContent),
            arrow: btns.some(b => b.classList.contains('back-link')),
            tabbar: !bar || bar.hidden,
            forced: !!window.forceHideBottomTabs,
            raceHidden: !race || race.hidden,
            levelBlock: !!lvl,
            levelGain: lvl ? (lvl.querySelector('.results-level-gain') || {}).textContent : null,
            reviewItems: list ? list.querySelectorAll('li').length : -1,
            chatCorner: chat ? (R(chat).right > R(panel).right - 4) : null
          };}""")
        check("no bottom tab bar on the results screen",
              got["tabbar"] and got["forced"], {k: got[k] for k in ("tabbar", "forced")})
        check("the race line is down once the results are out",
              got["raceHidden"], got["raceHidden"])
        check("and stays down on every snapshot after, not just the first",
              race_again, race_again)
        check("both exits are the same width",
              len(got["exits"]) == 2 and got["exits"][0] == got["exits"][1], got["exits"])
        check("and neither is a back link, so neither carries an arrow",
              not got["arrow"] and "Back to Home" in got["exitLabels"], got["exitLabels"])
        check("the XP and level block is on the screen",
              got["levelBlock"], got["levelGain"])
        # -1 means the toggle was not found at all; 0 means it was found
        # and opened nothing, which is the bug this is written against.
        check("Review your answers opens a real list, even on a clean run",
              got["reviewItems"] > 0, got["reviewItems"])
        if got["chatCorner"] is not None:
            check("the chat button is in the top right", got["chatCorner"], got["chatCorner"])

        ctx.close()
        br.close()
    srv.shutdown()
    print("\n%s  (%d failure(s))"
          % ("ALL PASS" if not FAILURES else "FAILED: " + ", ".join(FAILURES),
             len(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
