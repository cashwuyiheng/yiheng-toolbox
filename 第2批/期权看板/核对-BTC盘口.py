# -*- coding: utf-8 -*-
"""
核对用：把 11-27 / 12-25 / 27-03-26 三个到期日的近月平值区间报价，
按「USDT / 1 BTC」列出来，方便与手机 App 上的盘口逐格对照。
"""
import json
import urllib.request

PROXY = 'http://127.0.0.1:7897'
op = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
MON = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
       'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}


def g(u):
    try:
        return json.loads(op.open(urllib.request.Request(
            u, headers={'User-Agent': UA}), timeout=45).read())
    except Exception as e:
        return {'_err': str(e)[:80]}


TARGETS = ['2026-11-27', '2026-12-25', '2027-03-26']

# ---- 取数 ----
books, idx = {}, 0

d = g('https://api.gateio.ws/api/v4/options/contracts?underlying=BTC_USDT')
if isinstance(d, list):
    for c in d:
        _, ymd, k, t = c['name'].split('-')
        iso = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'
        if iso in TARGETS:
            books.setdefault(iso, {}).setdefault(('gate', float(k), t), (
                float(c.get('bid1_price') or 0), float(c.get('ask1_price') or 0)))
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
    if iso in TARGETS:
        books.setdefault(iso, {}).setdefault(('bybit', float(p[2]), p[3]), (
            float(c.get('bid1Price') or 0), float(c.get('ask1Price') or 0)))
    idx = idx or float(c.get('indexPrice') or 0)

d = g('https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option')
for c in ((d or {}).get('result') or []):
    nm = c.get('instrument_name') or ''
    p = nm.split('-')
    if p[0] != 'BTC' or len(p) < 4:
        continue
    try:
        exp = p[1]
        iso = f'20{exp[5:7]}-{MON[exp[2:5].upper()]:02d}-{exp[:2]}'
    except Exception:
        continue
    if iso in TARGETS:
        # 币本位：价格是 BTC 计，折成 USDT
        books.setdefault(iso, {}).setdefault(('deribit', float(p[2]), p[3]), (
            float(c.get('bid_price') or 0), float(c.get('ask_price') or 0)))
    idx = idx or float(c.get('underlying_price') or 0)

d = g('https://www.okx.com/api/v5/market/tickers?instType=OPTION&uly=BTC-USD')
for c in ((d or {}).get('data') or []):
    p = c['instId'].split('-')
    if len(p) < 5 or p[1] != 'USD':
        continue
    ymd = p[2]
    iso = f'20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}'
    if iso in TARGETS:
        books.setdefault(iso, {}).setdefault(('okx', float(p[3]), p[4]), (
            float(c.get('bidPx') or 0), float(c.get('askPx') or 0)))

print(f'BTC 指数价（中位参考）: {idx:.1f}\n')

INV = {'deribit', 'okx'}
for iso in TARGETS:
    per = books.get(iso) or {}
    if not per:
        print(f'=== {iso} ===  （无数据）\n')
        continue
    ks = sorted({k[1] for k in per})
    band = [k for k in ks if 0.86 * idx <= k <= 1.12 * idx]
    print(f'=== {iso}   行权价 {band[0]:g} ~ {band[-1]:g} （现价 ±14%）===')
    for t, tname in (('C', '看涨 CALL'), ('P', '看跌 PUT')):
        print(f'  -- {tname} --   [单位：USDT / 1 BTC   “买/卖”]')
        print(f"  {'行权价':>8}  {'Gate':>16}  {'Bybit':>16}  {'Deribit':>16}  {'OKX':>16}")
        for k in band:
            cells = []
            for v in ('gate', 'bybit', 'deribit', 'okx'):
                q = per.get((v, k, t))
                if q:
                    mult = idx if v in INV else 1.0
                    cells.append(f'{q[0]*mult:.1f}/{q[1]*mult:.1f}')
                else:
                    cells.append('—')
            print(f'  {k:>8.0f}  {cells[0]:>16}  {cells[1]:>16}  {cells[2]:>16}  {cells[3]:>16}')
    print()
