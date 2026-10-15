# -*- coding: utf-8 -*-
"""
生成「BTC 期权五所比价」交互看板（单文件 HTML）。

· 点「更新数据」→ 浏览器直接抓 Gate / Bybit / OKX / Deribit（这四家给跨域头）
  Binance 不给跨域头，浏览器抓不到，需要用「扫描并更新看板.bat」刷新
· 抓取失败时回落到生成时嵌入的快照
· 两张表分开：① 两腿结算方式相同（干净） ② 跨结算（多一层敞口）

用法：
  python make_options_dashboard_btc.py
  python make_options_dashboard_btc.py --src <json> --out <dir>
"""

import argparse
import datetime
import json
import os

DEFAULT_SRC = r'.\X监控\数据\options_arb_btc.json'
DEFAULT_OUT = r'.\X监控\看板'
FILENAME = 'BTC期权比价看板.html'

VENUE_COVERAGE = [
    ('Gate',        'gate.io',     'BTC_USDT',    True,  '已接入', 'USDT 结算（Linear）'),
    ('Bybit',       'bybit.com',   'BTC-…-USDT',  True,  '已接入', 'USDT 结算（Linear）'),
    ('Binance',     'binance.com', 'BTC-YYMMDD',  True,  '仅脚本', 'USDT 结算；浏览器抓不到（无跨域头）'),
    ('OKX (USD)',   'okx.com',     'BTC-USD',     True,  '已接入', '币本位结算（Inverse）'),
    ('OKX (USD_UM)','okx.com',     'BTC-USD_UM',  True,  '已接入', 'USDT 结算（Linear）'),
    ('Deribit',     'deribit.com', 'BTC-…',       True,  '已接入', '币本位结算（Inverse）'),
    ('Deribit USDC','deribit.com', 'BTC_USDC-…',  True,  '已接入', 'USDC 结算（Linear）'),
]

