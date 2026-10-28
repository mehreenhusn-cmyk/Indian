"""api/ai_pages.py - AI Trade Diary (API + HTML page), moved out of api_server.py (NEXT-6h part 1).

GET /api/ai/diary and GET /diary. The page text _DIARY_HTML stays at module level, byte for byte (a normal move would
indent it and change the HTML). Part 2 (6h-2) adds the AI Coach routes + page to this file.
Same code, same paths, same order. api_server.py includes the router at the exact place the routes used to be.
"""
from fastapi import APIRouter

from api.swr import _swr


_DIARY_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OWL Trade Diary</title><style>
body{font-family:system-ui,sans-serif;margin:0;padding:12px;background:#f2f3f7;color:#14161c}
h1{font-size:18px;margin:4px 0 8px}.c{background:#fff;border-radius:12px;padding:12px;margin:0 0 10px;box-shadow:0 1px 3px #0001}
.g{color:#0a8f4f}.r{color:#d0273a}.m{color:#667}.s{font-size:12px}.b{font-weight:700}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}td,th{padding:3px 2px;text-align:right}td:first-child,th:first-child{text-align:left}
.w{background:#fff4e0;border-left:4px solid #e08a00}</style></head><body>
<h1>OWL Trade Diary</h1><div class="s m" id="t">load ho raha hai...</div><div id="h" class="c b"></div>
<div id="o"></div><div id="l"></div>
<script>
const P=v=>(v>=0?'+':'')+Number(v).toFixed(1)+'%',C=v=>v>0?'g':(v<0?'r':'m');
const T=ts=>{const d=new Date((ts+19800)*1000);return d.toISOString().slice(11,16)};
async function go(){try{const d=await (await fetch('/api/ai/diary')).json();
document.getElementById('t').textContent='Update: '+new Date().toLocaleTimeString()+' - har 30 sec me khud badalta hai';
document.getElementById('h').textContent=d.headline||'';
let o='';(d.open||[]).forEach(x=>{o+=`<div class="c ${x.alert.startsWith('Booking')?'w':''}"><span class="b">${x.sym} ${x.side=='BUY'?'LONG':'SHORT'}</span> <span class="${C(x.now)} b">${P(x.now)}</span> <span class="s m">peak ${P(x.peak)} | low ${P(x.low)} | ${T(x.opened)}</span>${x.alert?`<div class="s">${x.alert}</div>`:''}</div>`});
document.getElementById('o').innerHTML=o?'<div class="s m b">ABHI KHULE TRADE</div>'+o:'';
const K=Object.keys(d.names||{});let l='<div class="s m b">BAND TRADE (naye pehle)</div>';
(d.rows||[]).forEach(x=>{l+=`<div class="c"><span class="b">${x.sym} ${x.side=='BUY'?'LONG':'SHORT'}</span> <span class="${C(x.roi)} b">${P(x.roi)}</span> <span class="s m">${x.reason||''} | ${T(x.opened)} | peak ${P(x.peak)} @${x.peak_min}m | low ${P(x.low)}</span>
<div class="s">TP: ${x.tp.map((v,i)=>v?'TP'+(i+1)+' ok':'TP'+(i+1)+' -').join(' | ')}</div><div class="s" style="margin-top:4px">${x.lesson}</div>
<table><tr>${K.map(k=>`<th>${k}</th>`).join('')}</tr><tr>${K.map(k=>`<td class="${C(x.rules[k])}${k==x.best?' b':''}">${x.rules[k].toFixed(1)}</td>`).join('')}</tr></table>
<div class="s m">Data: SD ${x.has.sd?'ha':'collecting'} | EMA ${x.has.slope?'ha':'collecting'} | TSI/Z ${x.has.ind?'ha':'collecting'}</div></div>`});
document.getElementById('l').innerHTML=l;}catch(e){document.getElementById('t').textContent='Backend se connect nahi hua: '+e}}
go();setInterval(go,30000);
</script></body></html>"""


def make_router_diary():
    """Trade Diary: JSON (/api/ai/diary) and the phone-browser page (/diary)."""
    r = APIRouter()

    @r.get("/api/ai/diary")
    async def ai_diary_endpoint():
        """Per-trade diary (ai_observer.diary): what each bot trade did and what other exit rules would have given. Read-only."""
        from recovered_bot import ai_observer
        return await _swr("diary", 15.0, ai_observer.diary)


    @r.get("/diary")
    async def ai_diary_page():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_DIARY_HTML)

    return r
