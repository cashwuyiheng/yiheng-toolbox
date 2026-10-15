# -*- coding: utf-8 -*-
"""双击即可：检查「网关在不在」以及「哪些脚本走了池子」。"""
import glob
import os
import urllib.request

BASE = r"."

print("=" * 56)

# 1) 网关在不在
try:
    urllib.request.urlopen("http://127.0.0.1:8788/healthz", timeout=3).read()
    up = True
except Exception:
    up = False
print("网关 127.0.0.1:8788 :", "在跑 ✅" if up else "没在跑 ❌（脚本会退回直连，等于没走池子）")
print("-" * 56)

# 2) 扫配置：走了池子 / 还直连
pool_cfg, direct_cfg = [], []
for path in glob.glob(os.path.join(BASE, "**", "*.json"), recursive=True):
    if "AI中转站" in path:
        continue
    try:
        txt = open(path, encoding="utf-8").read()
    except Exception:
        continue
    if "base_url" not in txt:
        continue
    rel = os.path.relpath(path, BASE)
    if "127.0.0.1:8788" in txt:
        pool_cfg.append(rel)
    if "dashscope.aliyuncs.com" in txt or "api.deepseek.com" in txt:
        direct_cfg.append(rel)

print("走了池子的配置：")
for p in (pool_cfg or ["（无）"]):
    print("   [OK]", p)
print("仍直连外部的配置：")
for p in (direct_cfg or ["（无）"]):
    print("   [直连]", p)
print("-" * 56)
print("结论：")
if up and pool_cfg:
    print(" 网关在跑，且有脚本指向它 -> 这些脚本会自动混用免费额度。")
else:
    print(" 网关没跑 -> 就算配置指向池子，也会退回直连。请先双击 启动网关.bat。")
