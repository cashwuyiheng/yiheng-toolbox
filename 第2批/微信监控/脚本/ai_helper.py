"""AI 调用 helper —— 分级 + 自动降级 + 失败升级

思路
----
1) 每家 provider 标一个档位 tier:
     fast  = 便宜快（日常摘要、话题提炼）
     smart = 更强更贵（读长文档、做判断、写文章）

2) 调用时指定 task，helper 按 task_tier 决定先用哪一档:
     chat(cfg, prompt, task="summary")   -> 先 fast
     chat(cfg, prompt, task="analysis")  -> 先 smart

3) 同一档里的 provider 按顺序试；都失败了，且 allow_escalate=true，
   就自动升到 smart 档再试一遍。

配置示例（微信监控配置.json）
    "ai": {
      "task_tier": {"summary": "fast", "topic": "fast",
                    "analysis": "smart", "writing": "smart"},
      "allow_escalate": true,
      "providers": [
        {"name":"千问flash","tier":"fast","base_url":"...","api_key":"...","model":"qwen3.8-flash"},
        {"name":"DeepSeek","tier":"fast","base_url":"...","api_key":"...","model":"deepseek-chat"},
        {"name":"千问max","tier":"smart","base_url":"...","api_key":"...","model":"qwen3.8-max"}
      ]
    }

兼容老结构：providers 里没有 tier 的，一律当 fast；也能读单家结构。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

FAST, SMART = "fast", "smart"

# 国内大模型接口（千问 / DeepSeek）直连最稳。
# 走系统代理（Clash）时经常 RemoteDisconnected / IncompleteRead
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _one(provider: dict, prompt: str, timeout: int, temperature: float,
         max_tokens: int | None = None, json_mode: bool = False) -> str:
    base = (provider.get("base_url") or "").rstrip("/")
    key = provider.get("api_key") or ""
    model = provider.get("model") or ""
    if not (base and key and model):
        raise ValueError(f"provider 配置不全: {provider.get('name', '?')}")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if json_mode:
        # 千问 / DeepSeek 都支持 OpenAI 兼容的 json_object
        payload["response_format"] = {"type": "json_object"}

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    with _NO_PROXY.open(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    return (data.get("choices", [{}])[0]
            .get("message", {}).get("content", "") or "").strip()


def _providers(cfg: dict) -> list:
    ai = cfg.get("ai") or {}
    provs = ai.get("providers")
    if not provs:
        provs = [ai] if ai.get("base_url") else []
    out = []
    for p in provs:
        q = dict(p)
        q.setdefault("tier", FAST)
        q.setdefault("name", q.get("model") or "?")
        out.append(q)
    return out


def _tier_of(p: dict) -> str:
    return (p.get("tier") or FAST).lower()


def _wanted_tier(cfg: dict, task: str | None) -> str:
    ai = cfg.get("ai") or {}
    mapping = ai.get("task_tier") or {}
    if task and task in mapping:
        return str(mapping[task]).lower()
    return FAST


def _looks_ok(text: str, min_len: int = 2) -> bool:
    """极简的质量闸：空 or 过短都当失败。"""
    return bool(text) and len(text.strip()) >= min_len


def chat(cfg: dict, prompt: str, task: str | None = None,
         timeout: int = 180, temperature: float = 0.3,
         max_tokens: int | None = None,
         allow_escalate: bool | None = None,
         json_mode: bool = False) -> tuple:
    """返回 (文本, 实际使用的provider名)。

    task        : 任务类型，用来决定先走哪一档（见 task_tier）
    allow_escalate: 同一档全失败后，是否升到 smart 档重试。
                    默认读配置里的 ai.allow_escalate（缺省 True）
    """
    ai = cfg.get("ai") or {}
    provs = _providers(cfg)
    if not provs:
        raise RuntimeError("没有配置任何 AI 通道")

    want = _wanted_tier(cfg, task)
    if allow_escalate is None:
        allow_escalate = ai.get("allow_escalate", True)

    # 排序：目标档优先；其余按原顺序跟在后面
    ordered = ([p for p in provs if _tier_of(p) == want]
               + [p for p in provs if _tier_of(p) != want])
    if not allow_escalate:
        ordered = [p for p in ordered if _tier_of(p) == want]

    errors = []
    for p in ordered:
        name = p.get("name")
        try:
            text = _one(p, prompt, timeout, temperature, max_tokens, json_mode)
            if _looks_ok(text):
                if _tier_of(p) != want:
                    print(f"     ⤴ 已升到 {_tier_of(p)} 档：{name}")
                return text, name
            errors.append(f"{name}: 返回过短/为空")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "ignore")[:120]
            except Exception:
                pass
            errors.append(f"{name}: HTTP {e.code} {detail}")
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}")

    raise RuntimeError("所有 AI 通道都失败了 -> " + " | ".join(errors))


def describe(cfg: dict) -> str:
    provs = _providers(cfg)
    if not provs:
        return "未配置"
    fast = [p["name"] for p in provs if _tier_of(p) == FAST]
    smart = [p["name"] for p in provs if _tier_of(p) == SMART]
    parts = []
    if fast:
        parts.append("快档: " + " → ".join(fast))
    if smart:
        parts.append("强档: " + " → ".join(smart))
    return "  |  ".join(parts) if parts else "未配置"
