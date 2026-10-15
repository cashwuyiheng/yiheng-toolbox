# -*- coding: utf-8 -*-
"""
生成「HYPE 期权跨所比价」交互看板（单文件 HTML）。

特点：
  · 点「更新」按钮 → 浏览器直接抓 Gate / Bybit 行情 → 即时重算 → 重画表格
  · 不需要 Python、不需要服务器；拷到 U 盘插哪都能用
  · 抓取失败时回落到生成时嵌入的快照（页面照常可看）
  · 「市场覆盖」面板如实标出：谁上架了 HYPE 期权、谁没有

用法：
    python make_options_dashboard.py
    python make_options_dashboard.py --src <json> --out <dir>
"""

import argparse
import datetime
import json
import os

DEFAULT_SRC = r'.\X监控\数据\options_arb_hype.json'
DEFAULT_OUT = r'.\X监控\看板'
FILENAME = 'HYPE期权比价看板.html'

# 市场覆盖情况（经 2026-09-17 实测）
VENUE_COVERAGE = [
    ('Gate',    'gate.io',       True,  '已接入报价',  'HYPE_USDT 期权，232 张'),
    ('Bybit',   'bybit.com',     True,  '已接入报价',  'HYPE 期权，280 张'),
    ('Aevo',    'aevo.xyz',      True,  '未接入报价',  'HYPE 期权，报价接口不稳定'),
    ('Derive',  'derive.xyz',    True,  '未接入报价',  '有合约，但走 RFQ 询价，无公开盘口'),
    ('Binance', 'binance.com',   False, '—',          '期权标的不含 HYPE'),
    ('OKX',     'okx.com',       False, '—',          '期权标的不含 HYPE'),
    ('Deribit', 'deribit.com',   False, '—',          '期权标的不含 HYPE'),
]

