# -*- coding: utf-8 -*-
"""
HYPE 期权跨所比价扫描器
=======================
对比 Bybit 与 Gate 上同一张 HYPE 期权合约的报价，算出「买低卖高」的价差。

口径声明（务必先读）：
  · 两条腿必须是同一张合约：同标的、同到期日、同行权价、同类型（都 CALL 或都 PUT）
  · 两家都是 USDT 结算（Linear），不存在币本位敞口
  · 手续费按「费率 × 指数价 × 张数」估算（Gate/Bybit 的期权手续费都按名义计）
  · 未考虑：滑点、两腿成交时差、保证金占用、提币
  · 输出的是「报价差」，不是「已落袋收益」

用法：
  python scan_options_arb.py            # 扫一次
  python scan_options_arb.py --raw      # 另外打印各家的原始字段样例
"""

import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.error

PROXY = 'http://127.0.0.1:7897'
UNDERLYING = 'HYPE'

# 手续费率（taker，按名义价计）——来自各所接口/公开费率表，可自行调整
TAKER_FEE = {
    'gate': 0.0005,    # Gate 期权接口 taker_fee_rate = 0.0005
    'bybit': 0.0003,   # Bybit 期权 taker 约 0.03%（按指数价计）
}

# 1 张合约 = 多少 HYPE（用于把「每 1 HYPE 的价」换算成「一张花多少钱」）
# Gate 接口 multiplier = 1（已确认）；Bybit 接口未直接给，按 1 估
MULT = {'gate': 1.0, 'bybit': 1.0}
MULT_GUESS = {'bybit'}

MONTHS = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
          'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}

_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


