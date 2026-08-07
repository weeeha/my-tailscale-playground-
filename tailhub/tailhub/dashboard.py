"""Self-contained HTML fleet dashboard, served at GET / by the hub.

A dark mission-control console: temperature-driven card glow, live polling of
/fleet, client-accumulated sparklines. No external JS/CSS deps (fonts from
Google Fonts with monospace fallbacks).
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tailfleet · operations</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:#070b10; --bg2:#0b1118; --panel:#0e151d; --panel2:#111b25;
    --line:#1c2a36; --line2:#273a4a;
    --text:#dCe7ef; --dim:#6b8499; --faint:#46596a;
    --cyan:#54d8ff; --teal:#34f5c8; --amber:#ffc24b; --red:#ff5d6c; --violet:#9d8cff;
    --mono:'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace;
    --disp:'Chakra Petch', var(--mono);
  }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; }
  body {
    background:
      radial-gradient(1100px 620px at 78% -8%, rgba(52,245,200,.07), transparent 60%),
      radial-gradient(900px 600px at 8% 108%, rgba(84,216,255,.06), transparent 55%),
      var(--bg);
    color:var(--text); font-family:var(--mono);
    -webkit-font-smoothing:antialiased; min-height:100%;
    background-attachment:fixed;
  }
  /* faint engineering grid + scanlines */
  body::before {
    content:""; position:fixed; inset:0; pointer-events:none; z-index:0; opacity:.5;
    background-image:
      linear-gradient(rgba(40,58,74,.16) 1px, transparent 1px),
      linear-gradient(90deg, rgba(40,58,74,.16) 1px, transparent 1px);
    background-size:46px 46px; mask-image:radial-gradient(circle at 50% 30%, #000 55%, transparent 100%);
  }
  body::after {
    content:""; position:fixed; inset:0; pointer-events:none; z-index:9999; opacity:.5;
    background:repeating-linear-gradient(0deg, rgba(0,0,0,0), rgba(0,0,0,0) 2px, rgba(0,0,0,.10) 3px, rgba(0,0,0,0) 4px);
  }
  .wrap { position:relative; z-index:1; max-width:1320px; margin:0 auto; padding:26px 24px 60px; }

  /* ---- topbar ---- */
  .top { display:flex; align-items:flex-end; justify-content:space-between; gap:24px;
         flex-wrap:wrap; border-bottom:1px solid var(--line); padding-bottom:16px; }
  .brand { display:flex; align-items:center; gap:13px; }
  .beacon { width:12px; height:12px; border-radius:50%; background:var(--teal);
            box-shadow:0 0 0 4px rgba(52,245,200,.14), 0 0 16px 2px rgba(52,245,200,.7);
            animation:pulse 2.4s ease-in-out infinite; }
  @keyframes pulse { 0%,100%{ opacity:1; transform:scale(1);} 50%{ opacity:.45; transform:scale(.82);} }
  h1 { font-family:var(--disp); font-weight:700; font-size:25px; letter-spacing:.16em;
       margin:0; text-transform:uppercase; }
  h1 .sub { color:var(--teal); }
  .tagline { font-size:11px; color:var(--faint); letter-spacing:.34em; text-transform:uppercase; margin-top:3px; }
  .stats { display:flex; gap:26px; flex-wrap:wrap; }
  .stat { text-align:right; }
  .stat .k { font-size:10px; letter-spacing:.22em; color:var(--faint); text-transform:uppercase; }
  .stat .v { font-family:var(--disp); font-weight:600; font-size:21px; margin-top:3px; letter-spacing:.04em; }
  .stat .v small { font-size:12px; color:var(--dim); font-family:var(--mono); }
  #clock { color:var(--cyan); }

  .err { display:none; margin:14px 0 0; padding:10px 14px; border:1px solid var(--red);
         border-radius:8px; background:rgba(255,93,108,.08); color:var(--red);
         font-size:13px; letter-spacing:.04em; }
  .err.on { display:block; }

  .sectlabel { display:flex; align-items:center; gap:12px; margin:30px 2px 14px;
               font-size:11px; letter-spacing:.30em; color:var(--dim); text-transform:uppercase; }
  .sectlabel::after { content:""; flex:1; height:1px;
                      background:linear-gradient(90deg, var(--line2), transparent); }

  /* ---- grid + cards ---- */
  .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(288px,1fr)); gap:16px; }
  .card { position:relative; border:1px solid var(--line); border-radius:13px;
          background:linear-gradient(180deg, var(--panel2), var(--panel));
          padding:16px 17px 15px; overflow:hidden; opacity:0; transform:translateY(14px);
          animation:rise .5s cubic-bezier(.22,.7,.3,1) forwards;
          transition:border-color .25s, transform .25s, box-shadow .25s; }
  @keyframes rise { to { opacity:1; transform:none; } }
  .card:hover { transform:translateY(-3px); border-color:var(--accent,var(--line2));
                box-shadow:0 14px 34px -18px rgba(0,0,0,.9); }
  .card::before { content:""; position:absolute; left:0; right:0; top:0; height:2px;
                  background:var(--accent,var(--line2));
                  box-shadow:0 0 16px 1px var(--accent,transparent); opacity:.9; }
  /* corner glow keyed to temperature */
  .card::after { content:""; position:absolute; right:-44px; top:-44px; width:120px; height:120px;
                 border-radius:50%; background:radial-gradient(circle, var(--accent), transparent 68%);
                 opacity:.16; pointer-events:none; }
  .card.off { opacity:.52; filter:saturate(.35); }
  .card.off::after { opacity:.05; }

  .chead { display:flex; align-items:center; gap:9px; }
  .dot { width:8px; height:8px; border-radius:50%; background:var(--accent,var(--faint)); flex:none;
         box-shadow:0 0 9px var(--accent); }
  .off .dot { box-shadow:none; background:var(--faint); }
  .host { font-weight:600; font-size:15px; letter-spacing:.02em; flex:1; min-width:0;
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .badge { font-size:9.5px; letter-spacing:.18em; padding:3px 7px; border-radius:5px;
           text-transform:uppercase; border:1px solid var(--accent); color:var(--accent); }
  .off .badge { color:var(--faint); border-color:var(--line2); }
  .model { font-size:11px; color:var(--dim); margin:4px 0 0 17px; letter-spacing:.02em;
           overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

  .midrow { display:flex; align-items:center; justify-content:space-between; margin:11px 0 12px; }
  .temp { font-family:var(--disp); font-weight:700; font-size:38px; line-height:.9;
          color:var(--accent); letter-spacing:.01em; }
  .temp .u { font-size:15px; color:var(--dim); font-weight:500; margin-left:1px; }
  .temp.na { font-size:20px; color:var(--faint); }
  svg.spark { width:108px; height:34px; }
  svg.spark polyline { fill:none; stroke:var(--accent); stroke-width:1.6; vector-effect:non-scaling-stroke; }
  svg.spark .fillarea { fill:var(--accent); opacity:.10; stroke:none; }

  .bars { display:flex; flex-direction:column; gap:7px; }
  .bar { display:grid; grid-template-columns:30px 1fr 62px; align-items:center; gap:9px; }
  .bar .bk { font-size:9.5px; letter-spacing:.14em; color:var(--faint); }
  .track { height:5px; border-radius:3px; background:#0a1219; overflow:hidden; border:1px solid #16222d; }
  .fill { height:100%; border-radius:3px; transition:width .5s cubic-bezier(.3,.8,.3,1); }
  .bar .bv { font-size:11.5px; text-align:right; color:var(--text); letter-spacing:.02em; }

  .foot { display:flex; align-items:center; justify-content:space-between; gap:8px;
          margin-top:13px; padding-top:11px; border-top:1px solid var(--line);
          font-size:11px; color:var(--dim); }
  .up { letter-spacing:.04em; }
  .app { display:inline-flex; align-items:center; gap:6px; padding:3px 9px; border-radius:20px;
         border:1px solid var(--line2); font-size:10.5px; letter-spacing:.06em; }
  .app .ad { width:6px; height:6px; border-radius:50%; }
  .flag { color:var(--red); font-weight:600; letter-spacing:.1em; }

  /* others strip */
  .chips { display:flex; flex-wrap:wrap; gap:9px; }
  .chip { display:inline-flex; align-items:center; gap:8px; padding:7px 13px; border-radius:9px;
          border:1px solid var(--line); background:var(--panel); font-size:12.5px; color:var(--dim);
          letter-spacing:.02em; }
  .chip .cd { width:7px; height:7px; border-radius:50%; }
  .chip.up .cd { background:var(--teal); box-shadow:0 0 8px var(--teal); }
  .chip.down { opacity:.5; }
  .chip.up { color:var(--text); }

  footer { margin-top:34px; padding-top:14px; border-top:1px solid var(--line);
           display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px;
           font-size:11px; color:var(--faint); letter-spacing:.06em; }
  .live { display:inline-flex; align-items:center; gap:7px; color:var(--teal); }
  .live .ld { width:7px; height:7px; border-radius:50%; background:var(--teal);
              box-shadow:0 0 8px var(--teal); animation:pulse 1.6s ease-in-out infinite; }
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand">
      <span class="beacon"></span>
      <div>
        <h1>tail<span class="sub">fleet</span></h1>
        <div class="tagline">tailnet · operations console</div>
      </div>
    </div>
    <div class="stats">
      <div class="stat"><div class="k">probes online</div><div class="v" id="s-online">–</div></div>
      <div class="stat"><div class="k">hottest</div><div class="v" id="s-hot">–</div></div>
      <div class="stat"><div class="k">tailnet</div><div class="v" id="s-net">–</div></div>
      <div class="stat"><div class="k">station time</div><div class="v" id="clock">–</div></div>
    </div>
  </div>
  <div class="err" id="err"></div>

  <div class="sectlabel">probe agents</div>
  <div class="grid" id="grid"></div>

  <div class="sectlabel">other tailnet devices</div>
  <div class="chips" id="chips"></div>

  <footer>
    <span class="live"><span class="ld"></span> live · polling /fleet every 5s</span>
    <span id="updated">awaiting first scrape…</span>
  </footer>
</div>

<script>
const HIST = {};                 // host -> [temps]  (client-accumulated sparkline)
const HMAX = 48;
let lastOk = null;

function tempColor(t){
  if (t==null) return 'var(--faint)';
  if (t<45) return '#54d8ff';
  if (t<55) return '#34f5c8';
  if (t<65) return '#ffc24b';
  return '#ff5d6c';
}
function pctColor(p){ return p>=90?'#ff5d6c':p>=75?'#ffc24b':'#34f5c8'; }
function fmtUp(s){ if(!s) return '–'; const d=s/86400; return d>=1? d.toFixed(1)+'d' : (s/3600).toFixed(1)+'h'; }
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function spark(host, accent){
  const h = HIST[host]||[];
  if (h.length<2) return '<svg class="spark" viewBox="0 0 108 34"></svg>';
  const lo=Math.min(...h), hi=Math.max(...h), rng=(hi-lo)||1;
  const pts = h.map((v,i)=>{
    const x = (i/(h.length-1))*108;
    const y = 31 - ((v-lo)/rng)*27;
    return x.toFixed(1)+','+y.toFixed(1);
  });
  const area = '0,34 '+pts.join(' ')+' 108,34';
  return `<svg class="spark" viewBox="0 0 108 34" preserveAspectRatio="none">
    <polygon class="fillarea" points="${area}"></polygon>
    <polyline points="${pts.join(' ')}"></polyline></svg>`;
}

function bar(label, pct, valText){
  const p = Math.max(0, Math.min(100, pct||0));
  return `<div class="bar"><span class="bk">${label}</span>
    <span class="track"><span class="fill" style="width:${p}%;background:${pctColor(p)}"></span></span>
    <span class="bv">${valText}</span></div>`;
}

function appPill(apps){
  const names = Object.keys(apps||{});
  if (!names.length) return '<span class="app" style="color:var(--faint)">no app</span>';
  const n = names[0], v = apps[n];
  const col = v===true?'var(--teal)':v===false?'var(--red)':'var(--amber)';
  const txt = v===true?'up':v===false?'down':'unknown';
  return `<span class="app"><span class="ad" style="background:${col};box-shadow:0 0 7px ${col}"></span>${esc(n)} · ${txt}</span>`;
}

function card(d, i){
  const m = d.snapshot.metrics||{}, cfg = d.snapshot.config||{}, fl = d.snapshot.flags||{};
  const t = (typeof m.soc_temp_c==='number')? m.soc_temp_c : null;
  const accent = d.online ? tempColor(t) : 'var(--faint)';
  if (d.online && t!=null){ (HIST[d.host]=HIST[d.host]||[]).push(t); if(HIST[d.host].length>HMAX) HIST[d.host].shift(); }
  const tempHtml = (d.online && t!=null)
      ? `<div class="temp">${t.toFixed(1)}<span class="u">°C</span></div>`
      : `<div class="temp na">${d.online?'no temp':'OFFLINE'}</div>`;
  const body = d.online ? `
    <div class="midrow">${tempHtml}${spark(d.host, accent)}</div>
    <div class="bars">
      ${bar('CPU', m.cpu_pct, (m.cpu_pct??0).toFixed(0)+'%')}
      ${bar('MEM', m.mem_pct, (m.mem_pct??0).toFixed(0)+'%')}
      ${bar('DSK', m.disk_used_pct, (m.disk_free_gb??0).toFixed(1)+'GB free')}
    </div>
    <div class="foot">
      <span class="up">▲ ${fmtUp(m.uptime_s)}${fl.throttled?' · <span class="flag">THROTTLED</span>':''}${fl.under_voltage?' · <span class="flag">UNDER-VOLT</span>':''}</span>
      ${appPill(d.snapshot.apps)}
    </div>` : `<div class="midrow">${tempHtml}</div>
      <div class="foot"><span class="up">last seen ${d.last_seen?timeAgo(d.last_seen):'–'}</span></div>`;
  return `<div class="card ${d.online?'':'off'}" style="--accent:${accent};animation-delay:${Math.min(i*45,650)}ms">
    <div class="chead"><span class="dot"></span>
      <span class="host">${esc(d.host)}</span>
      <span class="badge">${d.online?'online':'offline'}</span></div>
    <div class="model">${esc(cfg.model||(d.online?'—':'no agent reachable'))}</div>
    ${body}</div>`;
}

function timeAgo(ts){ const s=Math.max(0,Date.now()/1000-ts); if(s<90)return Math.round(s)+'s ago';
  if(s<5400)return Math.round(s/60)+'m ago'; return Math.round(s/3600)+'h ago'; }

function render(devices){
  const probes = devices.filter(d=>d.has_probe).sort((a,b)=>{
    if(a.online!==b.online) return a.online?-1:1;
    const ta=a.snapshot.metrics?.soc_temp_c??-1, tb=b.snapshot.metrics?.soc_temp_c??-1;
    return tb-ta; });
  const others = devices.filter(d=>!d.has_probe).sort((a,b)=>a.host.localeCompare(b.host));

  document.getElementById('grid').innerHTML = probes.map(card).join('');
  document.getElementById('chips').innerHTML = others.map(d=>
    `<span class="chip ${d.online?'up':'down'}"><span class="cd"></span>${esc(d.host)}</span>`).join('') || '<span class="chip down">none</span>';

  const on = probes.filter(d=>d.online).length;
  document.getElementById('s-online').innerHTML = `${on}<small>/${probes.length}</small>`;
  const hot = probes.filter(d=>d.online && typeof d.snapshot.metrics?.soc_temp_c==='number')
                    .sort((a,b)=>b.snapshot.metrics.soc_temp_c-a.snapshot.metrics.soc_temp_c)[0];
  document.getElementById('s-hot').innerHTML = hot
     ? `${hot.snapshot.metrics.soc_temp_c.toFixed(0)}°<small> ${esc(hot.host)}</small>` : '–';
  document.getElementById('s-net').innerHTML = `${devices.filter(d=>d.online).length}<small>/${devices.length}</small>`;
}

async function load(){
  try {
    const r = await fetch('/fleet', {cache:'no-store'});
    if(!r.ok) throw new Error('HTTP '+r.status);
    const data = await r.json();
    render(data.devices||[]);
    lastOk = Date.now();
    document.getElementById('err').classList.remove('on');
    document.getElementById('updated').textContent = 'updated ' + new Date().toLocaleTimeString();
  } catch(e){
    const el = document.getElementById('err');
    el.textContent = '⚠ hub unreachable — ' + e.message + (lastOk?` (last ok ${new Date(lastOk).toLocaleTimeString()})`:'');
    el.classList.add('on');
  }
}
function tick(){ document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-GB'); }
tick(); setInterval(tick, 1000);
load(); setInterval(load, 5000);
</script>
</body>
</html>
"""