JS = r"""
const SNAP = __SNAPSHOT__;
const FEES = {gate:0.0003, bybit:0.0003, binance:0.0002, okx:0.0002,
              okx_um:0.0002, deribit:0.0003, deribit_usdc:0.0003};
const LINEAR = {gate:true, bybit:true, binance:true, okx_um:true,
                deribit_usdc:true, okx:false, deribit:false};
const MON = {JAN:1,FEB:2,MAR:3,APR:4,MAY:5,JUN:6,JUL:7,AUG:8,SEP:9,OCT:10,NOV:11,DEC:12};
const UAHEAD = {'Accept':'application/json'};

function K(iso, strike, kind){ return iso+'|'+(+strike)+'|'+kind; }
function isoFromYmd(s){ return s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8); }
function isoFromDmy(s){ return '20'+s.slice(5,7)+'-'+String(MON[s.slice(2,5).toUpperCase()]).padStart(2,'0')+'-'+s.slice(0,2); }

async function jget(url){ const r=await fetch(url,{headers:UAHEAD}); if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); }

async function loadGate(){
  const list = await jget('https://api.gateio.ws/api/v4/options/contracts?underlying=BTC_USDT');
  const out={}; let idx=0;
  for(const c of list){
    const p=c.name.split('-'); if(p.length<4) continue;
    out[K(isoFromYmd(p[1]), p[2], p[3])]={bid:+c.bid1_price||0, ask:+c.ask1_price||0};
    idx = idx || +c.underlying_price || 0;
  }
  return {out, idx};
}

async function loadBybit(){
  const j = await jget('https://api.bybit.com/v5/market/tickers?category=option&baseCoin=BTC');
  const list=(j.result&&j.result.list)||[]; const out={}; let idx=0;
  for(const c of list){
    const p=c.symbol.split('-'); if(p.length<4) continue;
    out[K(isoFromDmy(p[1]), p[2], p[3])]={bid:+c.bid1Price||0, ask:+c.ask1Price||0};
    idx = idx || +c.indexPrice || 0;
  }
  return {out, idx};
}

async function loadOkx(){
  const j = await jget('https://www.okx.com/api/v5/market/tickers?instType=OPTION&uly=BTC-USD');
  const list=j.data||[]; const inv={}, um={};
  for(const c of list){
    const p=c.instId.split('-'); if(p.length<5) continue;
    const key=K(isoFromYmd(p[2]), p[3], p[4]);
    const q={bid:+c.bidPx||0, ask:+c.askPx||0};
    if(p[1]==='USD') inv[key]=q; else if(p[1]==='USD_UM') um[key]=q;
  }
  return {inv, um};
}

async function loadDeribit(){
  const a = await jget('https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option');
  let b={result:[]};
  try { b = await jget('https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC_USDC&kind=option'); } catch(e){}
  const inv={}, usdc={}; let idx=0;
  const eat=(list, target)=>{
    for(const c of list){
      const nm=c.instrument_name||''; const p=nm.split('-');
      const fam=p[0];
      if(fam!=='BTC' && fam!=='BTC_USDC') continue;
      const key=K(isoFromDmy(p[1]), p[2], p[3]);
      (fam==='BTC'?inv:usdc)[key]={bid:+c.bid_price||0, ask:+c.ask_price||0};
      idx = idx || +c.underlying_price || 0;
    }
  };
  eat(a.result||[], 'inv'); eat(b.result||[], 'usdc');
  return {inv, usdc, idx};
}

function daysTo(iso){ const d=(new Date(iso+'T08:00:00Z')-new Date())/86400000; return Math.max(Math.ceil(d),1); }

function build(books, idx){
  // books: {venue: {key:{bid,ask}}}
  const all={};
  for(const v in books){
    const mult = LINEAR[v] ? 1 : idx;
    for(const k in books[v]){
      (all[k]=all[k]||{})[v] = {bid: books[v][k].bid*mult, ask: books[v][k].ask*mult};
    }
  }
  const rows=[];
  for(const k in all){
    const per=all[k], parts=k.split('|'); const iso=parts[0], label='BTC '+iso+' '+(+parts[1])+' '+parts[2];
    const live={}; for(const v in per){ if(per[v].bid>0 && per[v].ask>0) live[v]=per[v]; }
    const vs=Object.keys(live); if(vs.length<2) continue;
    const days=daysTo(iso); const base=idx/77000;
    for(const b of vs) for(const s of vs){
      if(b===s) continue;
      const buy=live[b].ask, sell=live[s].bid;
      const fee=(FEES[b]+FEES[s])*idx/ (77000/77000);
      const net=sell-buy-fee;
      rows.push({contract:label, buy_at:b, sell_at:s, buy:+buy.toFixed(2), sell:+sell.toFixed(2),
                 gross:+(sell-buy).toFixed(2), fee:+((FEES[b]+FEES[s])*idx).toFixed(2),
                 net:+net.toFixed(2), days:days, mixed:(LINEAR[b]!==LINEAR[s])});
    }
  }
  rows.sort((a,b)=>b.net-a.net);
  return rows;
}

function renderRows(tbody, rows, top){
  if(!rows.length){ tbody.innerHTML='<tr><td colspan="14" class="empty">无</td></tr>'; return; }
  tbody.innerHTML = rows.slice(0, top||80).map(r=>{
    const cls = r.net>0?'pos':(r.net<0?'neg':'');
    const money = (r.moneyness_pct>0?'实值':'虚值')+Math.abs(r.moneyness_pct||0).toFixed(0)+'%';
    const guess = r.mult_guess ? ' *' : '';
    const pc = (r.per_contract!=null) ? r.per_contract.toFixed(2)+guess : '—';
    const apr = (r.apr!=null) ? r.apr.toFixed(0)+'%' : '—';
    const us = (r.usable_btc!=null) ? r.usable_btc.toFixed(2)+' BTC' : '未知';
    const real = (r.real_profit!=null) ? r.real_profit.toFixed(2) : '—';
    return '<tr class="'+cls+'">'
      +'<td class="c">'+r.contract+'</td><td class="c">'+r.buy_at+' → '+r.sell_at+'</td>'
      +'<td class="n">'+(+r.buy).toFixed(2)+'</td><td class="n">'+(+r.sell).toFixed(2)+'</td>'
      +'<td class="n">'+(+r.gross).toFixed(2)+'</td><td class="n">'+(+r.fee).toFixed(2)+'</td>'
      +'<td class="n strong">'+(+r.net).toFixed(2)+'</td>'
      +'<td class="n">'+pc+'</td><td class="c">'+money+'</td>'
      +'<td class="c">'+r.days+'</td><td class="n">'+apr+'</td>'
      +'<td class="n">'+us+'</td><td class="n strong">'+real+'</td>'
      +'<td class="c">'+(r.mixed?'✱':'')+'</td></tr>';
  }).join('');
}

let RAWR = [];
let LASTMETA = ['', '', ''];

function filtered(rows){
  const n = document.getElementById('fNear'), i = document.getElementById('fItm');
  const near = n && n.checked, hideItm = i && i.checked;
  return rows.filter(r=>{
    if(near && r.days>45) return false;
    if(hideItm && r.moneyness_pct>0) return false;
    return true;
  });
}

function paint(rows, label, msg, cls){
  RAWR = rows; LASTMETA = [label, msg, cls||''];
  const view = filtered(rows);
  const pos=view.filter(r=>r.net>0), same=pos.filter(r=>!r.mixed), mixed=pos.filter(r=>r.mixed);
  document.getElementById('when').textContent = label;
  document.getElementById('npair').textContent = new Set(view.map(r=>r.contract)).size;
  document.getElementById('nall').textContent = pos.length;
  document.getElementById('nsame').textContent = same.length;
  const best = pos.length? pos[0]: view[0];
  const bv=document.getElementById('best');
  bv.textContent = best? (best.net>0?'+':'')+(+best.net).toFixed(2) : '—';
  bv.style.color = (best&&best.net>0)?'var(--pos)':'var(--neg)';
  renderRows(document.getElementById('tb1'), same);
  renderRows(document.getElementById('tb2'), mixed);
  const m=document.getElementById('msg'); m.className='msg '+(cls||''); m.textContent=msg||'';
}

function repaint(){ paint(RAWR, LASTMETA[0], LASTMETA[1], LASTMETA[2]); }

async function update(){
  const btn=document.getElementById('upd'); btn.disabled=true; btn.textContent='抓取中…';
  document.getElementById('msg').textContent='正在请求 Gate / Bybit / OKX / Deribit …';
  const errs=[], books={}; let idx=0;
  try{ const g=await loadGate(); books.gate=g.out; idx=idx||g.idx; }catch(e){ errs.push('Gate'); }
  try{ const b=await loadBybit(); books.bybit=b.out; idx=idx||b.idx; }catch(e){ errs.push('Bybit'); }
  try{ const o=await loadOkx(); books.okx=o.inv; books.okx_um=o.um; }catch(e){ errs.push('OKX'); }
  try{ const d=await loadDeribit(); books.deribit=d.inv; books.deribit_usdc=d.usdc; idx=idx||d.idx; }catch(e){ errs.push('Deribit'); }
  const got=Object.keys(books).length;
  if(got>=2){
    idx = idx || SNAP.index || 77000;
    const rows=build(books, idx);
    document.getElementById('idx').textContent=idx.toFixed(2);
    paint(rows, new Date().toLocaleString('zh-CN')+'（浏览器实时抓取）',
          (errs.length? ('未取到：'+errs.join('/')+'（浏览器跨域限制，可用 bat 完整刷新）。'):'数据已更新。')
          + ' 注意：完整含 Binance 的榜单请用「扫描并更新看板.bat」。', errs.length?'warn':'ok');
  } else {
    paint(SNAP.rows, '抓取失败，显示快照', '浏览器抓不到任何一家（可能是跨域或网络限制）。请用「扫描并更新看板.bat」刷新。', 'warn');
  }
  btn.disabled=false; btn.textContent='更新数据';
}

document.getElementById('upd').addEventListener('click', update);
['fNear','fItm'].forEach(function(id){
  var e=document.getElementById(id);
  if(e) e.addEventListener('change', repaint);
});

function paintSnapshot(){
  const rows=(SNAP.rows||[]);
  document.getElementById('idx').textContent=(SNAP.index||0).toFixed(2);
  paint(rows, '快照（点右上角「更新数据」抓最新）', '快照数据由本地脚本抓取（含 Binance）。', '');
}
paintSnapshot();
"""