def http_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': _UA,
                                              'Accept': 'application/json'})
    try:
        return json.loads(_opener.open(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        return {'_http_error': e.code, '_body': e.read()[:200].decode('utf-8', 'replace')}
    except Exception as e:
        return {'_error': f'{type(e).__name__}: {e}'}


# ---------- Gate ----------
def fetch_gate():
    """返回 {(expiry_date, strike, kind): {bid, ask, size, raw}}"""
    url = f'https://api.gateio.ws/api/v4/options/contracts?underlying={UNDERLYING}_USDT'
    data = http_get(url)
    out = {}
    if not isinstance(data, list):
        return out, data
    for c in data:
        try:
            name = c['name']            # HYPE_USDT-20261002-110-P
            _, ymd, strike, kind = name.split('-')
            y = int(ymd[:4]); m = int(ymd[4:6]); d = int(ymd[6:8])
            key = (f'{y:04d}-{m:02d}-{d:02d}', float(strike), kind)
            out[key] = {
                'bid': float(c.get('bid1_price') or 0),
                'ask': float(c.get('ask1_price') or 0),
                'bid_sz': float(c.get('bid1_size') or 0),
                'ask_sz': float(c.get('ask1_size') or 0),
                'raw': name,
            }
        except Exception:
            continue
    return out, data


# ---------- Bybit ----------
def fetch_bybit():
    """返回 {(expiry_date, strike, kind): {bid, ask, size, raw}}"""
    t = http_get('https://api.bybit.com/v5/market/tickers'
                 f'?category=option&baseCoin={UNDERLYING}')
    out = {}
    lst = ((t or {}).get('result') or {}).get('list') or []
    for c in lst:
        try:
            sym = c['symbol']            # HYPE-30OCT26-78-P-USDT
            parts = sym.split('-')
            if len(parts) < 4:
                continue
            exp, strike, kind = parts[1], parts[2], parts[3]
            dd, mon, yy = exp[:2], exp[2:5], exp[5:7]
            y = 2000 + int(yy)
            m = MONTHS[mon.upper()]
            d = int(dd)
            key = (f'{y:04d}-{m:02d}-{d:02d}', float(strike), kind.upper())
            out[key] = {
                'bid': float(c.get('bid1Price') or 0),
                'ask': float(c.get('ask1Price') or 0),
                'bid_sz': float(c.get('bid1Size') or 0),
                'ask_sz': float(c.get('ask1Size') or 0),
                'index': float(c.get('indexPrice') or 0),
                'raw': sym,
            }
        except Exception:
            continue
    return out, lst


def main():
    raw_mode = '--raw' in sys.argv
    gate, gate_raw = fetch_gate()
    bybit, bybit_raw = fetch_bybit()

    if isinstance(gate_raw, dict) and '_http_error' in gate_raw:
        print('[Gate 取数失败]', gate_raw)
    if isinstance(bybit_raw, dict) and '_http_error' in bybit_raw:
        print('[Bybit 取数失败]', bybit_raw)

    print(f'Gate  HYPE 期权: {len(gate)} 张')
    print(f'Bybit HYPE 期权: {len(bybit)} 张')

    if raw_mode:
        print('\n--- Gate 样例 ---')
        for k in list(gate)[:2]:
            print(' ', k, gate[k])
        print('--- Bybit 样例 ---')
        if isinstance(bybit_raw, list) and bybit_raw:
            print(json.dumps(bybit_raw[0], indent=2, ensure_ascii=False))
            for k in list(bybit)[:2]:
                print(' ', k, bybit[k])
        print()

    # 指数价（用两家里取到的）
    idx = 81.6
    for v in bybit.values():
        if v.get('index'):
            idx = v['index']
            break

    # ---------- 匹配 + 算价差 ----------
    rows = []
    common = set(gate) & set(bybit)
    for key in common:
        g, b = gate[key], bybit[key]
        exp, strike, kind = key
        days = max((datetime.date.fromisoformat(exp) - datetime.date.today()).days, 1)
        # 实值/虚值：正值 = 实值，负值 = 虚值（相对现价百分比）
        moneyness = ((idx - strike) / idx * 100) if kind.upper() == 'C' else ((strike - idx) / idx * 100)
        legs = []
        # 方案 A：Gate 买、Bybit 卖
        if g['ask'] > 0 and b['bid'] > 0:
            legs.append(('gate→bybit', g['ask'], b['bid'], g['ask_sz'], b['bid_sz']))
        # 方案 B：Bybit 买、Gate 卖
        if b['ask'] > 0 and g['bid'] > 0:
            legs.append(('bybit→gate', b['ask'], g['bid'], b['ask_sz'], g['bid_sz']))
        for direction, buy, sell, buy_sz, sell_sz in legs:
            bn, sn = ('gate', 'bybit') if direction == 'gate→bybit' else ('bybit', 'gate')
            fee = (TAKER_FEE[bn] + TAKER_FEE[sn]) * idx
            gross = sell - buy
            net = gross - fee
            # 可成交的 HYPE 量 = 买腿可买量与卖腿可卖量取小；任一边取不到就标 unknown
            if buy_sz > 0 and sell_sz > 0:
                usable = min(buy_sz * MULT.get(bn, 1.0), sell_sz * MULT.get(sn, 1.0))
                real = net * usable
            else:
                usable, real = None, None
            rows.append({
                'contract': f'{UNDERLYING} {exp} {strike:g} {kind}',
                'direction': direction,
                'buy_at': round(buy, 4),
                'sell_at': round(sell, 4),
                'gross': round(gross, 4),
                'fee': round(fee, 4),
                'net': round(net, 4),
                'days': days,
                # 年化 = 净利润 / 买入腿权利金 × 365 / 剩余天数（与 BTC 那份同口径）
                'net_apr_pct': round(net / buy * (365 / days) * 100, 1) if buy else 0,
                'moneyness_pct': round(moneyness, 1),
                'per_contract': round(buy * MULT.get(bn, 1.0), 4),
                'mult': MULT.get(bn, 1.0),
                'mult_guess': bn in MULT_GUESS,
                'usable_hype': round(usable, 2) if usable is not None else None,
                'real_profit': round(real, 4) if real is not None else None,
                'expiry': exp,
            })

    rows.sort(key=lambda r: r['net'], reverse=True)
    hits = [r for r in rows if r['net'] > 0]
    real_hits = [r for r in hits if (r.get('real_profit') or 0) > 0]

    print(f'可比合约（两家都有该合约）: {len(common)}')
    print(f'算出价差的组合: {len(rows)}   其中净值为正: {len(hits)}'
          f'   其中“实赚”也为正: {len(real_hits)}')
    print(f'指数价: {idx}\n')

    if not rows:
        print('没有可比对的双边报价。')
        return

    print('=== 净价差 前 15 ===')
    print(f"{'合约':<26}{'方向':<14}{'买':>8}{'卖':>8}{'净利':>9}"
          f"{'每张花':>8}{'实值率':>8}{'天':>4}{'年化':>8}{'可成交':>9}{'实赚':>8}")
    for r in rows[:15]:
        money = ('实值' if r['moneyness_pct'] > 0 else '虚值') + f"{abs(r['moneyness_pct']):.0f}%"
        us = ('%.1f HYPE' % r['usable_hype']) if r.get('usable_hype') else '未知'
        real = ('%.2f' % r['real_profit']) if r.get('real_profit') is not None else '—'
        print(f"{r['contract']:<26}{r['direction']:<14}"
              f"{r['buy_at']:>8}{r['sell_at']:>8}{r['net']:>9.4f}"
              f"{r['per_contract']:>8.3f}{money:>8}{r['days']:>4}"
              f"{r['net_apr_pct']:>7.0f}%{us:>9}{real:>8}")

    print('\n【实赚】净价差 × 可成交 HYPE 量（买腿可买 ∩ 卖腿可卖）；量取不到则显示 —')

    # 存一份（放在脚本同级的 数据\ 下，便于整包拷贝到 U 盘）
    base = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base, '数据')
    os.makedirs(data_dir, exist_ok=True)
    outp = os.path.join(data_dir, 'options_arb_hype.json')
    try:
        with open(outp, 'w', encoding='utf-8') as f:
            json.dump({'ts': int(time.time()), 'underlying': UNDERLYING, 'index': idx,
                       'n_common': len(common), 'n_pairs': len(rows), 'n_pos': len(hits),
                       'n_real': len(real_hits), 'rows': rows}, f, ensure_ascii=False, indent=2)
        print(f'\n已存: {outp}')
    except Exception as e:
        print('存盘失败:', e)


if __name__ == '__main__':
    main()