JS = r"""
const SNAPSHOT = __SNAPSHOT__;
const FEE = { gate: 0.0005, bybit: 0.0003 };   // taker，按名义价计
const MONTHS = {JAN:1,FEB:2,MAR:3,APR:4,MAY:5,JUN:6,JUL:7,AUG:8,SEP:9,OCT:10,NOV:11,DEC:12};

function expToISO(sym) {           // 30OCT26 -> 2026-10-30
  const dd = sym.slice(0,2), mon = sym.slice(2,5).toUpperCase(), yy = sym.slice(5,7);
  const m = MONTHS[mon];
  if (!m) return null;
  return (2000 + parseInt(yy,10)) + '-' + String(m).padStart(2,'0') + '-' + dd;
}

async function fetchGate() {
  const r = await fetch('https://api.gateio.ws/api/v4/options/contracts?underlying=HYPE_USDT');
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const list = await r.json();
  const out = {};
  for (const c of list) {
    const p = c.name.split('-');               // HYPE_USDT-20261002-110-P
    if (p.length < 4) continue;
    const ymd = p[1];
    const key = ymd.slice(0,4)+'-'+ymd.slice(4,6)+'-'+ymd.slice(6,8)+'|'+parseFloat(p[2])+'|'+p[3];
    out[key] = { bid:+c.bid1_price||0, ask:+c.ask1_price||0, bid_sz:+c.bid1_size||0, ask_sz:+c.ask1_size||0 };
  }
  return { keys: out, n: list.length, name: 'Gate' };
}

async function fetchBybit() {
  const r = await fetch('https://api.bybit.com/v5/market/tickers?category=option&baseCoin=HYPE');
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const j = await r.json();
  const list = (j.result && j.result.list) || [];
  const out = {};
  let index = 0;
  for (const c of list) {
    const p = c.symbol.split('-');             // HYPE-30OCT26-78-P-USDT
    if (p.length < 4) continue;
    const iso = expToISO(p[1]);
    if (!iso) continue;
    const key = iso+'|'+parseFloat(p[2])+'|'+p[3];
    out[key] = { bid:+c.bid1Price||0, ask:+c.ask1Price||0, bid_sz:+c.bid1Size||0, ask_sz:+c.ask1Size||0 };
    if (!index && +c.indexPrice) index = +c.indexPrice;
  }
  return { keys: out, n: list.length, name: 'Bybit', index: index };
}

function daysTo(iso) {
  const d = (new Date(iso + 'T08:00:00Z') - new Date()) / 86400000;
  return Math.max(Math.ceil(d), 1);
}

const MULT = { gate: 1.0, bybit: 1.0 };   // 1 张 = 1 HYPE（Gate 接口已确认；Bybit 为估）

function compute(gate, bybit, index) {
  const rows = [];
  const common = Object.keys(gate.keys).filter(k => k in bybit.keys);
  for (const key of common) {
    const g = gate.keys[key], b = bybit.keys[key];
    const parts = key.split('|');
    const label = 'HYPE ' + parts[0] + ' ' + (+parts[1]) + ' ' + parts[2];
    const strike = +parts[1];
    const fee = (FEE.gate + FEE.bybit) * index;
    const days = daysTo(parts[0]);
    const moneyness = (parts[2] === 'C' ? (index - strike) : (strike - index)) / index * 100;
    const legs = [];
    if (g.ask > 0 && b.bid > 0) legs.push(['gate→bybit', g.ask, b.bid, g.ask_sz, b.bid_sz, 'gate']);
    if (b.ask > 0 && g.bid > 0) legs.push(['bybit→gate', b.ask, g.bid, b.ask_sz, g.bid_sz, 'bybit']);
    for (const [dir, buy, sell, buy_sz, sell_sz, bven] of legs) {
      const gross = sell - buy, net = gross - fee;
      let usable = null, real = null;
      if (buy_sz > 0 && sell_sz > 0) {
        usable = Math.min(buy_sz * MULT[bven], sell_sz * MULT[dir === 'gate→bybit' ? 'bybit' : 'gate']);
        real = +(net * usable).toFixed(4);
      }
      rows.push({
        contract: label, direction: dir,
        buy: +buy.toFixed(4), sell: +sell.toFixed(4),
        gross: +gross.toFixed(4), fee: +fee.toFixed(4), net: +net.toFixed(4),
        days: days, apr: +(net / buy * (365 / days) * 100).toFixed(1),
        moneyness_pct: +moneyness.toFixed(1),
        per_contract: +(buy * MULT[bven]).toFixed(4),
        mult_guess: bven === 'bybit',
        usable: usable === null ? null : +usable.toFixed(2),
        real: real
      });
    }
  }
  rows.sort((a, b) => b.net - a.net);
  return { rows, common: common.length };
}

function fmt(x, n) { return (+x).toFixed(n); }

function render(data, srcLabel, errs, silent) {
  const rows = data.rows || [], index = data.index || SNAPSHOT.index || 0;
  const pos = rows.filter(r => r.net > 0);
  const best = rows.length ? rows[0] : null;

  document.getElementById('when').textContent = srcLabel;
  document.getElementById('idx').textContent = index ? fmt(index, 2) : '—';
  document.getElementById('npair').textContent = rows.length;
  document.getElementById('nhit').innerHTML = pos.length
    ? '<span class="pill pos-pill">' + pos.length + ' 条</span>'
    : '<span class="pill zero-pill">0 条</span>';
  const bv = document.getElementById('best');
  bv.textContent = best ? (best.net > 0 ? '+' : '') + fmt(best.net, 4) : '—';
  bv.style.color = (best && best.net > 0) ? 'var(--pos)' : 'var(--neg)';

  const tb = document.getElementById('tb');
  if (!rows.length) {
    tb.innerHTML = '<tr><td colspan="12" class="empty">没有可比对的合约</td></tr>';
  } else {
    tb.innerHTML = rows.map(r => {
      const cls = r.net > 0 ? 'pos' : (r.net < 0 ? 'neg' : '');
      const money = r.moneyness_pct != null
        ? ((r.moneyness_pct > 0 ? '实值' : '虚值') + Math.abs(r.moneyness_pct).toFixed(0) + '%') : '—';
      const guess = r.mult_guess ? ' *' : '';
      const pc = (r.per_contract != null) ? fmt(r.per_contract, 3) + guess : '—';
      const us = (r.usable != null) ? fmt(r.usable, 1) + ' HYPE' : '未知';
      const real = (r.real != null) ? fmt(r.real, 2) : '—';
      return '<tr class="' + cls + '">'
        + '<td class="c">' + r.contract + '</td>'
        + '<td class="c">' + r.direction + '</td>'
        + '<td class="n">' + fmt(r.buy, 3) + '</td>'
        + '<td class="n">' + fmt(r.sell, 3) + '</td>'
        + '<td class="n">' + fmt(r.gross, 3) + '</td>'
        + '<td class="n">' + fmt(r.fee, 4) + '</td>'
        + '<td class="n strong">' + fmt(r.net, 4) + '</td>'
        + '<td class="n">' + pc + '</td>'
        + '<td class="c">' + money + '</td>'
        + '<td class="c">' + r.days + '</td>'
        + '<td class="n">' + r.apr + '%</td>'
        + '<td class="n">' + us + '</td>'
        + '<td class="n strong">' + real + '</td>'
        + '</tr>';
    }).join('');
  }
  const msg = document.getElementById('msg');
  if (silent) {
    msg.className = 'msg';
    msg.textContent = '';
    return;
  }
  if (errs && errs.length) {
    msg.className = 'msg warn';
    msg.textContent = '部分市场抓取失败：' + errs.join('；') + '（表格为已取到部分）';
  } else {
    msg.className = 'msg ok';
    msg.textContent = '数据已更新。';
  }
}

async function update() {
  const btn = document.getElementById('upd');
  btn.disabled = true; btn.textContent = '抓取中…';
  document.getElementById('msg').className = 'msg';
  document.getElementById('msg').textContent = '正在请求 Gate / Bybit …';
  const errs = [];
  let gate = null, bybit = null;
  try { gate = await fetchGate(); } catch (e) { errs.push('Gate ' + e.message); }
  try { bybit = await fetchBybit(); } catch (e) { errs.push('Bybit ' + e.message); }
  if (gate && bybit) {
    const index = bybit.index || (SNAPSHOT.index || 0);
    const res = compute(gate, bybit, index);
    render({ rows: res.rows, index: index },
           new Date().toLocaleString('zh-CN') + '（浏览器实时抓取）', errs);
  } else {
    render(SNAPSHOT, '抓取失败，显示为快照（生成时间见页脚）', errs.length ? errs : ['未知错误']);
  }
  btn.disabled = false; btn.textContent = '更新数据';
}

document.getElementById('upd').addEventListener('click', update);

// 排序
(function () {
  const t = document.getElementById('t');
  const ths = t.querySelectorAll('th');
  const asc = {};
  ths.forEach(function (th) {
    th.addEventListener('click', function () {
      const c = +th.dataset.c, tb = t.tBodies[0];
      const rows = Array.prototype.slice.call(tb.rows);
      asc[c] = !asc[c];
      rows.sort(function (a, b) {
        const x = a.cells[c].innerText.replace('%','').trim();
        const y = b.cells[c].innerText.replace('%','').trim();
        const nx = parseFloat(x), ny = parseFloat(y);
        if (!isNaN(nx) && !isNaN(ny)) return asc[c] ? nx - ny : ny - nx;
        return asc[c] ? x.localeCompare(y) : y.localeCompare(x);
      });
      rows.forEach(function (r) { tb.appendChild(r); });
    });
  });
})();

// 首屏：先用快照渲染（不提示“已更新”）
render(SNAPSHOT, '快照（点右上角「更新数据」抓最新）', [], true);
"""