CSS = r"""
:root{--bg:#f5f6f8;--card:#fff;--ink:#1c1f23;--sub:#6b7280;--line:#e6e8ec;
      --pos:#128a5b;--neg:#c0392b;--accent:#f7931a;}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.55 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
.wrap{max-width:1220px;margin:0 auto;padding:26px 20px 60px;}
.top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;flex-wrap:wrap;}
h1{font-size:23px;margin:0 0 6px;letter-spacing:.3px;}
.meta{color:var(--sub);font-size:13.5px;}
#upd{background:var(--accent);color:#fff;border:0;border-radius:10px;padding:11px 22px;
     font-size:15px;font-weight:600;cursor:pointer;box-shadow:0 2px 8px rgba(247,147,26,.3);white-space:nowrap;}
#upd:hover{filter:brightness(1.06);} #upd:disabled{opacity:.6;cursor:default;}
.msg{margin:14px 0 0;font-size:13.5px;min-height:20px;color:var(--sub);}
.msg.ok{color:var(--pos);} .msg.warn{color:#a8620a;}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:14px;margin:18px 0 22px;}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:15px 17px;}
.card .k{color:var(--sub);font-size:12.5px;margin-bottom:7px;}
.card .v{font-size:22px;font-weight:650;}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-bottom:22px;}
.panel h2{font-size:15px;margin:0;padding:13px 18px;border-bottom:1px solid var(--line);font-weight:600;}
.panel .hint{padding:9px 18px;font-size:12.5px;color:var(--sub);background:#fafbfc;border-bottom:1px solid var(--line);}
table{width:100%;border-collapse:collapse;font-size:13.5px;}
th,td{padding:8px 11px;border-bottom:1px solid var(--line);white-space:nowrap;}
th{background:#fafbfc;color:var(--sub);font-weight:600;text-align:right;position:sticky;top:0;}
th:first-child,th:nth-child(2),th:nth-child(8),th:nth-child(9){text-align:center;}
td.c{text-align:center;} td.n{text-align:right;font-variant-numeric:tabular-nums;}
td.strong{font-weight:700;} tr.pos td.strong{color:var(--pos);} tr.neg td.strong{color:var(--neg);}
tr:hover td{background:#fafcff;} td.empty{text-align:center;color:var(--sub);padding:22px;}
.vt td{font-size:13px;}
.note{margin-top:6px;background:#fffdf3;border:1px solid #f0e6c0;border-radius:12px;padding:15px 18px;
      font-size:13.5px;color:#5c4b17;} .note b{color:#3f3305;} .note ul{margin:8px 0 0;padding-left:18px;}
footer{margin-top:24px;color:var(--sub);font-size:12.5px;}
"""


