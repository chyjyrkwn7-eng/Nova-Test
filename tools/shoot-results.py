"""The two screens the walk cannot reach, because both need run state."""
import re, os, io, http.server, threading, functools, socket, sys
from playwright.sync_api import sync_playwright
ROOT="/home/user/Nova-Test"; CHROME="/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
OUT=sys.argv[1]
INSET=re.compile(r"env\(safe-area-inset-(top|right|bottom|left)(?:,\s*[^)]*)?\)")
os.makedirs(OUT, exist_ok=True)
SEED=('{"firstName":"Madison","avatarChar":"ninja","onboardingComplete":true,'
      '"leaderboardOptIn":true,"lastModified":1700000000000,"tourRev":99,'
      '"seenProfileTour":true,"seenModeSelectTour":true,"seenUnitSelectTour":true,'
      '"seenMainMenuTour":true,"seenFirstResultsTour":true,'
      '"unitPerfects":{"Professionalism and Ethics":35,"Professional Policing":35},'
      '"lifetime":{"points":12250,"answered":5400,"correct":4980,"perfectTests":141}}')
STATUS = """
(() => { window.addEventListener('DOMContentLoaded', () => {
  const b=document.createElement('div');
  b.style.cssText='position:fixed;top:0;left:0;right:0;height:__H__px;z-index:99999;'
    +'display:flex;align-items:center;justify-content:space-between;'
    +'padding:0 22px;font:700 17px -apple-system,system-ui,sans-serif;color:#fff;'
    +'pointer-events:none;';
  b.innerHTML='<span>9:41</span><span style="display:inline-block;width:26px;height:13px;'
    +'border:1.6px solid #fff;border-radius:3px;"></span>';
  document.body.appendChild(b); }); })();
"""
src=io.open(os.path.join(ROOT,"index.html"),encoding="utf-8").read()
sk=socket.socket(); sk.bind(("127.0.0.1",0)); port=sk.getsockname()[1]; sk.close()
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
srv=http.server.ThreadingHTTPServer(("127.0.0.1",port), functools.partial(Q,directory=ROOT))
threading.Thread(target=srv.serve_forever,daemon=True).start()

