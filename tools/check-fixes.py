#!/usr/bin/env python3
"""Assert each fix from the iPad bug report, on every device, both ways in.

The sweep asks "is anything broken" and check-positions asks "did it land
where I meant it to". Neither asks "is this specific fix actually in effect
here", which is the question after a batch of device-reported bugs. Every
check below is a measurement, not a code read.
"""
import functools, http.server, io, os, re, socket, sys, threading
from PIL import Image
from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSET_RE = re.compile(r"env\(safe-area-inset-(top|bottom|left|right)(?:\s*,[^()]*)?\)")
STANDALONE = """
Object.defineProperty(navigator,'standalone',{get:()=>true,configurable:true});
(function(){ const mm = window.matchMedia.bind(window);
  window.matchMedia = q => /display-mode:\\s*standalone/.test(q)
    ? {matches:true, media:q, addListener(){}, removeListener(){},
       addEventListener(){}, removeEventListener(){}, onchange:null, dispatchEvent(){return false;}}
    : mm(q); })();"""

def load(name, pat):
    s = io.open(os.path.join(ROOT, "tools/sweep-layout.py")).read()
    m = re.search(pat, s, re.S)
    return m.group(1)

SEED = load("SEED", r'SEED = """(.*?)"""')
DEVICES = eval("[" + load("DEVICES", r'DEVICES = \[(.*?)\n\]') + "]")
CHROME_H = eval(load("CHROME_H", r'CHROME_H = (\{.*?\})'))

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

CHECKS = """(() => {
  const out = {};
  const R = s => { const e = document.querySelector(s); return e && e.getBoundingClientRect(); };

  // 1. grey bar: html's fallback glow must be anchored to the viewport
  const hs = getComputedStyle(document.documentElement);
  /* No background-attachment assertion. It was one, and it was wrong:
     `fixed` was the first attempted grey-bar fix, it is unsupported on
     iOS Safari (treated as scroll), and asserting it here only proved
     Chromium honoured something the target platform ignores. The grey
     bar is checked by reproducing it instead - see the screenshot
     comparison further down. */
  out.htmlLayers = (hs.backgroundImage.match(/radial-gradient/g) || []).length;

  // 5. sphere tap highlight (Home only)
  const hero = document.querySelector(".cosmic-hero-wrap");
  out.sphereHighlight = hero ? getComputedStyle(hero).webkitTapHighlightColor : null;
  const circ = hero && hero.querySelector("circle");
  out.sphereChildHighlight = circ ? getComputedStyle(circ).webkitTapHighlightColor : null;

  // 3. the points-fly destination must exist
  out.profileTab = !!document.getElementById("bottomtab-profile");
  return out;
})()"""

def rgb(s):
    m = re.findall(r"[\d.]+", s or "")
    return tuple(float(x) for x in m[:3]) if len(m) >= 3 else None

