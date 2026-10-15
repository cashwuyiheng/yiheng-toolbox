# -*- coding: utf-8 -*-
"""关键情景：如果手续费能降下来，这 73 个毛锁定里能活几个"""
import time
import importlib.util

src = open(r'.\X监控\分析-套利是否还在.py', encoding='utf-8').read()
ns = {}
exec(src.split("print('跨所 BTC 期权")[0], ns)
snapshot, FEES = ns['snapshot'], ns['FEES']

books, idx = snapshot()
today = time.strftime('%Y-%m-%d')

locks = []
for k, per in books.items():
    iso, strike, kind = k
    days = (time.mktime(time.strptime(iso, '%Y-%m-%d')) -
            time.mktime(time.strptime(today, '%Y-%m-%d'))) / 86400
    if days > 45 or abs((strike - idx) / idx) > 0.15:
        continue
    lv = {v: q for v, q in per.items() if q[0] > 0 and q[1] > 0}
    if len(lv) < 2:
        continue
    bb = max(q[0] for q in lv.values())
    ba = min(q[1] for q in lv.values())
    if ba >= bb:
        continue
    bv = [v for v, q in lv.items() if q[1] == ba][0]
    sv = [v for v, q in lv.items() if q[0] == bb][0]
    locks.append((bb - ba, (FEES[bv] + FEES[sv]) * idx, bv, sv))

print(f'指数 {idx:.0f}   毛锁定 {len(locks)} 个\n')
print(f"{'手续费倍数':<12}{'净>0 的个数':<14}{'最好的净收益':<14}")
for mult, name in ((1.0, '1.0（现在）'), (0.5, '0.5（减半）'), (0.0, '0.0（免费）')):
    nets = [g - f * mult for g, f, _, _ in locks]
    pos = [x for x in nets if x > 0]
    print(f'{name:<12}{len(pos):<14}{(max(nets) if nets else 0):<14.2f}')

print('\n注：手续费倍数 0.5 ≈ 一边做 maker 且拿到返佣；0.0 ≈ 有一条零费腿（如 Lighter）')
