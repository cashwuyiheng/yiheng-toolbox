# -*- coding: utf-8 -*-
"""单格核对：BTC 2026-12-25 80000 P / C —— 五家实时报价 + 挂单量"""
import json
import urllib.request

PROXY = 'http://127.0.0.1:7897'
op = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


def g(u):
    try:
        return json.loads(op.open(urllib.request.Request(
            u, headers={'User-Agent': UA}), timeout=45).read())
    except Exception as e:
        return {'_err': str(e)[:90]}


D = '2026-12-25'
IDX = 76949.6

print(f'目标：BTC {D} 80000 P   （指数参考 {IDX}）')
print('=' * 64)

# Gate
d = g('https://api.gateio.ws/api/v4/options/contracts?underlying=BTC_USDT')
for c in (d if isinstance(d, list) else []):
    if c['name'] in ('BTC_USDT-20261225-80000-P', 'BTC_USDT-20261225-80000-C'):
        print(f"Gate     {c['name'][-1]}  bid {c['bid1_price']:>8} (量 {c['bid1_size']:>6})"
              f"   ask {c['ask1_price']:>8} (量 {c['ask1_size']:>6})   mult={c['multiplier']}")

# Bybit
t = g('https://api.bybit.com/v5/market/tickers?category=option&baseCoin=BTC')
for c in ((t or {}).get('result') or {}).get('list') or []:
    if c['symbol'] in ('BTC-25DEC26-80000-P-USDT', 'BTC-25DEC26-80000-C-USDT'):
        print(f"Bybit    {c['symbol'].split('-')[-2]}  bid {c['bid1Price']:>8} (量 {c.get('bid1Size'):>6})"
              f"   ask {c['ask1Price']:>8} (量 {c.get('ask1Size'):>6})"
              f"   24h量 {c.get('volume24h')}")

# Binance
for sym in ('BTC-251225-80000-P', 'BTC-251225-80000-C'):
    d = g(f'https://eapi.binance.com/eapi/v1/ticker?symbol={sym}')
    row = d[0] if isinstance(d, list) and d else (d if isinstance(d, dict) else {})
    if row and 'bidPrice' in row:
        print(f"Binance  {sym.split('-')[-1]}  bid {row['bidPrice']:>8} (量 {row.get('bidQty')})"
              f"   ask {row['askPrice']:>8} (量 {row.get('askQty')})"
              f"   24h量 {row.get('volume')}  成交额 {row.get('amount')}")

# OKX 币本位
o = g('https://www.okx.com/api/v5/market/tickers?instType=OPTION&uly=BTC-USD')
for c in ((o or {}).get('data') or []):
    if c['instId'] in ('BTC-USD-251225-80000-P', 'BTC-USD-251225-80000-C'):
        try:
            b = float(c['bidPx'] or 0) * IDX; a = float(c['askPx'] or 0) * IDX
            print(f"OKX币本位 {c['instId'][-1]}  bid {b:>8.1f} (量 {c.get('bidSz')})"
                  f"   ask {a:>8.1f} (量 {c.get('askSz')})")
        except Exception:
            pass

# Deribit
db = g('https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option')
for c in ((db or {}).get('result') or []):
    if c.get('instrument_name') in ('BTC-25DEC26-80000-P', 'BTC-25DEC26-80000-C'):
        try:
            b = float(c['bid_price'] or 0) * IDX; a = float(c['ask_price'] or 0) * IDX
            print(f"Deribit   {c['instrument_name'][-1]}  bid {b:>8.1f} (量 {c.get('bid_amount')})"
                  f"   ask {a:>8.1f} (量 {c.get('ask_amount')})")
        except Exception:
            pass

print()
print('--- 若「Gate 买 → Binance 卖」成立，需要：Gate ask < Binance bid ---')
