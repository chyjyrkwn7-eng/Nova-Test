#!/usr/bin/env python3
"""Account integrity: the sync code, recovery, and who Find me blames.

The sweep asks "is anything broken on this device", check-positions asks
"did it land where I meant it to", check-fixes asks "is this fix in effect
here". None of them can see the one class of bug that costs somebody their
account rather than their layout: a sync code that goes missing, a
recovery that restores the progress and then leaves the Welcome screen up
to overwrite it, a rankings row nobody can ever delete. Every check here
is a measurement of behaviour, not a code read, and every one of them was
written against a build where it FAILED - run it with --against on that
build to see it fail, which is the only thing that makes a green run mean
anything.

  python3 tools/check-sync.py
  python3 tools/check-sync.py --against /path/to/old-index.html

Chromium has no Firestore here (the CDN is blocked in the sandbox), so
fbDb is stubbed - see HOOK. Exits non-zero on any failure.
"""
import functools, http.server, io, os, re, socket, sys, threading
from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSET_RE = re.compile(r"env\(safe-area-inset-(top|bottom|left|right)(?:\s*,[^()]*)?\)")

SRC = sys.argv[sys.argv.index("--against") + 1] if "--against" in sys.argv \
    else os.path.join(ROOT, "index.html")

# A Firestore stand-in. The real CDN is blocked in the sandbox, so fbDb is
# null and every cloud path is dead; these checks are about those paths, so
# the stub is the only way to exercise them at all. It records deletes,
# which is how "the old rankings row is retired" is measured.
HOOK = '''
  window.__deleted = [];
  window.__entries = [];
  window.__fake = function(entries){
    window.__entries = entries || [];
    fbDb = { collection: function(name){ return { doc: function(id){ return {
      set: function(){ return Promise.resolve(); },
      get: function(){ return Promise.resolve({ exists: false }); },
      delete: function(){ window.__deleted.push(name + "/" + id); return Promise.resolve(); }
    }; } }; } };
    onSnapshotResilient = function(ref, onNext){
      setTimeout(function(){ onNext({ forEach: function(f){
        window.__entries.forEach(function(e){ f({ id: e.id, data: function(){ return e; } }); });
      } }); }, 20);
      return function(){};
    };
  };
'''

BODY = INSET_RE.sub(lambda m: "0px", io.open(SRC, encoding="utf-8").read()) \
    .replace("let fbDb = null;", "let fbDb = null;" + HOOK, 1)

STORE = ("{\"firstName\":\"Madison\",\"avatarChar\":\"ninja\",\"onboardingComplete\":true,"
         "\"leaderboardOptIn\":true,\"lastModified\":1700000000000,"
         "\"lifetime\":{\"points\":420,\"correct\":88,\"perfectTests\":2}}")