CSS = r"""
:root{--bg:#f5f6f8;--card:#fff;--ink:#1c1f23;--sub:#6b7280;--line:#e6e8ec;
      --pos:#128a5b;--neg:#c0392b;--accent:#2f5bea;}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.55 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
.wrap{max-width:1180px;margin:0 auto;padding:26px 20px 60px;}
.top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;flex-wrap:wrap;}
h1{font-size:23px;margin:0 0 6px;letter-spacing:.3px;}
.meta{color:var(--sub);font-size:13.5px;}
#upd{background:var(--accent);color:#fff;border:0;border-radius:10px;
     padding:11px 22px;font-size:15px;font-weight:600;cursor:pointer;
     box-shadow:0 2px 8px rgba(47,91,234,.25);white-space:nowrap;}
#upd:hover{filter:brightness(1.06);}
#upd:disabled{opacity:.6;cursor:default;}
.msg{margin:14px 0 0;font-size:13.5px;min-height:20px;color:var(--sub);}
.msg.ok{color:var(--pos);}
.msg.warn{color:#a8620a;}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:18px 0 24px;}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:15px 17px;}
.card .k{color:var(--sub);font-size:12.5px;margin-bottom:7px;}
.card .v{font-size:22px;font-weight:650;letter-spacing:.3px;}
.pill{display:inline-block;padding:1px 9px;border-radius:20px;font-size:15px;}
.pos-pill{background:#e6f6ee;color:var(--pos);}
.zero-pill{background:#f1f2f4;color:var(--sub);}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-bottom:22px;}
.panel h2{font-size:15px;margin:0;padding:13px 18px;border-bottom:1px solid var(--line);font-weight:600;}
table{width:100%;border-collapse:collapse;font-size:13.5px;}
th,td{padding:9px 12px;border-bottom:1px solid var(--line);white-space:nowrap;}
th{background:#fafbfc;color:var(--sub);font-weight:600;text-align:left;position:sticky;top:0;cursor:pointer;user-select:none;}
th:hover{color:var(--accent);}
td.c{text-align:center;}
td.n{text-align:right;font-variant-numeric:tabular-nums;}
td.strong{font-weight:700;}
tr.pos td.strong{color:var(--pos);}
tr.neg td.strong{color:var(--neg);}
tr:hover td{background:#fafcff;}
td.empty{text-align:center;color:var(--sub);padding:26px;}
.vt th,.vt td{font-size:13px;}
.yes{color:var(--pos);font-weight:600;}
.no{color:var(--sub);}
.note{margin-top:6px;background:#fffdf3;border:1px solid #f0e6c0;border-radius:12px;
      padding:15px 18px;font-size:13.5px;color:#5c4b17;}
.note b{color:#3f3305;}
.note ul{margin:8px 0 0;padding-left:18px;}
footer{margin-top:24px;color:var(--sub);font-size:12.5px;}
"""


