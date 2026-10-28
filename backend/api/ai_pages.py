"""api/ai_pages.py - AI Trade Diary (API + HTML page), moved out of api_server.py (NEXT-6h part 1).

GET /api/ai/diary and GET /diary. The page text _DIARY_HTML stays at module level, byte for byte (a normal move would
indent it and change the HTML). 6h-2 added the AI Coach routes + page (_COACH_HTML, also byte for byte) to this file.
Same code, same paths, same order. api_server.py includes the router at the exact place the routes used to be.
"""
import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException

from api.swr import _swr, _SWR


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


_COACH_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OWL AI Coach</title><style>
body{font-family:system-ui,sans-serif;margin:0;padding:12px;background:#f2f3f7;color:#14161c}
h1{font-size:18px;margin:4px 0 8px}h2{font-size:13px;margin:14px 0 6px;color:#667}.c{background:#fff;border-radius:12px;padding:12px;margin:0 0 8px;box-shadow:0 1px 3px #0001}
.g{color:#0a8f4f}.r{color:#d0273a}.m{color:#667}.s{font-size:12px}.b{font-weight:700}.big{font-size:22px;font-weight:800}
.row{display:flex;justify-content:space-between;gap:8px}.col{flex:1}.w{background:#fff4e0;border-left:4px solid #e08a00}
.pill{display:inline-block;font-size:11px;padding:1px 6px;border-radius:8px;background:#eef;margin:1px}.pw{background:#dff5e8}.pa{background:#fde3e6}
</style></head><body><h1>OWL AI Coach</h1><div class="s m" id="t">load ho raha hai...</div>
<div id="cmp" class="c"></div><h2>AI KE ABHI KHULE TRADE</h2><div id="op"></div>
<h2>AI NE KHUD KYA DHUNDHA (indicators ke combos)</h2><div id="tb" class="c"></div>
<h2>MEMO (kab kya hua)</h2><div id="me" class="c"></div><h2>BAND TRADE: AI vs BOT</h2><div id="cl"></div>
<script>
const P=v=>(v>=0?'+':'')+Number(v).toFixed(1)+'%',U=v=>(v>=0?'+':'')+Number(v).toFixed(2),C=v=>v>0?'g':(v<0?'r':'m');
const T=ts=>{const d=new Date((ts+19800)*1000);return d.toISOString().slice(11,16)};
const pill=(k,v)=>`<span class="pill ${v=='WITH'?'pw':'pa'}">${k} ${v=='WITH'?'saath':'khilaf'}</span>`;
async function go(){try{const d=await (await fetch('/api/ai/coach')).json();
document.getElementById('t').textContent='Update: '+new Date().toLocaleTimeString()+' - har 30 sec me khud badalta hai';
const c=d.compare;
document.getElementById('cmp').innerHTML=c.n==0?`<div class="b">DATA JAMA HO RAHA HAI 0/${d.min_n}</div><div class="s m">AI ke ${c.open} trade khule hain. Pehle trade band hone par yahan AI vs Bot dikhega.</div>`:
`<div class="row"><div class="col"><div class="s m">AI (khud manage)</div><div class="big ${C(c.ai_pnl)}">${U(c.ai_pnl)}</div><div class="s m">jeet ${c.ai_wins}/${c.n}</div></div>
<div class="col"><div class="s m">BOT akela</div><div class="big ${C(c.bot_pnl)}">${U(c.bot_pnl)}</div><div class="s m">jeet ${c.bot_wins}/${c.n}</div></div></div>
<div class="s m" style="margin-top:6px">USDT, ${c.n} same signal par. ${c.ready?'':'<b>JAMA HO RAHA HAI '+c.n+'/'+d.min_n+' - abhi verdict nahi.</b>'} Sideways (30+ min, kuch nahi mila): ${d.sideways.n} trade${d.sideways.n?', avg '+d.sideways.avg_min+' min':''}.</div>`;
const M=d.margin;document.getElementById('cmp').innerHTML+=`<div class="s m" style="margin-top:8px">MARGIN: balance ${M.balance}${M.custom?'':' (default 20 trade)'} | har trade ${M.per_trade} | free ${M.free} | ${M.open}/${M.slots} slot | skip ${M.skipped} | jagah banane ke liye band ${M.freed}</div>`;
document.getElementById('op').innerHTML=(d.open.length?'':'<div class="c s m">Abhi koi AI trade khula nahi.</div>')+d.open.map(x=>`<div class="c"><span class="b">${x.sym} ${x.side=='BUY'?'LONG':'SHORT'}</span> <span class="b ${C(x.roi)}">${P(x.roi)}</span> <span class="s m">peak ${P(x.peak)} | TP${x.hit||'-'} | ${x.min} min${x.be?' | SL entry par':''}</span>
<div>${(x.facts||[]).map(f=>`<span class="pill">${f}</span>`).join('')||'<span class="s m">indicator: pehli closed candle ka wait</span>'}</div></div>`).join('');
const L=d.learned,row=(x,cl)=>`<div class="row s"><span>${x.text}</span><span class="${cl}">${x.p}% (${x.n})</span></div>`;
document.getElementById('tb').innerHTML=`<div class="s m">${L.samples} candle samples | normal: ${L.base}% baar trade ke saath | ${L.trusted} situation ke ${L.min_n}+ cases</div>`+
(L.best.length?'<div class="b s g" style="margin-top:6px">TRADE KE SAATH JAATE HAIN</div>'+L.best.map(x=>row(x,'g')).join(''):'')+
(L.worst.length?'<div class="b s r" style="margin-top:6px">PHIR PALAT JAATE HAIN</div>'+L.worst.map(x=>row(x,'r')).join(''):'')+
(L.best.length+L.worst.length?'':'<div class="s b" style="margin-top:6px">JAMA HO RAHA HAI - abhi koi situation '+L.min_n+' cases tak nahi pahunchi</div>');
document.getElementById('me').innerHTML=d.memo.map(x=>`<div class="s"><span class="m">${T(x.t)}</span> ${x.text}</div>`).join('')||'<div class="s m">Abhi memo khali.</div>';
document.getElementById('cl').innerHTML=d.closed.map(x=>`<div class="c"><span class="b">${x.sym} ${x.side=='BUY'?'LONG':'SHORT'}</span> AI <span class="b ${C(x.roi)}">${P(x.roi)}</span> | Bot ${x.bot_roi===null?'<span class="m">abhi khula</span>':'<span class="b '+C(x.bot_roi)+'">'+P(x.bot_roi)+'</span>'} <span class="s m">| peak ${P(x.peak)} | ${T(x.t0)}</span>
<div class="s">${x.reason}${x.mode&&x.mode!='-'?' ['+x.mode+']':''}</div>${x.after?'<div class="s m">'+x.after+'</div>':'<div class="s m">band ke baad price dekh raha hai...</div>'}</div>`).join('');
}catch(e){document.getElementById('t').textContent='Backend se connect nahi hua: '+e}}
go();setInterval(go,30000);
</script></body></html>"""


def make_router_coach(require_api_token):
    """AI Coach: JSON (/api/ai/coach, reset, plan/config, coach/config) and the phone-browser page (/coach). require_api_token is api_server's own (passed in)."""
    r = APIRouter()

    @r.get("/api/ai/coach")
    async def ai_coach_endpoint():
        """AI Coach: AI-managed virtual trades vs the bot on the same signals, learned indicator probabilities, memo (ai_coach.py).
        The answer carries "data_info": how old it is, whether the build is stuck and why, so the app can show the real cause."""
        from recovered_bot import ai_coach
        v = ai_coach.view()                     # ready answer from the coach's own 2 s thread: instant, never stale because of a busy pool
        info = ai_coach.view_info()
        if v is not None:
            if not info["stuck"]:
                return dict(v, data_info=info)
            # the coach thread is stuck: try ONE fresh build in the shared pool (max 8 s), else show the old answer + the reason
            try:
                fresh = await asyncio.wait_for(_swr("coach", 5.0, ai_coach.build), timeout=8.0)
                return dict(fresh, data_info=dict(info, fresh_build=True))
            except Exception:
                return dict(v, data_info=info)
        try:                                                 # only until the first build has finished after start-up
            out = await asyncio.wait_for(_swr("coach", 5.0, ai_coach.build), timeout=7.0)
        except Exception:                                    # still building: say so at once (the app retries by itself)
            return {"building": True, "pairs": [], "data_info": dict(info, building=True), "ts": time.time()}
        return dict(out, data_info=info) if isinstance(out, dict) else out


    @r.post("/api/ai/coach/reset")
    async def ai_coach_reset(_auth=Depends(require_api_token)):
        from recovered_bot import ai_coach
        _SWR.pop("coach", None)
        return await asyncio.to_thread(ai_coach.reset)


    @r.post("/api/ai/plan/config")
    async def ai_plan_config(payload: dict, _auth=Depends(require_api_token)):
        """The AI's day plan (paper only): target, loss cap, max open trades, give-back %. 0 = off."""
        from recovered_bot import ai_planner
        try:
            kw = {k: payload.get(k) for k in ("target_usdt", "loss_cap_usdt", "max_open", "giveback_pct") if payload.get(k) is not None}
            for k, v in kw.items():
                float(v)
        except Exception:
            raise HTTPException(status_code=400, detail="values must be numbers")
        _SWR.pop("coach", None)
        return await asyncio.to_thread(lambda: ai_planner.set_config(**kw))


    @r.post("/api/ai/coach/config")
    async def ai_coach_config(payload: dict, _auth=Depends(require_api_token)):
        """Virtual balance (USDT) the AI Coach manages margin with. 0 / empty = default (20 trades' margin)."""
        from recovered_bot import ai_coach
        try:
            bal = float(payload.get("balance") or 0)
        except Exception:
            raise HTTPException(status_code=400, detail="balance must be a number")
        _SWR.pop("coach", None)
        return await asyncio.to_thread(ai_coach.set_balance, bal)


    @r.get("/coach")
    async def ai_coach_page():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_COACH_HTML)

    r.ai_coach_endpoint = ai_coach_endpoint   # api_server._swr_prewarm calls this handler directly (start-up warm-up)
    return r
