# -*- coding: utf-8 -*-
"""Web3 地址监控 · 本地

给指定的 EVM 地址，查它在各条链上的余额（原生币 + 主流代币），
折成 USD，生成本地看板。纯标准库，零依赖；数据不出门。

用法：
  python web3监控.py            # 抓一轮 -> 写 monitor_data.json + 看板.html
  python web3监控.py --open     # 抓完顺手打开看板
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE, "monitor_data.json")
HTML_PATH = os.path.join(BASE, "版图.html")

# ============ ① 要盯的地址（你只改这里） ============
ADDRESSES = {
    "小霞钱包": "0x3b89f20ffba7b5198686da2c06261f4fac0e968b",
    "PIONEER": "0xD83181C6002F667592E275fCe79671Ea5de42A75",
}

# ============ ② 链 + 主流代币 ============
# 公共 RPC，免 key。（代币：symbol -> [合约地址, 小数位]）
CHAINS = {
    "Ethereum": {
        "rpc": "https://ethereum-rpc.publicnode.com", "coin": "ETH",
        "tokens": {
            "USDT": ["0xdAC17F958D2ee523a2206206994597C13D831ec7", 6],
            "USDC": ["0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6],
            "DAI":  ["0x6B175474E89094C44Da98b954EedeAC495271d0F", 18],
            "WETH": ["0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18],
        },
    },
    "BSC": {
        "rpc": "https://bsc-rpc.publicnode.com", "coin": "BNB",
        "tokens": {
            "USDT": ["0x55d398326f99059fF775485246999027B3197955", 18],
            "USDC": ["0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", 18],
            "U":    ["0xce24439f2d9c6a2289f741120fe202248b666666", 18],
            "BUSD": ["0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56", 18],
            "WBNB": ["0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c", 18],
        },
    },
    "Polygon": {
        "rpc": "https://polygon-bor-rpc.publicnode.com", "coin": "POL",
        "tokens": {
            "USDT": ["0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6],
            "USDC": ["0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6],
            "WETH": ["0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619", 18],
        },
    },
    "Arbitrum": {
        "rpc": "https://arbitrum-one-rpc.publicnode.com", "coin": "ETH",
        "tokens": {
            "USDT": ["0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6],
            "USDC": ["0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6],
            "ARB":  ["0x912CE59144191C1204E64559FE8253a0e49E6548", 18],
        },
    },
    "Base": {
        "rpc": "https://base-rpc.publicnode.com", "coin": "ETH",
        "tokens": {
            "USDC": ["0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6],
            "WETH": ["0x4200000000000000000000000000000000000006", 18],
        },
    },
}

# 价格：稳定币按 1；其余从币安公开行情取（免 key）。BUSD 已按 1 计。
STABLE = {"USDT", "USDC", "DAI", "BUSD"}
COIN_TO_SYMBOL = {"ETH": "ETHUSDT", "BNB": "BNBUSDT", "POL": "POLUSDT", "MATIC": "POLUSDT"}
TOKEN_TO_SYMBOL = {"WETH": "ETHUSDT", "WBNB": "BNBUSDT", "ARB": "ARBUSDT", "WMATIC": "POLUSDT"}

PROXY = "http://127.0.0.1:7897"  # 直连不通时自动回退到它（你的 Clash）

OP_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OP_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def _open(req, timeout):
    """先直连，不行再走代理。"""
    try:
        return OP_DIRECT.open(req, timeout=timeout)
    except Exception:
        return OP_PROXY.open(req, timeout=timeout)


def rpc(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with _open(req, 20) as r:
        return json.loads(r.read().decode("utf-8", "ignore")).get("result")


def get_price(symbol):
    if symbol in STABLE:
        return 1.0
    sym = COIN_TO_SYMBOL.get(symbol) or TOKEN_TO_SYMBOL.get(symbol) or (symbol + "USDT")
    try:
        req = urllib.request.Request(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}")
        with _open(req, 15) as r:
            return float(json.loads(r.read().decode())["price"])
    except Exception:
        return None


def main():
    prices = {}
    for s in list(COIN_TO_SYMBOL) + list(TOKEN_TO_SYMBOL) + list(STABLE):
        prices[s] = get_price(s)

    result = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "addresses": {}}
    for label, addr in ADDRESSES.items():
        holdings = []
        for chain, info in CHAINS.items():
            # 原生币
            try:
                wei = int(rpc(info["rpc"], "eth_getBalance", [addr, "latest"]), 16)
                bal = wei / 1e18
                if bal > 0:
                    holdings.append({"chain": chain, "sym": info["coin"], "amt": bal,
                                     "usd": bal * (prices.get(info["coin"]) or 0)})
            except Exception as e:
                print(f"  [错] {label} {chain} 原生: {type(e).__name__}")
            # 代币
            for sym, (tok, dec) in info["tokens"].items():
                try:
                    data = "0x70a08231" + addr[2:].lower().rjust(64, "0")
                    r = rpc(info["rpc"], "eth_call", [{"to": tok, "data": data}, "latest"])
                    amt = int(r, 16) / (10 ** dec)
                    if amt > 0:
                        holdings.append({"chain": chain, "sym": sym, "amt": amt,
                                         "usd": amt * (prices.get(sym) or 0)})
                except Exception as e:
                    print(f"  [错] {label} {chain} {sym}: {type(e).__name__}")
        result["addresses"][label] = {"addr": addr, "holdings": holdings,
                                      "total_usd": sum(h["usd"] for h in holdings)}
        print(f"  {label} 合计 ≈ ${result['addresses'][label]['total_usd']:.2f}")

    json.dump(result, open(DATA_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    render(result)
    print("已写:", DATA_PATH, "和", HTML_PATH)
    if "--open" in sys.argv:
        os.startfile(HTML_PATH)


def render(result):
    grand = sum(a["total_usd"] for a in result["addresses"].values())
    blocks = ""
    for label, a in result["addresses"].items():
        rows = ""
        for h in sorted(a["holdings"], key=lambda x: -x["usd"]):
            amt = f"{h['amt']:.4f}".rstrip("0").rstrip(".")
            rows += (f'<tr><td>{h["chain"]}</td><td><b>{h["sym"]}</b></td>'
                     f'<td class="mono">{amt}</td><td class="usd">${h["usd"]:,.2f}</td></tr>')
        if not rows:
            rows = '<tr><td colspan=4 class="muted">这个地址在这些链上没查到余额（或还没纳入监控）</td></tr>'
        blocks += (f'<h2>{label} <span class="muted">{a["addr"]}</span></h2>'
                   f'<div class="total">≈ ${a["total_usd"]:,.2f}</div>'
                   f'<table><tr><th>链</th><th>币</th><th>数量</th><th>估值</th></tr>{rows}</table>')
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Web3 版图</title><style>
:root{{--navy:#003366;--orange:#FF6600;--muted:#5b6672;--line:#e2e7ee;--bg:#f7f9fc}}
body{{font-family:"Noto Sans SC","Microsoft YaHei",sans-serif;color:#1c2530;background:#fff;margin:0;line-height:1.7}}
.wrap{{max-width:820px;margin:0 auto;padding:44px 36px}}
.kicker{{color:var(--orange);font-size:13px;letter-spacing:.2em;font-weight:700}}
h1{{color:var(--navy);font-size:28px;margin:8px 0}} .meta{{color:var(--muted);font-size:13px;border-bottom:2px solid var(--navy);padding-bottom:14px;margin-bottom:10px}}
.big{{font-size:34px;font-weight:800;color:var(--navy);margin:14px 0}}
h2{{color:var(--navy);font-size:17px;margin:26px 0 6px;padding-left:10px;border-left:5px solid var(--orange)}}
h2 .muted{{color:var(--muted);font-weight:400;font-size:12px;font-family:Consolas,monospace}}
.total{{color:var(--orange);font-weight:700;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th,td{{border-bottom:1px solid var(--line);padding:8px 11px;text-align:left}} th{{background:var(--navy);color:#fff;font-size:12.5px}} tr:nth-child(even) td{{background:var(--bg)}}
.mono{{font-family:Consolas,monospace}} .usd{{color:var(--orange);font-weight:700}} .muted{{color:var(--muted)}}
.foot{{margin-top:34px;color:var(--muted);font-size:12.5px;border-top:1px solid var(--line);padding-top:12px}}
</style></head><body><div class="wrap">
<div class="kicker">Web3 · 资金版图</div>
<h1>我的地址余额</h1>
<div class="meta">快照：{result.get('ts','')}</div>
<div class="big">合计 ≈ ${grand:,.2f}</div>
{blocks}
<div class="foot">只读地址、不连钱包；只查余额，不动资产。覆盖链：{' / '.join(CHAINS)}。全量代币需接索引服务（后续可加）。</div>
</div></body></html>"""
    open(HTML_PATH, "w", encoding="utf-8").write(html)


if __name__ == "__main__":
    main()
