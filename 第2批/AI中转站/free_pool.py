# -*- coding: utf-8 -*-
"""AI 免费额度池 · 多平台

把「还有免费额度的模型」串起来，自动轮换：一个 403 就换下一个。
目前接：阿里云百炼(DashScope)、千问AI平台(qianwenai.com)。

用法：
  python free_pool.py          # 探所有平台，落盘 pool_status.json，打印摘要
  python free_pool.py --show   # 只看上次结果
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
WE_CFG = r".\微信监控\微信监控配置.json"   # 借百炼的 key
QW_CFG = os.path.join(BASE, "千问平台配置.json")                 # 千问AI平台的 key
STATUS_PATH = os.path.join(BASE, "pool_status.json")

# 百炼没有 /models 便捷枚举的习惯，这里列一批候选；千问平台用 /models 自动枚举。
BAILIAN_CANDIDATES = [
    "qwen3.8-flash", "qwen3.8-max", "qwen-flash", "qwen-plus", "qwen-max",
    "qwen-turbo", "qwen-long", "qwen3-max", "qwen3-coder-plus",
    "qwen-vl-plus", "qwen-vl-max",
]
# 枚举时跳过非文本对话类
SKIP = ("image", "audio", "video", "embedding", "rerank", "asr", "tts", "realtime",
        "livetranslate", "test", "sre", "ocr", "voice", "wan", "mt-", "vl-", "2.0-pro-")


def _we_key():
    cfg = json.load(open(WE_CFG, encoding="utf-8"))
    for p in cfg["ai"]["providers"]:
        if "dashscope" in p["base_url"]:
            return p["api_key"], p["base_url"].rstrip("/")
    raise SystemExit("微信监控配置里没找到 dashscope key")


def _platforms():
    key, base = _we_key()
    plats = [{"name": "百炼", "base": base, "key": key, "models": BAILIAN_CANDIDATES}]
    if os.path.exists(QW_CFG):
        q = json.load(open(QW_CFG, encoding="utf-8"))
        plats.append({"name": q.get("name", "千问AI平台"), "base": q["base_url"].rstrip("/"),
                      "key": q["api_key"], "models": None})
    return plats


def _req(base, key, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(base + path, data=data, method="POST" if data else "GET",
                               headers={"Authorization": "Bearer " + key,
                                        "Content-Type": "application/json"})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(r, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def classify(code, body):
    if code == 200:
        return "ok"
    if "AllocationQuota.FreeTierOnly" in body:
        return "exhausted"
    if code == 404 or "ModelNotFound" in body or "model not found" in body.lower():
        return "not_found"
    if code == 401 or "InvalidApiKey" in body:
        return "auth"
    if code == 429:
        return "throttled"
    return f"error{code}"


def _list_models(base, key):
    code, body = _req(base, key, "/models")
    if code != 200:
        return []
    return [m.get("id") for m in json.loads(body).get("data", []) if m.get("id")]


def probe(platforms=None):
    platforms = platforms or _platforms()
    out = {}
    for p in platforms:
        models = p["models"]
        if models is None:
            models = [m for m in _list_models(p["base"], p["key"])
                      if not any(s in m.lower() for s in SKIP)]
        res = {}
        for m in models:
            c, b = _req(p["base"], p["key"], "/chat/completions",
                        {"model": m, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1})
            res[m] = {"status": classify(c, b), "http": c}
            time.sleep(0.1)
        out[p["name"]] = {"base": p["base"], "models": res}
        print(f"  [{p['name']}] 共 {len(models)} 个，可用 "
              f"{sum(1 for v in res.values() if v['status'] == 'ok')}", flush=True)
    data = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "platforms": out}
    json.dump(data, open(STATUS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return data


def load_status():
    if not os.path.exists(STATUS_PATH):
        return probe()
    return json.load(open(STATUS_PATH, encoding="utf-8"))


def all_ok(data=None):
    """返回 [(平台名, 模型, base_url), ...]，只含有免费额度的。"""
    data = data or load_status()
    out = []
    for pname, pv in data["platforms"].items():
        for m, mv in pv["models"].items():
            if mv["status"] == "ok":
                out.append((pname, m, pv["base"]))
    return out


def pick(prefer=None):
    ok = all_ok()
    if prefer:
        for pn, m, b in ok:
            if m == prefer:
                return pn, m, b
    return ok[0] if ok else (None, None, None)


def chat(messages, prefer=None, max_tokens=512):
    """池内兜底：挑一个可用模型，失败就换下一个。返回 (平台, 模型, 文本)。"""
    plats = {p["name"]: p for p in _platforms()}
    ok = all_ok()
    if not ok:
        raise RuntimeError("池内没有可用模型（免费额度都尽了？）")
    if prefer:
        ok.sort(key=lambda x: x[1] != prefer)
    last = None
    for pname, model, base in ok:
        key = plats[pname]["key"]
        c, b = _req(base, key, "/chat/completions",
                    {"model": model, "messages": messages, "max_tokens": max_tokens})
        if c == 200:
            return pname, model, json.loads(b)["choices"][0]["message"]["content"]
        last = (pname, model, c, b[:150])
    raise RuntimeError(f"池内全部失败：{last}")


if __name__ == "__main__":
    if "--show" in sys.argv:
        d = load_status()
    else:
        d = probe()
    print(f"\n探测时间 {d['ts']}")
    for pname, pv in d["platforms"].items():
        ok = [m for m, v in pv["models"].items() if v["status"] == "ok"]
        ex = [m for m, v in pv["models"].items() if v["status"] == "exhausted"]
        print(f"  {pname}: 可用 {len(ok)} / 耗尽 {len(ex)}")
    print(f"合计可用：{len(all_ok(d))} 个模型")