def build_html(snapshot):
    vr = []
    for name, dom, ins, ok, st, note in VENUE_COVERAGE:
        vr.append(f'<tr><td>{name}</td><td>{dom}</td><td>{ins}</td>'
                  f'<td class="{"yes" if ok else "no"}">{"有" if ok else "无"}</td>'
                  f'<td>{st}</td><td>{note}</td></tr>')
    venue_html = '\n'.join(vr)
    snap_json = json.dumps(snapshot, ensure_ascii=False)
    js = JS.replace('__SNAPSHOT__', snap_json)
    when = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BTC 期权五所比价 · 看板</title><style>{CSS}</style></head>
<body><div class="wrap">
  <div class="top">
    <div><h1>BTC 期权 · 五所跨所比价看板</h1>
      <div class="meta">数据时间：<span id="when">—</span>　|　指数价：<span id="idx">—</span> USDT</div></div>
    <button id="upd">更新数据</button>
  </div>
  <div class="msg" id="msg"></div>

  <div class="cards">
    <div class="card"><div class="k">可比合约（已过滤）</div><div class="v" id="npair">—</div></div>
    <div class="card"><div class="k">净价差&gt;0 合计</div><div class="v" id="nall">—</div></div>
    <div class="card"><div class="k">其中：两腿结算相同</div><div class="v" id="nsame">—</div></div>
    <div class="card"><div class="k">当前最佳净价差</div><div class="v" id="best">—</div></div>
  </div>

  <div class="panel"><h2>市场覆盖（BTC 期权）</h2>
    <table class="vt"><thead><tr><th>交易所</th><th>域名</th><th>期权标识</th>
      <th>是否有</th><th>接入</th><th>说明</th></tr></thead><tbody>
{venue_html}
    </tbody></table></div>

  <div class="panel"><h2>① 两腿结算方式相同（干净，可执行）</h2>
    <div class="hint">两边都是 USDT 计价，或都是币本位计价。这类没有额外的币种敞口。
      <label style="margin-left:14px"><input type="checkbox" id="fNear"> 只看近月 ≤45 天</label>
      <label style="margin-left:14px"><input type="checkbox" id="fItm"> 隐藏实值</label>
      <b style="margin-left:14px;color:#c0392b">直接看最后一列「实赚」——那才是真能到手的钱</b>
    </div>
    <table><thead><tr><th>合约</th><th>方向</th><th>买价</th><th>卖价</th><th>毛利</th>
      <th>费用</th><th>净价差</th><th>每张花</th><th>实值率</th><th>剩余天数</th><th>年化</th><th>可成交</th><th>实赚</th><th>跨结算</th></tr></thead>
      <tbody id="tb1"><tr><td colspan="14" class="empty">加载中…</td></tr></tbody></table></div>

  <div class="panel"><h2>② 跨结算方式（✱＝两腿一腿币本位一腿 USDT，多一层敞口）</h2>
    <div class="hint">这一栏的数字看着更大，但两条腿的结算币种不同，收益并不真的锁死。</div>
    <table><thead><tr><th>合约</th><th>方向</th><th>买价</th><th>卖价</th><th>毛利</th>
      <th>费用</th><th>净价差</th><th>每张花</th><th>实值率</th><th>剩余天数</th><th>年化</th><th>可成交</th><th>实赚</th><th>跨结算</th></tr></thead>
      <tbody id="tb2"><tr><td colspan="14" class="empty">加载中…</td></tr></tbody></table></div>

  <div class="note"><b>口径说明（先读这个）</b>
    <ul>
      <li>单位统一为 <b>USDT / 1 BTC 的权利金</b>。<b>「每张花」</b>才是买入腿一张实际要付的 USDT（1 张 = Gate/OKX/Bybit/Binance 0.01 BTC，Deribit 1 BTC；带 * 的是推定值）。</li>
      <li><b>年化 = 净利润 ÷ 买入腿权利金 × 365 ÷ 剩余天数</b>（行业工具常用口径，不是保证金口径）。</li>
      <li><b>「可成交」= 买腿的卖单量 ∩ 卖腿的买单量</b>（取小），单位 BTC；任一边取不到就显示“未知”。</li>
      <li><b>「实赚」= 净价差 × 可成交 BTC 量</b>——这才算真实能到手的钱。净价差可能是几百，但量只有 0.01 BTC 时，实赚就是几毛钱。</li>
      <li><b>已剔除</b>：偏离现价 >25% 的深度实/虚值、剩余 >120 天的远月——那类价差多来自报价陈旧。</li>
      <li>同一张合约 = 同到期日 + 同行权价 + 同类型。</li>
      <li>费用按「费率 × 指数价」估算：Gate/Bybit/Deribit 0.03%，Binance/OKX 0.02%。</li>
      <li><b>未计入</b>：滑点、两腿成交时差、保证金占用、跨所转账。<b>也没核成交量</b>——远月挂单可能没有成交，报价是虚的。</li>
      <li>远月合约（剩余天数大）的价差往往来自<b>报价陈旧</b>，不是真的机会。</li>
    </ul>
  </div>
  <footer>看板生成时间：{when}　·　数据来源：Gate / Bybit / Binance / OKX / Deribit 公开行情接口</footer>
</div>
<script>{js}</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=DEFAULT_SRC)
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()

    snapshot = {'rows': [], 'index': 0}
    if os.path.exists(args.src):
        with open(args.src, encoding='utf-8') as f:
            snapshot = json.load(f)

    html = build_html(snapshot)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, FILENAME)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    print('已生成:', path)
    print('大小: %.1f KB' % (len(html.encode('utf-8')) / 1024))
    print('快照行数:', len(snapshot.get('rows') or []))


if __name__ == '__main__':
    main()