def normalize_snapshot(snapshot):
    """把 Python 扫描器的字段名（buy_at/net_apr_pct）统一成前端用的名字。"""
    rows = []
    for r in (snapshot.get('rows') or []):
        rows.append({
            'contract': r.get('contract'),
            'direction': r.get('direction'),
            'buy': r.get('buy_at', r.get('buy')),
            'sell': r.get('sell_at', r.get('sell')),
            'gross': r.get('gross'),
            'fee': r.get('fee'),
            'net': r.get('net'),
            'days': r.get('days'),
            'apr': r.get('net_apr_pct', r.get('apr')),
            'moneyness_pct': r.get('moneyness_pct'),
            'per_contract': r.get('per_contract'),
            'mult_guess': r.get('mult_guess', False),
            'usable': r.get('usable_hype', r.get('usable')),
            'real': r.get('real_profit', r.get('real')),
        })
    return {'rows': rows, 'index': snapshot.get('index', 0),
            'underlying': snapshot.get('underlying', 'HYPE')}


def build_html(snapshot):
    snapshot = normalize_snapshot(snapshot)
    venue_rows = []
    for name, dom, has, st, note in VENUE_COVERAGE:
        cls = 'yes' if has else 'no'
        mark = '有该品种' if has else '无该品种'
        venue_rows.append(
            f'<tr><td>{name}</td><td>{dom}</td>'
            f'<td class="{cls}">{mark}</td><td>{st}</td><td>{note}</td></tr>')
    venue_html = '\n'.join(venue_rows)

    snap_json = json.dumps(snapshot, ensure_ascii=False)
    js = JS.replace('__SNAPSHOT__', snap_json)
    when = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HYPE 期权跨所比价 · 看板</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div>
      <h1>HYPE 期权 · 跨所比价看板</h1>
      <div class="meta">数据时间：<span id="when">—</span>　|　指数价：<span id="idx">—</span> USDT</div>
    </div>
    <button id="upd">更新数据</button>
  </div>
  <div class="msg" id="msg"></div>

  <div class="cards">
    <div class="card"><div class="k">可比合约（同到期·同行权价·同类型）</div><div class="v" id="npair">—</div></div>
    <div class="card"><div class="k">扣费后净价差为正</div><div class="v" id="nhit">—</div></div>
    <div class="card"><div class="k">当前最佳净价差</div><div class="v" id="best">—</div></div>
    <div class="card"><div class="k">单张双所手续费</div><div class="v">≈ 0.066</div></div>
  </div>

  <div class="panel">
    <h2>市场覆盖（谁上架了 HYPE 期权）</h2>
    <table class="vt">
      <thead><tr><th>交易所</th><th>域名</th><th>是否有该品种</th><th>接入状态</th><th>说明</th></tr></thead>
      <tbody>
{venue_html}
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h2>价差明细（点表头可排序）</h2>
    <table id="t">
      <thead><tr>
        <th data-c="0">合约</th><th data-c="1">方向</th><th data-c="2">买价</th>
        <th data-c="3">卖价</th><th data-c="4">毛利</th><th data-c="5">手续费</th>
        <th data-c="6">净价差</th><th data-c="7">每张花</th><th data-c="8">实值率</th>
        <th data-c="9">剩余天数</th><th data-c="10">净年化</th>
        <th data-c="11">可成交</th><th data-c="12">实赚</th>
      </tr></thead>
      <tbody id="tb"><tr><td colspan="13" class="empty">加载中…</td></tr></tbody>
    </table>
  </div>

  <div class="note">
    <b>口径说明（先读这个）</b>
    <ul>
      <li>两条腿是<b>同一张合约</b>：同标的、同到期日、同行权价、同类型（都 CALL / 都 PUT）。</li>
      <li>两家均 <b>USDT 结算（Linear）</b>，不存在币本位敞口。</li>
      <li>手续费按「费率 × 指数价 × 张数」估算：Gate taker 0.05%、Bybit taker 0.03%。</li>
       <li><b>1 张 = 1 HYPE</b>（Gate 接口 multiplier = 1）；<b>「每张花」</b>就是买入腿一张实际要付的 USDT。</li>
       <li><b>「可成交」= 买腿卖单量 ∩ 卖腿买单量</b>（取小）；<b>「实赚」= 净价差 × 可成交量</b>——只剩这个数字才是真到手的钱。</li>
       <li><b>年化 = 净利润 ÷ 买入腿权利金 × 365 ÷ 剩余天数</b>（与 BTC 那份同口径）。</li>
      <li><b>未计入</b>：滑点、两腿成交时差、保证金占用、跨所转账。真实落袋比表里更难。</li>
      <li>净价差为负 = <b>此刻没有机会</b>，这是常态；机会是间歇出现的。</li>
      <li>点「更新数据」由<b>浏览器直接抓取行情</b>；若跨域或网络受限，会回落到本页内置快照。</li>
    </ul>
  </div>

  <footer>看板 HTML 生成时间：{when}　·　数据来源：Gate / Bybit 公开行情接口</footer>
</div>
<script>{js}</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=DEFAULT_SRC)
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()

    snapshot = {'rows': [], 'index': 0, 'underlying': 'HYPE'}
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
