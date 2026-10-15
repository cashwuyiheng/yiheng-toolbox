# -*- coding: utf-8 -*-
"""
BTC 期权 · 五所跨所比价扫描器
=============================
覆盖：Gate / Bybit / Binance / OKX / Deribit

口径（务必先读）：
  · 全部归一为「USDT / 1 BTC 的期权权利金」
      - Linear（USDT 结算）：Gate / Bybit / Binance —— 报价即 USDT，直接用
      - Inverse（币本位）：OKX / Deribit —— 报价以 BTC 计，需 × 指数价
  · 两条腿是同一张合约：同到期日、同行权价、同类型
  · 费用按「费率 × 指数价」估算（各所期权手续费均按名义计）
  · Inverse 那两家虽然已折成 USDT，但**结算仍是币本位**，币价波动会带来敞口

用法：
  python scan_options_arb_btc.py
  python scan_options_arb_btc.py --top 30
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.request
import urllib.error

PROXY = 'http://127.0.0.1:7897'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

# taker 费率（按指数名义计），可从各所文档/接口核对后调整
FEES = {'gate': 0.0003, 'bybit': 0.0003, 'binance': 0.0002,
        'okx': 0.0002, 'okx_um': 0.0002, 'deribit': 0.0003, 'deribit_usdc': 0.0003}
# 报价是否为币本位（需要 × 指数换算成 USDT）
INVERSE = {'okx': True, 'deribit': True}
# 哪些是 USDT/USDC 结算（Linear）——两条腿结算方式不同要标记出来
LINEAR = {'gate': True, 'bybit': True, 'binance': True,
          'okx_um': True, 'deribit_usdc': True,
          'okx': False, 'deribit': False}

# 1 张合约 = 多少 BTC（用于把「每 1 BTC 的价」换算成「一张花多少钱」）
# Gate / OKX 来自接口字段；Deribit 来自 contract_size；Bybit / Binance 接口未直接给，按 0.01 估
MULT = {'gate': 0.01, 'okx': 0.01, 'okx_um': 0.01,
        'deribit': 1.0, 'deribit_usdc': 1.0,
        'bybit': 0.01, 'binance': 0.01}
# 出现在表里标注“推定”的乘数
MULT_GUESS = {'bybit', 'binance'}

# 筛子：超过这个偏离就视为「深度实值/深度虚值」，不是实战标的
MAX_ABS_MONEYNESS = 25.0     # 百分比
MAX_DAYS = 120               # 超过这个天数的远月，报价多为陈旧

MONTHS = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
          'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}

_use_proxy = True
try:
    _opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
except Exception:
    _opener = urllib.request.build_opener()


def http_get(url):
    for attempt in (0, 1):
        try:
            return json.loads(_opener.open(
                urllib.request.Request(url, headers={'User-Agent': UA,
                                                     'Accept': 'application/json'}),
                timeout=45).read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt == 0:
                time.sleep(1.5)
                continue
            return {'_err': f'HTTP {e.code}'}
        except Exception as e:
            if attempt == 0:
                time.sleep(1.0)
                continue
            return {'_err': f'{type(e).__name__}'}
    return {'_err': 'unknown'}


def key_of(exp_iso, strike, kind):
    return f'{exp_iso}|{float(strike):g}|{kind.upper()}'


# ---------------- Gate ----------------
def fetch_gate():
    d = http_get('https://api.gateio.ws/api/v4/options/contracts?underlying=BTC_USDT')
    out, idx = {}, 0
    if not isinstance(d, list):
        return out, idx, d
    for c in d:
        try:
            _, ymd, strike, kind = c['name'].split('-')
            iso = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'
            out[key_of(iso, strike, kind)] = {
                'bid': float(c.get('bid1_price') or 0),
                'ask': float(c.get('ask1_price') or 0),
                'bid_sz': float(c.get('bid1_size') or 0),
                'ask_sz': float(c.get('ask1_size') or 0),
            }
            idx = idx or float(c.get('underlying_price') or 0)
        except Exception:
            continue
    return out, idx, None


# ---------------- Bybit ----------------
def fetch_bybit():
    d = http_get('https://api.bybit.com/v5/market/tickers?category=option&baseCoin=BTC')
    lst = ((d or {}).get('result') or {}).get('list') or []
    out, idx = {}, 0
    for c in lst:
        try:
            p = c['symbol'].split('-')          # BTC-25SEP26-70000-P-USDT
            if len(p) < 4:
                continue
            exp = p[1]
            iso = f'20{exp[5:7]}-{MONTHS[exp[2:5].upper()]:02d}-{exp[:2]}'
            out[key_of(iso, p[2], p[3])] = {
                'bid': float(c.get('bid1Price') or 0),
                'ask': float(c.get('ask1Price') or 0),
                'bid_sz': float(c.get('bid1Size') or 0),
                'ask_sz': float(c.get('ask1Size') or 0),
            }
            idx = idx or float(c.get('indexPrice') or 0)
        except Exception:
            continue
    return out, idx, None


# ---------------- Binance ----------------
def fetch_binance():
    e = http_get('https://eapi.binance.com/eapi/v1/exchangeInfo')
    syms = [o for o in ((e or {}).get('optionSymbols') or [])
            if o.get('underlying') == 'BTCUSDT']
    meta = {}
    for o in syms:
        try:
            dt = datetime.datetime.utcfromtimestamp(o['expiryDate'] / 1000)
            iso = dt.strftime('%Y-%m-%d')
            sym = o['symbol']                    # BTC-260925-70000-P
            strike = o['strikePrice']
            kind = 'C' if o['side'] == 'CALL' else 'P'
            meta[key_of(iso, strike, kind)] = sym
        except Exception:
            continue
    # 报价：批量接口
    tk = http_get('https://eapi.binance.com/eapi/v1/ticker')
    rows = tk if isinstance(tk, list) else []
    by_sym = {r.get('symbol'): r for r in rows if isinstance(r, dict)}
    out, idx = {}, 0
    for k, sym in meta.items():
        r = by_sym.get(sym)
        if not r:
            continue
        out[k] = {
            'bid': float(r.get('bidPrice') or 0),
            'ask': float(r.get('askPrice') or 0),
            'bid_sz': 0.0,
            'ask_sz': 0.0,
        }
        idx = idx or float(r.get('indexPrice') or 0)
    return out, idx, (None if rows else {'_err': 'no bulk ticker'})


# ---------------- OKX ----------------
def fetch_okx_family(seg):
    """seg = 'BTC-USD'（币本位）或 'BTC-USD_UM'（USDT 结算）
    OKX 同一个 uly=BTC-USD 会同时返回两个盘口，这里按家族切开。"""
    d = http_get('https://www.okx.com/api/v5/market/tickers?instType=OPTION&uly=BTC-USD')
    lst = (d or {}).get('data') or []
    out, idx = {}, 0
    if not lst:
        return out, idx, d if isinstance(d, dict) and '_err' in d else {'_err': 'empty'}
    want = seg.split('-')[1]                     # 'USD' 或 'USD_UM'
    for c in lst:
        try:
            p = c['instId'].split('-')           # BTC-USD-260925-70000-P
            if len(p) < 5 or p[1] != want:
                continue
            ymd = p[2]
            iso = f'20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}'
            out[key_of(iso, p[3], p[4])] = {
                'bid': float(c.get('bidPx') or 0),
                'ask': float(c.get('askPx') or 0),
                'bid_sz': float(c.get('bidSz') or 0),
                'ask_sz': float(c.get('askSz') or 0),
            }
        except Exception:
            continue
    return out, idx, None


def fetch_okx():
    return fetch_okx_family('BTC-USD')


def fetch_okx_um():
    return fetch_okx_family('BTC-USD_UM')


# ---------------- Deribit ----------------
def fetch_deribit():
    """只收 BTC-... （币本位）；BTC_USDC-... 算 USDC 结算，由 fetch_deribit_usdc 处理"""
    return _fetch_deribit(family='BTC')


def fetch_deribit_usdc():
    return _fetch_deribit(family='BTC_USDC')


def _fetch_deribit(family):
    d = http_get('https://www.deribit.com/api/v2/public/get_book_summary_by_currency'
                 '?currency=%s&kind=option' % family)
    lst = (d or {}).get('result') or []
    out, idx = {}, 0
    if not lst:
        return out, idx, None
    want = family + '-'
    for c in lst:
        try:
            name = c['instrument_name']          # BTC-25SEP26-70000-P
            if not name.startswith(want):
                continue
            p = name.split('-')[1:]               # ['25SEP26','70000','P']
            if len(p) < 3:
                continue
            exp = p[0]
            iso = f'20{exp[5:7]}-{MONTHS[exp[2:5].upper()]:02d}-{exp[:2]}'
            out[key_of(iso, p[1], p[2])] = {
                'bid': float(c.get('bid_price') or 0),   # 币本位：单位 BTC；USDC 盘：单位 USDC
                'ask': float(c.get('ask_price') or 0),
                'bid_sz': 0.0,
                'ask_sz': 0.0,
            }
            idx = idx or float(c.get('underlying_price') or 0)
        except Exception:
            continue
    return out, idx, None


VENUES = [
    ('gate', fetch_gate), ('bybit', fetch_bybit), ('binance', fetch_binance),
    ('okx', fetch_okx), ('okx_um', fetch_okx_um),
    ('deribit', fetch_deribit), ('deribit_usdc', fetch_deribit_usdc),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=25)
    args = ap.parse_args()

    books, idxs, notes = {}, {}, []
    for name, fn in VENUES:
        b, i, err = fn()
        books[name] = b
        if i:
            idxs[name] = i
        if err:
            notes.append(f'{name}: {err}')
        print(f'{name:<8} 合约 {len(b):>5} 张   指数 {i:.2f}' if i else
              f'{name:<8} 合约 {len(b):>5} 张')

    idx = 0
    if idxs:
        idx = sorted(idxs.values())[len(idxs) // 2]
    print(f'\n采用指数价（中位）: {idx:.2f}')
    if notes:
        print('异常:', '；'.join(notes))

    # ---- 归一化：把币本位折成 USDT；同时把挂单量折成「多少 BTC」----
    norm = {}
    for name, b in books.items():
        pmult = idx if INVERSE.get(name) else 1.0
        cmult = MULT.get(name, 0.01)
        for k, v in b.items():
            norm.setdefault(k, {})[name] = {
                'bid': v['bid'] * pmult, 'ask': v['ask'] * pmult,
                'raw_bid': v['bid'], 'raw_ask': v['ask'],
                'bid_sz': v.get('bid_sz', 0) * cmult,   # 可卖出的 BTC 量
                'ask_sz': v.get('ask_sz', 0) * cmult,   # 可买入的 BTC 量
            }

    # ---- 逐合约找机会 ----
    rows = []
    for k, per in norm.items():
        iso, strike, kind = k.split('|')
        try:
            days = max((datetime.date.fromisoformat(iso) - datetime.date.today()).days, 1)
        except Exception:
            days = 1
        if days > MAX_DAYS:
            continue
        K_ = float(strike)
        # 实值/虚值：正值 = 实值，负值 = 虚值（相对现价的百分比）
        moneyness = ((idx - K_) / idx * 100) if kind.upper() == 'C' else ((K_ - idx) / idx * 100)
        if abs(moneyness) > MAX_ABS_MONEYNESS:
            continue
        live = {n: q for n, q in per.items() if q['ask'] > 0 and q['bid'] > 0}
        if len(live) < 2:
            continue
        for bn, bq in live.items():
            for sn, sq in live.items():
                if bn == sn:
                    continue
                buy, sell = bq['ask'], sq['bid']
                gross = sell - buy
                fee = (FEES.get(bn, 0.0003) + FEES.get(sn, 0.0003)) * idx
                net = gross - fee
                mult = MULT.get(bn, 0.01)
                # 可成交的 BTC 量 = 买腿可买量与卖腿可卖量取小；任一边取不到就标 unknown
                bq_sz, sq_sz = bq['ask_sz'], sq['bid_sz']
                if bq_sz > 0 and sq_sz > 0:
                    usable = min(bq_sz, sq_sz)
                    real = net * usable
                else:
                    usable, real = None, None
                rows.append({
                    'contract': f'BTC {iso} {float(strike):g} {kind}',
                    'buy_at': bn, 'sell_at': sn,
                    'buy': round(buy, 2), 'sell': round(sell, 2),
                    'gross': round(gross, 2), 'fee': round(fee, 2),
                    'net': round(net, 2), 'days': days,
                    'mixed': (LINEAR.get(bn, True) != LINEAR.get(sn, True)),
                    'moneyness_pct': round(moneyness, 1),
                    'per_contract': round(buy * mult, 2),
                    'mult': mult,
                    'mult_guess': bn in MULT_GUESS,
                    'usable_btc': round(usable, 4) if usable is not None else None,
                    'real_profit': round(real, 2) if real is not None else None,
                    # 年化 = 净利润 / 买入腿权利金 × 365 / 剩余天数
                    'apr': round(net / buy * (365 / days) * 100, 1) if buy else 0,
                })
    rows.sort(key=lambda r: r['net'], reverse=True)
    pos = [r for r in rows if r['net'] > 0]
    same = [r for r in pos if not r['mixed']]
    mixed = [r for r in pos if r['mixed']]
    print(f'\n可比合约: {len(norm)}   组合: {len(rows)}   净价差>0: {len(pos)}'
          f'（同结算 {len(same)} / 跨结算 {len(mixed)}）')

    def table(title, data, star):
        print(f'\n=== {title} ===')
        if not data:
            print('   （无）')
            return
        print(f"{'合约':<24}{'方向':<22}{'买价':>10}{'卖价':>10}{'净':>9}"
              f"{'每张花':>10}{'实值率':>8}{'天':>5}{'年化':>8}{'可成交':>9}{'实赚':>9}")
        for r in data[:args.top]:
            money = ('实值' if r['moneyness_pct'] > 0 else '虚值') + f"{abs(r['moneyness_pct']):.0f}%"
            us = ('%.2f BTC' % r['usable_btc']) if r.get('usable_btc') else '未知'
            real = ('%.2f' % r['real_profit']) if r.get('real_profit') is not None else '—'
            print(f"{r['contract']:<24}{(r['buy_at']+' → '+r['sell_at']):<22}"
                  f"{r['buy']:>10.2f}{r['sell']:>10.2f}{r['net']:>9.2f}"
                  f"{r['per_contract']:>10.2f}{money:>8}{r['days']:>5}{r['apr']:>7.0f}%"
                  f"{us:>9}{real:>9}{' ✱' if star else ''}")

    print('\n【筛子】已剔除：偏离现价 >%d%% 的深度实/虚值、剩余 >%d 天的远月'
          % (MAX_ABS_MONEYNESS, MAX_DAYS))
    print('【年化口径】净利润 ÷ 买入腿权利金 × 365 ÷ 剩余天数')
    print('【实赚】净价差 × 可成交 BTC 量（买腿可买 ∩ 卖腿可卖）；量取不到则显示 —')

    table('① 两腿结算方式相同（干净，可执行）', same, False)
    table('② 跨结算方式（✱ 多一层敲口，谨慎）', mixed, True)

    base = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(base, '数据')
    os.makedirs(d, exist_ok=True)
    outp = os.path.join(d, 'options_arb_btc.json')
    with open(outp, 'w', encoding='utf-8') as f:
        json.dump({'ts': int(time.time()), 'symbol': 'BTC', 'index': idx,
                   'venue_counts': {k: len(v) for k, v in books.items()},
                   'n_common': len(norm), 'n_pairs': len(rows), 'n_pos': len(pos),
                   'n_same': len(same),
                   'filters': {'max_moneyness': MAX_ABS_MONEYNESS, 'max_days': MAX_DAYS},
                   'rows': rows[:600]}, f, ensure_ascii=False, indent=2)
    print('\n已存:', outp)


if __name__ == '__main__':
    main()