so = socket.socket(); so.bind(("127.0.0.1", 0)); PORT = so.getsockname()[1]; so.close()
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), functools.partial(Q, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/index.html" % PORT

fails = []
def check(name, ok, detail=""):
    print("  %-4s %s%s" % ("PASS" if ok else "FAIL", name, ("  -> " + detail) if detail else ""))
    if not ok: fails.append(name)

def page(ctx):
    pg = ctx.new_page()
    pg.route("**/index.html", lambda r: r.fulfill(
        status=200, headers={"content-type": "text/html; charset=utf-8"}, body=BODY))
    return pg

with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path=CHROME)

    # ---- 1. onboarded, no sync code: boot issues one ----
    print("\n1. onboarded account whose sync code went missing")
    ctx = br.new_context(viewport={"width": 834, "height": 1194})
    ctx.add_init_script("try{localStorage.setItem('class26e.drill.v1', '%s');}catch(e){}" % STORE)
    pg = page(ctx); pg.goto(URL); pg.wait_for_timeout(2600)
    got = pg.evaluate("()=>({code:syncCode, ls:localStorage.getItem('class26e.synccode')})")
    check("a code is issued at boot", bool(got["code"]) and got["ls"] == got["code"], str(got))
    pg.evaluate("()=>{document.getElementById('splashscreen')?.remove(); __fake([]);}")
    pg.evaluate("()=>showRankings('level')"); pg.wait_for_timeout(400)
    pg.evaluate("()=>document.querySelector('.rank-me-btn').click()"); pg.wait_for_timeout(300)
    res = pg.evaluate("""()=>({me:!!document.querySelector('[data-me="1"]'),
        flash:!!document.querySelector('.rank-flash'),
        msg:(document.querySelector('.daily-alert')||{}).textContent||null})""")
    check("Find me finds your row", res["me"] and res["flash"], str(res))
    ctx.close()

    # ---- 2. sync deliberately off: no code, and the message says so ----
    print("\n2. sync turned off on purpose")
    ctx = br.new_context(viewport={"width": 834, "height": 1194})
    ctx.add_init_script("try{localStorage.setItem('class26e.drill.v1', '%s');"
                        "localStorage.setItem('class26e.syncoff','1');}catch(e){}" % STORE)
    pg = page(ctx); pg.goto(URL); pg.wait_for_timeout(2600)
    pg.evaluate("()=>{document.getElementById('splashscreen')?.remove(); __fake([]);}")
    pg.evaluate("()=>showRankings('level')"); pg.wait_for_timeout(400)
    pg.evaluate("()=>document.querySelector('.rank-me-btn').click()"); pg.wait_for_timeout(300)
    res = pg.evaluate("""()=>({code:syncCode,
        msg:(document.querySelector('.daily-alert')||{}).textContent||''})""")
    check("no code is forced on a device that opted out", not res["code"], str(res["code"]))
    check("Find me blames sync, not the rankings setting",
          "isn’t syncing" in res["msg"], repr(res["msg"]))
    ctx.close()

    # ---- 3. hidden from the rankings: the other message ----
    print("\n3. hidden from the rankings")
    hidden = STORE.replace('"leaderboardOptIn":true', '"leaderboardOptIn":false')
    ctx = br.new_context(viewport={"width": 834, "height": 1194})
    ctx.add_init_script("try{localStorage.setItem('class26e.drill.v1', '%s');"
                        "localStorage.setItem('class26e.synccode','WXYZ-7777');}catch(e){}" % hidden)
    pg = page(ctx); pg.goto(URL); pg.wait_for_timeout(2600)
    pg.evaluate("()=>{document.getElementById('splashscreen')?.remove(); __fake([]);}")
    pg.evaluate("()=>showRankings('level')"); pg.wait_for_timeout(400)
    pg.evaluate("()=>document.querySelector('.rank-me-btn').click()"); pg.wait_for_timeout(300)
    msg = pg.evaluate("()=>(document.querySelector('.daily-alert')||{}).textContent||''")
    check("Find me names the Settings toggle", "Show me in the rankings" in msg, repr(msg))
    ctx.close()

    # ---- 4. localStorage evicted: recovery must land on Home, with the code ----
    print("\n4. localStorage lost, IndexedDB mirror intact")
    ctx = br.new_context(viewport={"width": 834, "height": 1194})
    pg = page(ctx)
    pg.add_init_script("try{localStorage.setItem('class26e.drill.v1', '%s');"
                       "localStorage.setItem('class26e.synccode','WXYZ-7777');}catch(e){}" % STORE)
    pg.goto(URL); pg.wait_for_timeout(2600)
    pg.evaluate("()=>{document.getElementById('splashscreen')?.remove(); saveStore();}")
    pg.wait_for_timeout(600)
    mirrored = pg.evaluate("()=>idbLoadCode? idbLoadCode() : null") \
        if pg.evaluate("()=>typeof idbLoadCode==='function'") else None
    check("the code is mirrored into IndexedDB", mirrored == "WXYZ-7777", repr(mirrored))
    pg.close()

    pg2 = page(ctx)   # same context: IndexedDB survives, localStorage does not
    pg2.add_init_script("try{localStorage.clear();}catch(e){}")
    pg2.goto(URL); pg2.wait_for_timeout(3200)
    pg2.evaluate("()=>document.getElementById('splashscreen')?.remove()")
    pg2.wait_for_timeout(900)
    res = pg2.evaluate("""()=>({screen:(document.querySelector('#stage [data-screen]')||{dataset:{}}).dataset.screen||null,
        name:store.firstName, points:(store.lifetime||{}).points,
        code:syncCode, ls:localStorage.getItem('class26e.synccode')})""")
    check("recovery lands on Home, not Welcome", res["screen"] == "home", str(res))
    check("recovery restores the progress", res["points"] == 420 and res["name"] == "Madison", str(res))
    check("recovery restores the sync code", res["code"] == "WXYZ-7777"
          and res["ls"] == "WXYZ-7777", str(res))
    ctx.close()

    # ---- 5. swapping codes retires the old rankings row ----
    print("\n5. abandoning a code takes its rankings row with it")
    ctx = br.new_context(viewport={"width": 834, "height": 1194})
    ctx.add_init_script("try{localStorage.setItem('class26e.drill.v1', '%s');"
                        "localStorage.setItem('class26e.synccode','AAAA-1111');}catch(e){}" % STORE)
    pg = page(ctx); pg.goto(URL); pg.wait_for_timeout(2600)
    pg.evaluate("()=>{document.getElementById('splashscreen')?.remove(); __fake([]);}")
    pg.evaluate("()=>{ __deleted.length = 0; setSyncCode('BBBB-2222'); }")
    pg.wait_for_timeout(200)
    dele = pg.evaluate("()=>__deleted.slice()")
    check("linking to another code deletes the old row",
          "leaderboard/AAAA-1111" in dele, str(dele))
    check("linking does NOT delete the old progress doc",
          not any(d.startswith("progress/") for d in dele), str(dele))
    pg.evaluate("()=>{ __deleted.length = 0; retireLeaderboardEntry(syncCode); clearSyncCode(true); }")
    pg.wait_for_timeout(200)
    res = pg.evaluate("()=>({del:__deleted.slice(), off:localStorage.getItem('class26e.syncoff')})")
    check("stopping sync deletes the row and records the opt-out",
          "leaderboard/BBBB-2222" in res["del"] and res["off"] == "1", str(res))
    ctx.close()
    br.close()

srv.shutdown()
print("\n%s  (%d failure(s))" % ("ALL PASS" if not fails else "FAILED: " + ", ".join(fails), len(fails)))
sys.exit(1 if fails else 0)
