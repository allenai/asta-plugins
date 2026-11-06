#!/usr/bin/env python3
"""Rendered review of a Quarto reveal.js deck's changes: changed, new and removed
slides as images, with a Clean / Changes-marked switch and unchanged slides
around each change that open full size, like a code diff's context.

Prototype for asta-plugins' What changed. Usage:

    deck_review.py OLD_DIR NEW_DIR DECK_PATH OUT_DIR [--title T] [--port P]

OLD_DIR and NEW_DIR are two built sites; DECK_PATH is the deck's path inside
them (e.g. slides/workspace/slides.html). Needs agent-browser on PATH.
Slides are matched by their id (Quarto's slug of the title), then by title.
A slide is "changed" when its text or its rendered image differs.
"""
import argparse, difflib, hashlib, html, json, os, shutil, subprocess, sys, threading, time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SESSION = "deck-review"
CONTEXT = 2  # unchanged slides offered before and after each change

def ab(*args, timeout=60):
    r = subprocess.run(["agent-browser", "--session", SESSION, *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"agent-browser {' '.join(args[:2])}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()

def ev(js):
    out = ab("eval", js)
    for _ in range(2):  # agent-browser prints the result as JSON; a stringified result is JSON inside that
        try:
            out = json.loads(out)
        except (json.JSONDecodeError, TypeError):
            break
        if not isinstance(out, str):
            break
    return out

LIST_JS = """JSON.stringify(Reveal.getSlides().map((s, i) => {
  const h = s.querySelector('h1, h2'); const x = Reveal.getIndices(s);
  return { i, h: x.h, v: x.v || 0, id: s.id || '', title: h ? h.textContent.trim() : '',
           text: (() => { const w=document.createTreeWalker(s, NodeFilter.SHOW_TEXT); const p=[]; let n; while((n=w.nextNode())) p.push(n.textContent); return p.join(' ').replace(/\\s+/g, ' ').trim(); })() };
}))"""

GOTO_JS = "(() => {{ Reveal.slide({h}, {v}, Infinity); return 1; }})()"

MARK_CSS = (".dr-ins{background:rgba(47,191,113,.3);color:inherit;text-decoration:none;border-radius:.15em;padding:0 .06em}"
            ".dr-del{background:rgba(253,70,69,.28);color:inherit;border-radius:.15em;padding:0 .06em;text-decoration-thickness:.08em}"
            ".dr-frame{position:fixed;inset:0;pointer-events:none;z-index:99;border:6px solid var(--dr-c)}"
            ".dr-badge{position:fixed;right:24px;top:20px;z-index:100;background:var(--dr-c);color:#04140f;font:700 22px/1 system-ui,sans-serif;padding:8px 14px;border-radius:8px}")

def frame_js(color, label):
    return (f"(() => {{ const st=document.createElement('style'); st.textContent={json.dumps(MARK_CSS)}; document.head.append(st);"
            f" const f=document.createElement('div'); f.className='dr-frame'; f.style.setProperty('--dr-c','{color}'); document.body.append(f);"
            f" const b=document.createElement('div'); b.className='dr-badge'; b.style.setProperty('--dr-c','{color}'); b.textContent={json.dumps(label)}; document.body.append(b); return 1; }})()")

def mark_words_js(old_text):
    # Mark, inside the current slide's text nodes, the words that differ from the old slide's text.
    return ("(() => { const st=document.createElement('style'); st.textContent=" + json.dumps(MARK_CSS) + "; document.head.append(st);"
            " const old=" + json.dumps(old_text.split()) + ";"
            " const s=Reveal.getCurrentSlide(); const w=document.createTreeWalker(s, NodeFilter.SHOW_TEXT); const nodes=[]; let n;"
            " while((n=w.nextNode())) if(n.textContent.trim()) nodes.push(n);"
            " const words=[]; nodes.forEach((nd,k)=>nd.textContent.split(/(\\s+)/).forEach(t=>{ if(t.trim()) words.push([k,t]); }));"
            " const a=old, b=words.map(x=>x[1]); const m=a.length, q=b.length; const L=Array.from({length:m+1},()=>new Int32Array(q+1));"
            " for(let i=m-1;i>=0;i--) for(let j=q-1;j>=0;j--) L[i][j]= a[i]===b[j] ? L[i+1][j+1]+1 : Math.max(L[i+1][j],L[i][j+1]);"
            " const keep=new Set(); const dels={}; let i=0,j=0;"
            " while(i<m&&j<q){ if(a[i]===b[j]){keep.add(j);i++;j++;} else if(L[i+1][j]>=L[i][j+1]){ (dels[j]=dels[j]||[]).push(a[i]); i++; } else j++; }"
            " while(i<m){ (dels[q]=dels[q]||[]).push(a[i]); i++; }"
            " let idx=0; nodes.forEach((nd,k)=>{ const frag=document.createDocumentFragment();"
            "  nd.textContent.split(/(\\s+)/).forEach(t=>{ if(!t.trim()){ frag.append(t); return; }"
            "   if(dels[idx]){ const d=document.createElement('del'); d.className='dr-del'; d.textContent=dels[idx].join(' '); frag.append(d,' '); }"
            "   if(keep.has(idx)) frag.append(t); else { const e=document.createElement('ins'); e.className='dr-ins'; e.textContent=t; frag.append(e); }"
            "   idx++; });"
            "  if(k===nodes.length-1 && dels[q]){ const d=document.createElement('del'); d.className='dr-del'; d.textContent=' '+dels[q].join(' '); frag.append(d); }"
            "  nd.replaceWith(frag); });"
            " Reveal.layout(); return 1; })()")

def serve(root):
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

def open_deck(url):
    ab("open", url)
    ab("wait", "2500")

def shoot(url, slide, path, extra_js=None):
    open_deck(url)
    ev(GOTO_JS.format(h=slide["h"], v=slide["v"]))
    time.sleep(0.5)
    if extra_js:
        ev(extra_js)
        time.sleep(0.3)
    ab("screenshot", str(path))
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("old"); p.add_argument("new"); p.add_argument("deck"); p.add_argument("out")
    p.add_argument("--title", default="Deck changes")
    a = p.parse_args()
    out = Path(a.out); img = out / "img"
    if out.exists():
        shutil.rmtree(img, ignore_errors=True)
    img.mkdir(parents=True, exist_ok=True)
    root = out / "_sites"
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(a.old, root / "old"); shutil.copytree(a.new, root / "new")
    srv = serve(root); base = f"http://127.0.0.1:{srv.server_address[1]}"
    old_url, new_url = f"{base}/old/{a.deck}", f"{base}/new/{a.deck}"
    ab("set", "viewport", "1600", "900")
    try:
        open_deck(old_url); old = ev(LIST_JS)
        open_deck(new_url); new = ev(LIST_JS)
        if not isinstance(old, list) or not isinstance(new, list) or not new:
            sys.exit("could not read the decks' slides (is Reveal loaded?)")
        key = lambda s: s["id"] or s["title"]
        old_by = {key(s): s for s in old}
        new_keys = {key(s) for s in new}
        rows = []
        for s in new:
            o = old_by.get(key(s))
            if o is None:
                kind = "new"
            elif o["text"] != s["text"]:
                kind = "changed"
            else:
                kind = "same?"  # text equal: compare images below
            rows.append({"slide": s, "old": o, "kind": kind})
        # Image check for text-equal slides is costly; only near-certain changes are rendered.
        for r in rows:
            if r["kind"] == "same?":
                r["kind"] = "unchanged"
        removed = [s for s in old if key(s) not in new_keys]
        # A retitled slide gets a new id: pair a new slide with a removed one whose text is mostly the same.
        for r in rows:
            if r["kind"] != "new" or not removed:
                continue
            best = max(removed, key=lambda o: difflib.SequenceMatcher(None, o["text"], r["slide"]["text"]).ratio())
            if difflib.SequenceMatcher(None, best["text"], r["slide"]["text"]).ratio() >= 0.5:
                r["kind"], r["old"] = "changed", best
                removed.remove(best)
        changed_idx = [k for k, r in enumerate(rows) if r["kind"] != "unchanged"]
        show = set()
        for k in changed_idx:
            show.update(range(max(0, k - CONTEXT), min(len(rows), k + CONTEXT + 1)))
        items = []
        for k in sorted(show):
            r = rows[k]; s = r["slide"]; n = s["i"] + 1
            clean = img / f"s{n}.png"
            shoot(new_url, s, clean)
            it = {"n": n, "title": s["title"], "kind": r["kind"], "clean": f"img/s{n}.png", "link": f"_sites/new/{a.deck}#/{s['h']}/{s['v']}"}
            if r["kind"] == "new":
                shoot(new_url, s, img / f"s{n}-m.png", frame_js("#2fbf71", "New slide")); it["marked"] = f"img/s{n}-m.png"
            elif r["kind"] == "changed":
                shoot(new_url, s, img / f"s{n}-m.png", mark_words_js(r["old"]["text"])); it["marked"] = f"img/s{n}-m.png"
                shoot(old_url, r["old"], img / f"s{n}-b.png"); it["before"] = f"img/s{n}-b.png"
            items.append(it)
        rem = []
        for s in removed:
            n = s["i"] + 1
            shoot(old_url, s, img / f"r{n}.png", frame_js("#fd4645", "Removed")); rem.append({"n": n, "title": s["title"], "img": f"img/r{n}.png"})
    finally:
        try: ab("close")
        except Exception: pass
        srv.shutdown()
    page = PAGE.replace("__TITLE__", html.escape(a.title)).replace("__DATA__", json.dumps({"items": items, "removed": rem, "total": len(new)}))
    (out / "index.html").write_text(page)
    nc = sum(1 for r in rows if r["kind"] == "changed"); nn = sum(1 for r in rows if r["kind"] == "new")
    print(f"deck_review: {nc} changed, {nn} new, {len(rem)} removed of {len(new)} slides -> {out / 'index.html'}")

PAGE = r"""<!doctype html><meta charset="utf-8"><title>__TITLE__</title>
<style>
:root{color-scheme:dark;--bg:#0f1a1c;--fg:#f4ece4;--muted:#9fb3b0;--line:#2b3b3d;--chip:#1a2a2c}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;padding:0 max(16px,3vw) 48px}
header{position:sticky;top:0;background:var(--bg);padding:14px 0 10px;border-bottom:1px solid var(--line);z-index:5;display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center}
h1{font-size:20px;margin:0}.count{color:var(--muted)}
.seg{margin-left:auto;display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{font:inherit;background:none;color:var(--muted);border:0;padding:6px 14px;cursor:pointer}
.seg button[aria-pressed=true]{background:var(--fg);color:var(--bg);font-weight:600}
.s{max-width:1100px;margin:18px 0}.s h2{font-size:15px;font-weight:600;margin:0 0 6px}
.tag{font-size:12px;font-weight:600;padding:1px 8px;border-radius:10px;margin-left:8px}
.new{background:#163d29;color:#2fbf71}.changed{background:#1d3346;color:#7fb8ff}.removed{background:#3d1616;color:#ff8a89}
.s img{width:100%;display:block;border:1px solid var(--line);border-radius:6px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}.pair figcaption{color:var(--muted);font-size:12px}
.more{font:inherit;font-size:13px;color:var(--muted);background:var(--chip);border:1px dashed var(--line);border-radius:6px;padding:6px 12px;cursor:pointer;display:block;margin:8px 0;max-width:1100px;width:100%;text-align:left}
.u h2{color:var(--muted)}[hidden]{display:none!important}
</style>
<header><h1>__TITLE__</h1><span class="count" id="count"></span>
<span class="seg" role="group" aria-label="View"><button data-v="marked" aria-pressed="true">Changes marked</button><button data-v="clean" aria-pressed="false">Clean</button><button data-v="before" aria-pressed="false">Before / after</button></span></header>
<main id="m"></main>
<script>
const D=__DATA__; const m=document.getElementById('m');
const nc=D.items.filter(i=>i.kind==='changed').length, nn=D.items.filter(i=>i.kind==='new').length;
document.getElementById('count').textContent=`${nc} changed, ${nn} new, ${D.removed.length} removed, of ${D.total} slides`;
let run=null;
const flush=()=>{ if(!run) return; const r=run; run=null; const b=document.createElement('button'); b.className='more';
  b.textContent=`⋯ ${r.length} unchanged slide${r.length>1?'s':''} (${r[0].n}${r.length>1?'–'+r[r.length-1].n:''})`;
  const box=document.createElement('div'); box.hidden=true; r.forEach(i=>box.append(card(i))); b.onclick=()=>{box.hidden=!box.hidden}; m.append(b,box); };
const card=i=>{ const d=document.createElement('section'); d.className='s'+(i.kind==='unchanged'?' u':'');
  const tag=i.kind==='unchanged'?'':`<span class="tag ${i.kind}">${i.kind}</span>`;
  d.innerHTML=`<h2>Slide ${i.n} · ${i.title}${tag}</h2>`;
  const a=document.createElement('a'); a.href=i.link; const im=document.createElement('img'); im.dataset.clean=i.clean; im.dataset.marked=i.marked||i.clean; a.append(im);
  if(i.before){ const p=document.createElement('div'); p.className='pair'; p.dataset.pair=1; p.hidden=true;
    p.innerHTML=`<figure style="margin:0"><figcaption>Before</figcaption><img src="${i.before}"></figure><figure style="margin:0"><figcaption>After</figcaption><img src="${i.clean}"></figure>`; d.append(a,p); }
  else d.append(a);
  return d; };
let last=0;
for(const i of D.items){ if(i.kind==='unchanged'){ if(run && i.n!==run[run.length-1].n+1) flush(); (run=run||[]).push(i); continue; } flush(); m.append(card(i)); }
flush();
for(const r of D.removed){ const d=document.createElement('section'); d.className='s'; d.innerHTML=`<h2>Slide ${r.n} (old deck) · ${r.title}<span class="tag removed">removed</span></h2><img src="${r.img}">`; m.append(d); }
const set=v=>{ document.querySelectorAll('.seg button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v===v)));
  document.querySelectorAll('img[data-clean]').forEach(im=>{ im.src = v==='clean' ? im.dataset.clean : im.dataset.marked; const p=im.closest('section').querySelector('[data-pair]'); if(p){ p.hidden = v!=='before'; im.parentElement.hidden = v==='before'; } }); };
document.querySelectorAll('.seg button').forEach(b=>b.onclick=()=>set(b.dataset.v));
addEventListener('keydown',e=>{ if(e.key==='d'){ const cur=document.querySelector('.seg [aria-pressed=true]').dataset.v; set(cur==='clean'?'marked':'clean'); } });
set('marked');
</script>"""

if __name__ == "__main__":
    main()