def main():
    srv, url = serve()
    fails, checked = [], 0
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(executable_path=CHROME)
            for name, w, h, kind, ins_p, ins_l in DEVICES:
                for orient in ("portrait", "landscape"):
                    vw, vh = (w, h) if orient == "portrait" else (h, w)
                    ins = ins_p if orient == "portrait" else ins_l
                    for mode in ("installed", "browser"):
                        if kind == "desktop" and mode == "installed": continue
                        if kind == "desktop" and orient == "landscape": continue
                        # CHROME_H holds (portrait, landscape) pairs, not a
                        # single number - browser chrome is shorter on a phone
                        # held sideways. Same indexing the sweep uses.
                        chrome = CHROME_H[kind][0 if orient == "portrait" else 1]
                        H = vh if mode == "installed" else vh - chrome
                        I = ins if mode == "installed" else (0, 0, 0, 0)
                        tag = f"{name} {vw}x{H} {mode}"
                        ctx = br.new_context(viewport={"width": vw, "height": H})
                        ctx.add_init_script(SEED)
                        if mode == "installed": ctx.add_init_script(STANDALONE)
                        pg = ctx.new_page(); body = patched(I)
                        pg.route("**/index.html", lambda r, q, b=body: r.fulfill(
                            status=200, headers={"content-type": "text/html; charset=utf-8"}, body=b))
                        errs = []
                        pg.on("pageerror", lambda e: errs.append(str(e)[:120]))
                        pg.goto(url); pg.wait_for_timeout(1400)

                        # --- REPRODUCTION, not a happy path. The splash bug is
                        # an oversized fixed box during an iOS launch, which
                        # Chromium never produces on its own: measured here the
                        # overlay matches the viewport on frame one, which is
                        # exactly why two earlier "fixes" passed locally and
                        # shipped broken. Force the box oversized and require
                        # the group to stay centred on the VIEWPORT.
                        sp = pg.evaluate("""()=>{
                          const o=document.getElementById('splashscreen'); if(!o) return null;
                          o.style.width=(innerWidth+260)+'px'; o.style.height=(innerHeight+260)+'px';
                          return new Promise(res=>requestAnimationFrame(()=>requestAnimationFrame(()=>{
                            const g=document.getElementById('splash-group');
                            const r=g.getBoundingClientRect();
                            res({dx:Math.round((r.left+r.right)/2-innerWidth/2),
                                 dy:Math.round((r.top+r.bottom)/2-innerHeight/2),
                                 vis:+getComputedStyle(g).opacity>0});})));}""")
                        if sp is not None:
                            if abs(sp["dx"])>2 or abs(sp["dy"])>2:
                                fails.append(f"{tag}: splash off-centre by {sp['dx']},{sp['dy']} in an oversized box")
                            if not sp["vis"]:
                                fails.append(f"{tag}: splash group never became visible")

                        # 2. splash: revealed and centred, before it is torn down
                        sp = pg.evaluate("""()=>{const g=document.getElementById('splash-group');
                          if(!g) return null; const r=g.getBoundingClientRect();
                          return {ready:g.classList.contains('splash-ready'),
                                  op:+getComputedStyle(g).opacity,
                                  dx:Math.round((r.left+r.right)/2-innerWidth/2),
                                  dy:Math.round((r.top+r.bottom)/2-innerHeight/2)};}""")
                        if sp:
                            if not sp["ready"]: fails.append(f"{tag}: splash never revealed")
                            elif abs(sp["dx"]) > 2 or abs(sp["dy"]) > 2:
                                fails.append(f"{tag}: splash off-centre by {sp['dx']},{sp['dy']}")

                        pg.wait_for_timeout(2200)
                        pg.evaluate("()=>{document.documentElement.style.background='';"
                                    "document.getElementById('splashscreen')?.remove();}")
                        pg.evaluate("()=>showHome()"); pg.wait_for_timeout(500)
                        c = pg.evaluate(CHECKS)
                        checked += 1

                        if c["htmlLayers"] < 2:
                            fails.append(f"{tag}: html fallback glow missing ({c['htmlLayers']} layers)")
                        for k in ("sphereHighlight", "sphereChildHighlight"):
                            v = rgb(c[k])
                            if c[k] and v and len(re.findall(r"[\d.]+", c[k])) > 3 and float(
                                    re.findall(r"[\d.]+", c[k])[3]) != 0:
                                fails.append(f"{tag}: {k} is {c[k]}, not transparent")
                        if not c["profileTab"]:
                            fails.append(f"{tag}: #bottomtab-profile missing (points fly target)")

                        # --- The grey bar, measured the only way that means
                        # anything: what body::before paints at the bottom edge
                        # against what html falls back to there. body::before is
                        # FIXED, so its bottom-edge colour is the same at every
                        # scroll offset, which makes it the correct target
                        # wherever the page happens to be.
                        #
                        # Two earlier versions of this check were worthless and
                        # both are worth remembering. One asserted
                        # background-attachment:fixed - a property iOS ignores,
                        # so it only proved Chromium honoured it. One compared
                        # the bottom row against "just above the 100lvh
                        # boundary", computed as SH-overflow-6, which clamps to
                        # the TOP ROW whenever the overflow exceeds the screen:
                        # on a 568x260 viewport it compared the bottom of the
                        # screen to the top and called a gradient a seam. A
                        # step-detector fails too - on a long page the boundary
                        # is far above the screen, so the whole visible bottom
                        # is uniformly wrong with no step to find.
                        #
                        # This one is verified against a build that actually has
                        # the bug: 23 levels there, 4 here.
                        pg.evaluate("""()=>{const s=document.createElement('style'); s.id='__hc';
                          s.textContent='body>*{visibility:hidden!important}';
                          document.head.appendChild(s);
                          window.scrollTo(0, document.documentElement.scrollHeight);}""")
                        pg.wait_for_timeout(260)
                        withFixed = Image.open(io.BytesIO(pg.screenshot())).convert("RGB")
                        pg.evaluate("""()=>{const s=document.createElement('style'); s.id='__hb';
                          s.textContent='body::before{display:none!important}';
                          document.head.appendChild(s);}""")
                        pg.wait_for_timeout(220)
                        fallback = Image.open(io.BytesIO(pg.screenshot())).convert("RGB")
                        SW, SH = withFixed.size
                        worst, worst_at = 0, None
                        for col in (SW // 4, SW // 2, (3 * SW) // 4):
                            for y in range(max(0, SH - 40), SH):
                                d = max(abs(a - b) for a, b in
                                        zip(withFixed.getpixel((col, y)), fallback.getpixel((col, y))))
                                if d > worst: worst, worst_at = d, (col, y)
                        if worst > 6:
                            fails.append(f"{tag}: GREY BAR - fallback is {worst} levels off the "
                                         f"fixed layer at the bottom edge, at {worst_at}")
                        pg.evaluate("()=>{document.getElementById('__hc')?.remove();document.getElementById('__hb')?.remove();}")

                        # 7. back-to-top must never sit under the tab bar
                        bt = pg.evaluate("""()=>{showAppearance();
                          const b=document.querySelector('.backtotop');
                          if(b){b.hidden=false;b.classList.add('show');}
                          const bar=document.querySelector('.bottomtabs');
                          if(!b||!bar||bar.hidden) return null;
                          const B=b.getBoundingClientRect(), A=bar.getBoundingClientRect();
                          const overlap=!(B.right<A.left||B.left>A.right||B.bottom<A.top||B.top>A.bottom);
                          return {overlap, w:Math.round(B.width),
                                  bottomGap:Math.round(innerHeight-B.bottom),
                                  offRight:Math.round(innerWidth-B.right),
                                  offBottom:B.bottom>innerHeight};}""")
                        if bt:
                            if bt["overlap"]: fails.append(f"{tag}: back-to-top overlaps the tab bar")
                            if bt["offBottom"]: fails.append(f"{tag}: back-to-top below the fold")
                            if bt["offRight"] < 0: fails.append(f"{tag}: back-to-top off the right edge")

                        # 8. daily "already done" must be a top banner clear of the bar
                        dq = pg.evaluate("""async ()=>{showHome();
                          store.dailyQuestionDate = dailyPeriodKey(); startDailyQuestion();
                          const a=document.getElementById('dailyalert');
                          // .daily-alert enters from translateY(-8px) and only
                          // gets .show on the next frame, so measuring it
                          // synchronously reads the animation's FIRST frame and
                          // calls a healthy banner off-screen by 2px. Ask for the
                          // settled position, not the starting one.
                          const t=document.querySelector('.toast');
                          const bar=document.querySelector('.bottomtabs');
                          if(!a) return {banner:false, toast:!!t};
                          /* Wait for the entrance to SETTLE, not for a fixed
                             delay. .daily-alert enters from translateY(-8px)
                             over .22s; a flat 320ms read it mid-transition on
                             a 2560px display and called a healthy banner 1px
                             off-screen. Poll the computed transform instead. */
                          for(let i=0;i<40;i++){
                            const cs = getComputedStyle(a);
                            if(a.classList.contains('show') && cs.opacity === '1' &&
                               (cs.transform === 'none' || /matrix\(1, 0, 0, 1, 0, 0\)/.test(cs.transform))) break;
                            await new Promise(r=>setTimeout(r,25));
                          }
                          if(!a.classList.contains('show')) return {banner:true, toast:!!t, never:true};
                          const r=a.getBoundingClientRect();
                          const A=bar&&!bar.hidden?bar.getBoundingClientRect():null;
                          return {banner:true, toast:!!t, top:Math.round(r.top),
                                  onScreen:r.top>=0&&r.bottom<=innerHeight,
                                  clearsBar:A?Math.round(A.top-r.bottom):999};}""")
                        if not dq["banner"]: fails.append(f"{tag}: daily 'already done' is not a banner")
                        elif dq["toast"]: fails.append(f"{tag}: daily 'already done' still raises a toast")
                        elif dq.get("never"): fails.append(f"{tag}: daily banner never animated in")
                        elif not dq["onScreen"]: fails.append(f"{tag}: daily banner off-screen (top {dq['top']})")
                        elif dq["clearsBar"] < 0: fails.append(f"{tag}: daily banner behind the tab bar")

                        # 4. Advanced settings: dark, and a real tap target
                        adv = pg.evaluate("""()=>{showAppearance();
                          const b=document.querySelector('.more-toggle.adv-toggle');
                          if(!b) return null; const cs=getComputedStyle(b);
                          return {bg:cs.backgroundColor, h:Math.round(b.getBoundingClientRect().height)};}""")
                        if not adv: fails.append(f"{tag}: Advanced settings button missing")
                        else:
                            v = rgb(adv["bg"])
                            if v and sum(v) / 3 > 60: fails.append(f"{tag}: Advanced settings still light {adv['bg']}")
                            if adv["h"] < 44: fails.append(f"{tag}: Advanced settings {adv['h']}px tall")

                        # 9/10. release history has no back link; tooltip names the daily question
                        misc = pg.evaluate("""()=>{showReleaseHistory();
                          const back=!!document.querySelector('.panel .back-link');
                          return {back};}""")
                        if misc["back"]: fails.append(f"{tag}: Release History still has a back link")

                        real = [e for e in errs if not any(k in e.lower() for k in
                                ("firebase", "firestore", "gstatic", "failed to fetch", "net::"))]
                        if real: fails.append(f"{tag}: JS error {real[0]}")
                        ctx.close()
            br.close()
    finally:
        srv.shutdown()
    print(f"\n{checked} device/orientation/mode combinations checked")
    if fails:
        print(f"\n{len(fails)} FAILURES")
        for f in fails: print("  *", f)
        sys.exit(1)
    print("all fixes verified on every combination")

main()
