# -*- coding: utf-8 -*-
"""
跨所期权套利 · 结构性检验
=========================
判据不是「有没有一单」，而是三个比值：

  ① 锁定机会数：best_ask(全市场) < best_bid(全市场) 的合约数（毛）
  ② 中价离散度：各所同一合约中价的最大差 / 中价（bps）
  ③ 双边费用：买腿+卖腿费率 × 指数 / 权利金（bps）

结论逻辑：若 ③ 常年远大于 ②，则不是「机会少」，是「机会不存在」。
连测三轮，看它是否稳定。
"""
import json
import statistics
import time
import urllib.request

PROXY = 'http://127.0.0.1:7897'
op = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
MON = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
       'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
FEES = {'gate': 0.0003, 'bybit': 0.0003, 'binance': 0.0002,
        'okx': 0.0002, 'okx_um': 0.0002, 'deribit': 0.0003, 'deribit_usdc': 0.0003}
INV = {'okx', 'deribit'}


def g(u):
    try:
        return json.loads(op.open(urllib.request.Request(
            u, headers={'User-Agent': UA}), timeout=45).read())
    except Exception:
        return None


def snapshot():
    books, idx = {}, 0
    d = g('https://api.gateio.ws/api/v4/options/contracts?underlying=BTC_USDT')
    for c in (d if isinstance(d, list) else []):
        _, ymd, k, t = c['name'].split('-')
        iso = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'
        books.setdefault((iso, float(k), t), {})['gate'] = (
            float(c.get('bid1_price') or 0), float(c.get('ask1_price') or 0))
        idx = idx or float(c.get('underlying_price') or 0)

    d = g('https://api.bybit.com/v5/market/tickers?category=option&baseCoin=BTC')
    for c in ((d or {}).get('result') or {}).get('list') or []:
        p = c['symbol'].split('-')
        if len(p) < 4:
            continue
        try:
            exp = p[1]
            iso = f'20{exp[5:7]}-{MON[exp[2:5].upper()]:02d}-{exp[:2]}'
        except Exception:
            continue
        books.setdefault((iso, float(p[2]), p[3]), {})['bybit'] = (
            float(c.get('bid1Price') or 0), float(c.get('ask1Price') or 0))
        idx = idx or float(c.get('indexPrice') or 0)

    e = g('https://eapi.binance.com/eapi/v1/exchangeInfo')
    sym = {}
    for o in ((e or {}).get('optionSymbols') or []):
        if o.get('underlying') != 'BTCUSDT':
            continue
        iso = time.strftime('%Y-%m-%d', time.gmtime(o['expiryDate'] / 1000))
        sym[o['symbol']] = (iso, float(o['strikePrice']),
                            'C' if o['side'] == 'CALL' else 'P')
    tk = g('https://eapi.binance.com/eapi/v1/ticker')
    for r in (tk if isinstance(tk, list) else []):
        k = sym.get(r.get('symbol'))
        if not k:
            continue
        b, a = float(r.get('bidPrice') or 0), float(r.get('askPrice') or 0)
        if b > 0 and a > 0:
            books.setdefault(k, {})['binance'] = (b, a)

    d = g('https://www.okx.com/api/v5/market/tickers?instType=OPTION&uly=BTC-USD')
    for c in ((d or {}).get('data') or []):
        p = c['instId'].split('-')
        if len(p) < 5:
            continue
        ymd = p[2]
        iso = f'20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}'
        v = 'okx_um' if p[1] == 'USD_UM' else 'okx'
        b, a = float(c.get('bidPx') or 0), float(c.get('askPx') or 0)
        if b > 0 and a > 0:
            m = idx if v == 'okx' else 1.0
            books.setdefault((iso, float(p[3]), p[4]), {})[v] = (b * m, a * m)

    d = g('https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option')
    for c in ((d or {}).get('result') or []):
        p = (c.get('instrument_name') or '').split('-')
        if p[0] != 'BTC' or len(p) < 4:
            continue
        try:
            exp = p[1]
            iso = f'20{exp[5:7]}-{MON[exp[2:5].upper()]:02d}-{exp[:2]}'
        except Exception:
            continue
        b, a = float(c.get('bid_price') or 0), float(c.get('ask_price') or 0)
        if b > 0 and a > 0:
            books.setdefault((iso, float(p[2]), p[3]), {})['deribit'] = (b * idx, a * idx)
        idx = idx or float(c.get('underlying_price') or 0)
    return books, idx


def analyse(books, idx, label):
    locked = 0        # 毛锁定：全市场最低卖价 < 全市场最高买价
    net_locked = 0    # 扣费后仍锁定
    disps = []        # 中价离散度 bps
    fee_bps_list = []
    n_multi = 0
    today = time.strftime('%Y-%m-%d')
    for k, per in books.items():
        iso, strike, kind = k
        if (time.mktime(time.strptime(iso, '%Y-%m-%d')) -
                time.mktime(time.strptime(today, '%Y-%m-%d'))) / 86400 > 45:
            continue
        if abs((strike - idx) / idx) > 0.15:
            continue
        lv = {v: q for v, q in per.items() if q[0] > 0 and q[1] > 0}
        if len(lv) < 2:
            continue
        n_multi += 1
        mids = [(q[0] + q[1]) / 2 for q in lv.values()]
        mid = statistics.mean(mids)
        if mid <= 0:
            continue
        disps.append((max(mids) - min(mids)) / mid * 1e4)
        bb = max(q[0] for q in lv.values())
        ba = min(q[1] for q in lv.values())
        if ba < bb:
            locked += 1
            # 扣两边费用（按指数名义）
            bv = [v for v, q in lv.items() if q[1] == ba][0]
            sv = [v for v, q in lv.items() if q[0] == bb][0]
            if bb - ba > (FEES[bv] + FEES[sv]) * idx:
                net_locked += 1
        fee_bps_list.append((0.0003 + 0.0003) * idx / mid * 1e4)

    print(f'--- {label} ---')
    print(f'  参与统计的合约（近月≤45天 · 平值±15% · 至少两所有双边报价）: {n_multi}')
    if not disps:
        print('  无有效样本\n')
        return
    print(f'  ① 毛锁定（最低卖 < 最高买）              : {locked} 个')
    print(f'  ①b 扣费后仍锁定                          : {net_locked} 个')
    print(f'  ② 跨所中价离散度  中位 {statistics.median(disps):7.1f} bps'
          f'   最大 {max(disps):8.1f} bps')
    print(f'  ③ 双边手续费（相对权利金）中位 {statistics.median(fee_bps_list):7.1f} bps')
    ratio = statistics.median(fee_bps_list) / max(statistics.median(disps), 1e-9)
    print(f'  → 费用 ÷ 离散度 = {ratio:.1f} 倍')
    print()


print('跨所 BTC 期权 · 结构性检验（连测三轮）\n')
for i in range(3):
    books, idx = snapshot()
    if not books:
        print(f'第 {i+1} 轮取数失败\n')
        continue
    analyse(books, idx, f'第 {i+1} 轮 · 指数 {idx:.0f} · {time.strftime("%H:%M:%S")}')
    if i < 2:
        time.sleep(20)