FAKE_ROOM = """
(() => {
  const room = { host:'MADI-0001', status:'started', units:['Penal Code'],
    startAt: Date.now()-60000, chatMessages:[],
    participants:{
      'MADI-0001':{name:'Madison',avatarChar:'ninja',level:23,badges:4,mystery:0,
        joinedAt:1,ready:true,finished:true,score:96,elapsedMs:214000,totalScore:9386,progress:100},
      'DEVO-0002':{name:'Devonte',avatarChar:'ghost',level:31,badges:6,mystery:0,
        joinedAt:2,ready:true,finished:true,score:92,elapsedMs:238000,totalScore:8962,progress:100},
      'ALEX-0003':{name:'Alex',avatarChar:'grizzly',level:47,badges:9,mystery:0,
        joinedAt:3,ready:true,finished:true,score:88,elapsedMs:201000,totalScore:8599,progress:100},
      'KIMB-0004':{name:'Kim',avatarChar:'alien',level:12,badges:2,mystery:0,
        joinedAt:4,ready:true,finished:true,score:84,elapsedMs:262000,totalScore:8138,progress:100}}};
  window.__room = room;
  window.__useFakeRoom = () => {
    const snap = () => ({ exists:true, data:()=>JSON.parse(JSON.stringify(window.__room)),
                          metadata:{fromCache:false} });
    const doc = () => ({
      get: () => Promise.resolve(snap()),
      set: () => Promise.resolve(),
      update: (f) => { Object.keys(f).forEach(k => {
          const parts=k.split('.'); let o=window.__room;
          for(let i=0;i<parts.length-1;i++){ o[parts[i]] = o[parts[i]] || {}; o=o[parts[i]]; }
          o[parts[parts.length-1]] = f[k]; });
        (window.__subs||[]).forEach(cb => cb(snap())); return Promise.resolve(); },
      onSnapshot: (cb) => { window.__subs=(window.__subs||[]); window.__subs.push(cb);
        setTimeout(()=>cb(snap()),30); return ()=>{}; }
    });
    /* A plain assignment, not window.fbDb. fbDb is a top-level `let`, so
       it lives in the global LEXICAL environment rather than on window -
       writing window.fbDb leaves the real binding null and the app
       throws on its first .collection(). check-vroom's __useFake does
       the same thing for the same reason. */
    fbDb = { collection: () => ({ doc: doc, get: () => Promise.resolve({docs:[]}) }) };
    window.firebase = window.firebase || {};
    window.firebase.firestore = window.firebase.firestore || {};
    window.firebase.firestore.FieldValue = { arrayUnion: (...a) => ({ __au:a }) };
  };
})();
"""
DEV=[("iphone-17-pro-max",440,956,62),("ipad-pro-11",834,1194,24)]
with sync_playwright() as pw:
    br=pw.chromium.launch(executable_path=CHROME)
    for label,w,h,top in DEV:
        v={"top":f"{top}px","right":"0px","bottom":"34px" if top>40 else "20px","left":"0px"}
        bd=INSET.sub(lambda m: v[m.group(1)], src)
        ctx=br.new_context(viewport={"width":w,"height":h},device_scale_factor=2)
        ctx.add_init_script("Object.defineProperty(navigator,'standalone',{get:()=>true});")
        ctx.add_init_script(FAKE_ROOM)
        ctx.add_init_script(STATUS.replace("__H__",str(top)))
        ctx.add_init_script("try{localStorage.setItem('class26e.freshstart','1');"
                            "localStorage.setItem('class26e.frame.ok','go-live-1');"
                            "localStorage.setItem('class26e.daily.seen','x');"
                            "localStorage.setItem('class26e.drill.v1','%s');}catch(e){}"%SEED)
        pg=ctx.new_page()
        pg.route("**/index.html", lambda route,request,b=bd: route.fulfill(
            status=200,headers={"content-type":"text/html; charset=utf-8"},body=b))
        pg.goto(f"http://127.0.0.1:{port}/index.html"); pg.wait_for_timeout(1500)
        pg.evaluate("()=>{document.getElementById('splashscreen')?.remove();}")

        # ---- an ordinary drill result, run for real ----
        pg.evaluate("""()=>{
          cfg.units=['Penal Code']; cfg.mode='drill'; cfg.size=10; cfg.source='all';
          const idx=[]; QUESTIONS.forEach((q,i)=>{ if(q.topic==='Penal Code' && idx.length<10) idx.push(i); });
          beginRun(idx);
        }""")
        pg.wait_for_timeout(3600)
        for _ in range(12):
            done = pg.evaluate("""()=>{
              const c=document.querySelector('.choice');
              if(!c) return true;
              const qi=order[pos];
              const oo=optionOrder(qi);
              const want=oo.indexOf(QUESTIONS[qi].answer);
              const all=[...document.querySelectorAll('.choice')];
              if(all[want]) all[want].click();
              return false;}""")
            if done: break
            pg.wait_for_timeout(700)
        pg.wait_for_timeout(1800)
        pg.evaluate("()=>{ if(typeof summarize==='function' && document.querySelector('.choice')) summarize(); }")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=f"{OUT}/{label}-50.0-drill-results.png")
        pg.evaluate("()=>window.scrollTo({top:document.documentElement.scrollHeight,behavior:'instant'})")
        pg.wait_for_timeout(500)
        pg.screenshot(path=f"{OUT}/{label}-50.5-drill-results-scrolled.png")

        # ---- the Virtual Room results ----
        pg.evaluate("""()=>{
          __useFakeRoom();
          vroomCode='TEST-ROOM'; vroomMyKey='MADI-0001'; vroomIsHost=true;
          inVirtualRoom=false;
          order.forEach(qi=>{ picked[qi]=optionOrder(qi).indexOf(QUESTIONS[qi].answer); });
          showVirtualRoomResults();
        }""")
        pg.wait_for_timeout(2200)
        pg.screenshot(path=f"{OUT}/{label}-51.0-vroom-results.png")
        pg.evaluate("()=>window.scrollTo({top:document.documentElement.scrollHeight,behavior:'instant'})")
        pg.wait_for_timeout(500)
        pg.screenshot(path=f"{OUT}/{label}-51.5-vroom-results-scrolled.png")

        # ---- the race line, four people spread out, two of them level ----
        pg.evaluate("""()=>{
          window.__room.participants['MADI-0001'].finished=false;
          window.__room.participants['MADI-0001'].progress=62;
          window.__room.participants['DEVO-0002'].finished=false;
          window.__room.participants['DEVO-0002'].progress=64;
          window.__room.participants['ALEX-0003'].finished=false;
          window.__room.participants['ALEX-0003'].progress=63;
          window.__room.participants['KIMB-0004'].finished=false;
          window.__room.participants['KIMB-0004'].progress=24;
          inVirtualRoom=true;
          document.getElementById('vroomracebar').hidden=false;
          startVroomRaceListener();
        }""")
        pg.wait_for_timeout(1400)
        pg.evaluate("()=>window.scrollTo({top:0,behavior:'instant'})")
        pg.wait_for_timeout(300)
        pg.screenshot(path=f"{OUT}/{label}-52.0-race-line-crowded.png",
                      clip={"x":0,"y":0,"width":w,"height":min(h, top+170)})
        print(label, "done")
        ctx.close()
    br.close()
srv.shutdown()
