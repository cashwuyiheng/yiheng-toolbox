# -*- coding: utf-8 -*-
"""追一层：毛锁定都是由哪两家构成的；扣费后还剩的那一个是什么"""
import json
import collections
import statistics
import time
import urllib.request
import importlib.util

spec = importlib.util.spec_from_file_location(
    'an', r'.\X监控\分析-套利是否还在.py')
# 直接复用其 snapshot()
src = open(r'.\X监控\分析-套利是否还在.py', encoding='utf-8').read()
ns = {}
exec(src.split("print('跨所 BTC 期权")[0], ns)
snapshot, FEES = ns['snapshot'], ns['FEES']

books, idx = snapshot()
print(f'指数 {idx:.0f}\n')

today = time.strftime('%Y-%m-%d')
pairs = collections.Counter()
details = []
n = 0
for k, per in books.items():
    iso, strike, kind = k
    days = (time.mktime(time.strptime(iso, '%Y-%m-%d')) -
            time.mktime(time.strptime(today, '%Y-%m-%d'))) / 86400
    if days > 45 or abs((strike - idx) / idx) > 0.15:
        continue
    lv = {v: q for v, q in per.items() if q[0] > 0 and q[1] > 0}
    if len(lv) < 2:
        continue
    n += 1
    bb = max(q[0] for q in lv.values())
    ba = min(q[1] for q in lv.values())
    if ba >= bb:
        continue
    bv = [v for v, q in lv.items() if q[1] == ba][0]
    sv = [v for v, q in lv.items() if q[0] == bb][0]
    pairs[(bv, sv)] += 1
    fee = (FEES[bv] + FEES[sv]) * idx
    net = bb - ba - fee
    details.append({
        'k': f'BTC {iso} {strike:g} {kind}', 'buy': bv, 'sell': sv,
        'gap': round(bb - ba, 2), 'fee': round(fee, 2), 'net': round(net, 2),
        'days': int(days),
    })

print(f'近月平值区间合约数: {n}')
print(f'毛锁定数: {sum(pairs.values())}\n')
print('毛锁定按「买@ → 卖@」构成：')
for (bv, sv), c in pairs.most_common(10):
    print(f'  买@{bv:<13} 卖@{sv:<13} {c} 个')

details.sort(key=lambda d: d['net'], reverse=True)
print('\n扣费后净值 前 8：')
print(f"  {'合约':<24}{'买@':<10}{'卖@':<10}{'毛差':>10}{'费用':>9}{'净':>10}{'天':>5}")
for d in details[:8]:
    print(f"  {d['k']:<24}{d['buy']:<10}{d['sell']:<10}{d['gap']:>10.2f}"
          f"{d['fee']:>9.2f}{d['net']:>10.2f}{d['days']:>5}")
