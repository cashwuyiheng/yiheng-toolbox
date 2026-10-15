# -*- coding: utf-8 -*-
"""从 pool_status.json 生成「免费额度池」看板（深蓝 + 橙）· 多平台版。"""
import datetime
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
STATUS_PATH = os.path.join(BASE, "pool_status.json")
OUT_PATH = os.path.join(BASE, "额度池看板.html")

LABEL = {"ok": ("还有免费额度", "ok"), "exhausted": ("额度已用尽", "dead"),
         "not_found": ("不存在", "mute"), "auth": ("key 无效", "dead"), "throttled": ("被限流", "warn")}

d = json.load(open(STATUS_PATH, encoding="utf-8"))
plats = d.get("platforms", {})

total_ok = 0
sections = ""
cards = ""
for pname, pv in plats.items():
    models = pv.get("models", {})
    ok = [m for m, v in models.items() if v["status"] == "ok"]
    dead = [m for m, v in models.items() if v["status"] != "ok"]
    total_ok += len(ok)
    cards += (f'<div class="card"><div class="n">{len(ok)}</div>'
              f'<div class="t">{pname} · 可用</div></div>')
    # 可用模型才列细表；耗尽的合并成一行备注
    rows = ""
    for m in ok:
        rows += f'<tr><td class="mono">{m}</td><td><span class="pill ok">可用</span></td></tr>'
    if dead:
        rows += (f'<tr><td class="mono mute">其余 {len(dead)} 个</td>'
                 f'<td><span class="pill dead">不可用 / 已耗尽</span></td></tr>')
    sections += (f'<h2>{pname} <span class="muted">· {pv.get("base","")}</span></h2>'
                 f'<table><tr><th>模型</th><th>状态</th></tr>{rows}</table>')

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>AI 免费额度池</title>
<style>
:root{{--navy:#003366;--orange:#FF6600;--ink:#1c2530;--muted:#5b6672;--line:#e2e7ee;--bg:#f7f9fc}}
*{{box-sizing:border-box}}
body{{font-family:"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;color:var(--ink);background:#fff;margin:0;line-height:1.7}}
.wrap{{max-width:820px;margin:0 auto;padding:44px 36px 56px}}
.kicker{{color:var(--orange);font-size:13px;letter-spacing:.2em;font-weight:700}}
h1{{color:var(--navy);font-size:28px;margin:8px 0 6px}}
.meta{{color:var(--muted);font-size:13px;border-bottom:2px solid var(--navy);padding-bottom:16px;margin-bottom:22px}}
.cards{{display:flex;gap:14px;margin-bottom:8px;flex-wrap:wrap}}
.card{{flex:1;min-width:150px;border:1px solid var(--line);border-radius:14px;padding:16px 18px;background:var(--bg)}}
.card .n{{font-size:30px;font-weight:800;color:var(--navy)}}
.card .t{{font-size:13px;color:var(--muted)}}
h2{{color:var(--navy);font-size:17px;margin:30px 0 10px;padding-left:11px;border-left:5px solid var(--orange)}}
h2 .muted{{color:var(--muted);font-weight:400;font-size:12.5px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{border-bottom:1px solid var(--line);padding:8px 12px;text-align:left}}
th{{background:var(--navy);color:#fff;font-weight:600;font-size:12.5px}}
.mono{{font-family:Consolas,"JetBrains Mono",monospace}}
.mute{{color:var(--muted)}}
.pill{{display:inline-block;font-size:12px;padding:2px 10px;border-radius:999px;font-weight:700}}
.pill.ok{{background:#e9f2ee;color:#1f7a53}}
.pill.dead{{background:#ffe9e9;color:#a11}}
.pill.warn{{background:#fff0e6;color:#b34700}}
.pill.mute{{background:#eef1f5;color:#5b6672}}
.foot{{margin-top:30px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px}}
</style></head><body><div class="wrap">
<div class="kicker">免费额度池 · 多平台</div>
<h1>还有哪些模型可以白嫖</h1>
<div class="meta">探测时间：{d.get("ts","")}　｜　生成：{datetime.datetime.now():%Y-%m-%d %H:%M}</div>
<div class="cards">{cards}<div class="card"><div class="n" style="color:var(--orange)">{total_ok}</div><div class="t">合计可用模型</div></div></div>
{sections}
<div class="foot">用法：中转站每次挑一个「还有免费额度」的模型；一个 403 就自动换下一个。绿点越多，白嫖余量越大。</div>
</div></body></html>
"""

open(OUT_PATH, "w", encoding="utf-8").write(html)
print("已生成:", OUT_PATH, "| 合计可用", total_ok)
