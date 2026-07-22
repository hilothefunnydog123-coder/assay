"""`assay serve` — a local web dashboard for your eval runs.

Reads the run history under ``.assay/`` and serves a single-page dashboard: pass
rate over time, regressions, and a drill-down of every case. Standard library
only (``http.server``); nothing leaves your machine.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import store


def gather(root: str = store.ROOT) -> dict:
    runs_dir = os.path.join(root, "runs")
    evals = []
    if os.path.isdir(runs_dir):
        for name in sorted(os.listdir(runs_dir)):
            d = os.path.join(runs_dir, name)
            if not os.path.isdir(d):
                continue
            runs = []
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    with open(os.path.join(d, fn)) as f:
                        runs.append(json.load(f))
            if runs:
                evals.append({"name": runs[-1]["eval"], "runs": runs})
    return {"evals": evals}


def _handler(root: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/api/data"):
                self._send(json.dumps(gather(root)).encode(), "application/json")
            else:
                self._send(PAGE.encode(), "text/html; charset=utf-8")

    return Handler


def serve(port: int = 8787, root: str = store.ROOT) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler(root))
    url = f"http://127.0.0.1:{port}"
    print(f"assay dashboard on {url}   (ctrl-c to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Assay</title>
<style>
:root{
  --bg:#08090d; --panel:#0f1219; --panel2:#141924; --line:#20263400;
  --border:#1e2532; --text:#e8edf6; --dim:#8b95a7; --green:#3fb950; --red:#f85149;
  --blue:#58a6ff; --gold:#f0c674; --violet:#a371f7;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:radial-gradient(1200px 600px at 70% -10%,#141c2e 0%,var(--bg) 60%);
  color:var(--text);font:15px/1.5 'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  min-height:100vh;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:36px 28px 80px}
header{display:flex;align-items:center;gap:14px;margin-bottom:8px}
.logo{width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,var(--green),#2ea043);
  display:grid;place-items:center;font-weight:800;color:#04130a;font-size:18px;
  box-shadow:0 0 24px rgba(63,185,80,.4)}
h1{font-size:22px;font-weight:700;letter-spacing:-.02em}
.sub{color:var(--dim);font-size:13px;margin-left:auto}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:26px 0 20px}
.tab{padding:7px 15px;border-radius:999px;border:1px solid var(--border);background:var(--panel);
  color:var(--dim);cursor:pointer;font-size:13px;font-weight:500;transition:.15s;white-space:nowrap}
.tab:hover{color:var(--text);border-color:#2c3547}
.tab.on{background:rgba(63,185,80,.12);border-color:var(--green);color:var(--green)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}
.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--border);
  border-radius:16px;padding:18px 20px}
.stat .k{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.stat .v{font-size:30px;font-weight:800;letter-spacing:-.03em;margin-top:6px}
.stat .v small{font-size:15px;font-weight:600;color:var(--dim)}
.hero .v{font-size:52px}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700}
.pill.up{background:rgba(63,185,80,.16);color:var(--green)}
.pill.down{background:rgba(248,81,73,.16);color:var(--red)}
.chart{margin-bottom:18px}
.chart h3,.cases h3{font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;
  font-weight:600;margin-bottom:14px}
.banner{border:1px solid var(--red);background:rgba(248,81,73,.09);border-radius:14px;
  padding:14px 18px;margin-bottom:18px}
.banner b{color:var(--red)}
.banner ul{margin:8px 0 0 2px;list-style:none}
.banner li{color:var(--dim);font-size:13px;padding:3px 0}
.banner li code{color:var(--text);background:#000;padding:1px 6px;border-radius:5px}
.row{display:flex;align-items:center;gap:14px;padding:13px 16px;border:1px solid var(--border);
  border-radius:12px;margin-bottom:8px;background:var(--panel);cursor:pointer;transition:.12s}
.row:hover{border-color:#2c3547;background:var(--panel2)}
.badge{font-size:11px;font-weight:800;padding:4px 9px;border-radius:7px;letter-spacing:.03em}
.badge.p{background:rgba(63,185,80,.16);color:var(--green)}
.badge.f{background:rgba(248,81,73,.16);color:var(--red)}
.cid{font-weight:600}
.ms{margin-left:auto;color:var(--dim);font-size:12px;font-variant-numeric:tabular-nums}
.detail{display:none;padding:4px 16px 14px 16px;margin:-4px 0 8px;border:1px solid var(--border);
  border-top:none;border-radius:0 0 12px 12px;background:#0b0e14}
.detail.open{display:block}
.detail .kv{display:grid;grid-template-columns:76px 1fr;gap:6px 12px;font-size:13px;margin-top:8px}
.detail .kv .lab{color:var(--dim)}
.detail code{background:#000;padding:2px 7px;border-radius:6px;color:var(--text);
  white-space:pre-wrap;word-break:break-word}
.sc{display:inline-flex;gap:6px;align-items:center;font-size:12px;color:var(--dim);margin-top:6px}
.dot{width:7px;height:7px;border-radius:50%}
.foot{color:var(--dim);font-size:12px;text-align:center;margin-top:30px}
@media(max-width:760px){.grid{grid-template-columns:repeat(2,1fr)}}
</style></head>
<body><div class="wrap">
<header>
  <div class="logo">A</div>
  <h1>Assay</h1>
  <div class="sub" id="sub">reliability dashboard</div>
</header>
<div class="tabs" id="tabs"></div>
<div id="app"></div>
<div class="foot">reading <code>.assay/</code> · refreshes every 4s · <code>assay serve</code></div>
</div>
<script>
const $=(s,e=document)=>e.querySelector(s);
let DATA={evals:[]}, cur=0;
const pct=x=>Math.round(x*100);
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const short=s=>{s=typeof s==='string'?s:JSON.stringify(s);return s.length>120?s.slice(0,120)+'…':s};

function diffRuns(a,b){ // regressions between prev(a) and latest(b)
  if(!a) return [];
  const A={}; a.results.forEach(r=>A[r.case_id]=r);
  return b.results.filter(r=>A[r.case_id]&&A[r.case_id].passed&&!r.passed);
}
function sparkline(runs){
  const w=1040,h=120,p=14, xs=runs.map((_,i)=>i), ys=runs.map(r=>r.pass_rate);
  if(runs.length<2){return `<div style="color:var(--dim);font-size:13px;padding:20px 0">one run so far — history builds as you re-run.</div>`}
  const X=i=>p+(w-2*p)*i/(runs.length-1), Y=v=>h-p-(h-2*p)*v;
  const line=xs.map(i=>`${X(i).toFixed(1)},${Y(ys[i]).toFixed(1)}`).join(' ');
  const area=`${X(0)},${h-p} ${line} ${X(xs.length-1)},${h-p}`;
  const dots=xs.map(i=>{const c=ys[i]>=.9?'var(--green)':ys[i]>=.7?'var(--gold)':'var(--red)';
    return `<circle cx="${X(i).toFixed(1)}" cy="${Y(ys[i]).toFixed(1)}" r="3.5" fill="${c}"/>`}).join('');
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" preserveAspectRatio="none" style="display:block">
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="var(--green)" stop-opacity=".35"/>
      <stop offset="1" stop-color="var(--green)" stop-opacity="0"/></linearGradient></defs>
    <line x1="${p}" y1="${Y(1)}" x2="${w-p}" y2="${Y(1)}" stroke="#1e2532" stroke-dasharray="3 4"/>
    <polygon points="${area}" fill="url(#g)"/>
    <polyline points="${line}" fill="none" stroke="var(--green)" stroke-width="2.5" stroke-linejoin="round"/>
    ${dots}</svg>`;
}
function render(){
  const tabs=$('#tabs'); tabs.innerHTML='';
  DATA.evals.forEach((e,i)=>{const t=document.createElement('div');
    t.className='tab'+(i===cur?' on':''); t.textContent=e.name;
    t.onclick=()=>{cur=i;render()}; tabs.appendChild(t)});
  const ev=DATA.evals[cur];
  if(!ev){$('#app').innerHTML=`<div class="card" style="text-align:center;color:var(--dim);padding:50px">No runs yet. Run <code>assay run evals/</code> then refresh.</div>`;return}
  const runs=ev.runs, last=runs[runs.length-1], prev=runs[runs.length-2];
  const regs=diffRuns(prev,last);
  const delta=prev?pct(last.pass_rate)-pct(prev.pass_rate):0;
  const avgMs=last.results.reduce((s,r)=>s+r.latency_ms,0)/last.results.length;
  $('#sub').textContent=last.started_at.slice(0,19).replace('T',' ');
  const pillHtml=prev?`<span class="pill ${delta>=0?'up':'down'}">${delta>=0?'+':''}${delta} pts</span>`:'';
  const heroColor=last.pass_rate>=.9?'var(--green)':last.pass_rate>=.7?'var(--gold)':'var(--red)';
  let html=`<div class="grid">
    <div class="card stat hero"><div class="k">pass rate</div>
      <div class="v" style="color:${heroColor}">${pct(last.pass_rate)}<small>%</small> ${pillHtml}</div></div>
    <div class="card stat"><div class="k">cases</div><div class="v">${last.passed}<small>/${last.n}</small></div></div>
    <div class="card stat"><div class="k">regressions</div><div class="v" style="color:${regs.length?'var(--red)':'var(--text)'}">${regs.length}</div></div>
    <div class="card stat"><div class="k">avg latency</div><div class="v">${avgMs.toFixed(0)}<small>ms</small></div></div>
  </div>`;
  if(regs.length){html+=`<div class="banner"><b>${regs.length} regression${regs.length>1?'s':''}</b> — passing last run, failing now:
    <ul>${regs.map(r=>`<li><code>${esc(r.case_id)}</code> — got <code>${esc(short(r.output))}</code>, expected <code>${esc(short(r.expect))}</code></li>`).join('')}</ul></div>`}
  html+=`<div class="card chart"><h3>pass rate over ${runs.length} runs</h3>${sparkline(runs)}</div>`;
  html+=`<div class="cases"><h3>cases · latest run</h3>`;
  last.results.forEach((r,i)=>{
    html+=`<div class="row" onclick="this.nextElementSibling.classList.toggle('open')">
      <span class="badge ${r.passed?'p':'f'}">${r.passed?'PASS':'FAIL'}</span>
      <span class="cid">${esc(r.case_id)}</span>
      <span class="ms">${r.latency_ms.toFixed(0)}ms</span></div>
      <div class="detail"><div class="kv">
        <span class="lab">input</span><code>${esc(short(r.input))}</code>
        <span class="lab">output</span><code>${esc(short(r.output))}</code>
        <span class="lab">expect</span><code>${esc(short(r.expect))}</code></div>
        ${r.scores.map(s=>`<div class="sc"><span class="dot" style="background:${s.passed?'var(--green)':'var(--red)'}"></span>${esc(s.name)}${s.reason?' — '+esc(s.reason):''}</div>`).join('')}
      </div>`;
  });
  html+=`</div>`;
  $('#app').innerHTML=html;
}
async function load(){try{DATA=await (await fetch('/api/data')).json();
  if(cur>=DATA.evals.length)cur=0;render()}catch(e){}}
load(); setInterval(load,4000);
</script></body></html>"""
