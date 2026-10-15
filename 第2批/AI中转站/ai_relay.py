# -*- coding: utf-8 -*-
"""个人 AI 中转站 · 本地优先

干什么：
  在本机起一个 OpenAI 风格的小网关（默认 http://127.0.0.1:8788/v1）。
  你各种客户端（聊天软件、脚本、IDE 插件）都指向它，由它按规则把请求转发到
  不同上游模型（千问 / DeepSeek / 任何兼容 OpenAI 的端点）。

为什么这么做：
  - 一个地址、一套 key 管理，换模型不用逐个改客户端
  - 数据只在你和上游之间走；中转站本身不保存你的 prompt（除非你开日志）
  - 纯标准库，不装任何第三方依赖，成本为零，可离线审计每一行

怎么用：
  1) 复制 config.example.json 为 config.json，填上游地址和 key
  2) python ai_relay.py            （或 python ai_relay.py 你的配置文件.json）
  3) 客户端 base_url 指向 http://127.0.0.1:8788/v1

路由规则（config.json 里的 routes）：
  - 客户端把 model 写成 "上游名"          -> 直接用该上游
  - 客户端把 model 写成 "上游名/真实模型"   -> 用该上游并覆盖模型名
  - model 写成 "auto" 或留空               -> 按 routes 关键字匹配，匹配不到走 default_upstream
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import free_pool          # 同目录：免费额度池（百炼 + 千问AI平台）
except Exception:
    free_pool = None

BASE = os.path.dirname(os.path.abspath(__file__))
PROMPT_KEYS = ("content",)


# ---------------- 缓存配置 / 日志 ----------------
class State:
    pass


STATE = State()
STATE.cfg = {}
STATE.log_path = None
STATE._lock = threading.Lock()


def log(msg: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    lp = STATE.log_path
    if lp:
        try:
            with STATE._lock:
                with open(lp, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass


# ---------------- 配置 ----------------
def load_config(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到配置文件：{path}")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("listen_host", "127.0.0.1")
    cfg.setdefault("listen_port", 8788)
    cfg.setdefault("upstreams", [])
    cfg.setdefault("routes", [])
    return cfg


def find_upstream(cfg: dict, name):
    if not name:
        return None
    for u in cfg.get("upstreams", []):
        if u.get("name") == name:
            return u
    return None


def last_user_text(body: dict) -> str:
    """取最后一条 user 消息的文本，用来做关键字路由。"""
    try:
        for m in reversed(body.get("messages") or []):
            if m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):  # 多段 content
                    return " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
    except Exception:
        pass
    return ""


def pick_upstream(cfg: dict, body: dict):
    """决定这条请求去哪个上游，返回 (upstream, 覆盖后的模型名 或 None)。"""
    req_model = (body.get("model") or "").strip()

    # 1) 显式 "上游名/真实模型"
    if "/" in req_model:
        name, _, real = req_model.partition("/")
        up = find_upstream(cfg, name)
        if up:
            return up, (real or up.get("model"))

    # 2) 显式 "上游名"
    up = find_upstream(cfg, req_model)
    if up:
        return up, up.get("model")

    # 3) 规则匹配（关键字 / 模型前缀）
    text = last_user_text(body)
    for r in cfg.get("routes", []):
        mt = r.get("match") or {}
        kws = mt.get("keywords") or []
        pref = mt.get("model_prefix")
        hit = (kws and any(k and k in text for k in kws)) or \
              (pref and req_model.startswith(pref))
        if hit:
            u = find_upstream(cfg, r.get("upstream"))
            if u:
                return u, u.get("model")

    # 4) 兜底：默认上游，其次第一个
    u = find_upstream(cfg, cfg.get("default_upstream")) or (cfg.get("upstreams") or [None])[0]
    return u, (u.get("model") if u else None)


# ---------------- 转发 ----------------
def _opener(up: dict):
    proxy = up.get("proxy")
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call_upstream(up: dict, body: dict):
    """把请求打到上游，返回 urllib 的响应对象（流式与否交给上层）。"""
    url = up["base_url"].rstrip("/") + "/chat/completions"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {up.get('api_key', '')}",
        "Content-Type": "application/json",
        "User-Agent": "ai-relay/1.0",
    })
    return _opener(up).open(req, timeout=up.get("timeout", 60))


# ---------------- HTTP 处理 ----------------
class RelayServer(ThreadingHTTPServer):
    """单实例锁：allow_reuse_address=False，端口被占就起不来（防双击多开）。"""
    allow_reuse_address = False
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = "ai-relay/1.0"

    def log_message(self, *a):   # 关掉默认的逐请求打印，改用我们的 log
        pass

    def _json(self, code: int, obj: dict):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self) -> bool:
        token = STATE.cfg.get("relay_token")
        if not token:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {token}"

    def _handle_pool(self, body: dict):
        """走向「免费额度池」：自动挑一个还有免费额度的模型，失败再换下一个。"""
        if free_pool is None:
            self._json(500, {"error": {"message": "free_pool 未加载"}})
            return
        prefer = (body.get("model") or "").strip()
        if prefer in ("", "auto"):
            prefer = None
        try:
            pname, model, text = free_pool.chat(body.get("messages") or [], prefer=prefer)
        except Exception as e:
            log(f"   池失败 {type(e).__name__}: {e}")
            self._json(502, {"error": {"message": f"pool error: {e}"}})
            return
        log(f"-> 池 选用 {pname}/{model}  stream={bool(body.get('stream'))}")
        created = int(time.time())
        if body.get("stream"):
            chunk = {"id": "chatcmpl-pool", "object": "chat.completion.chunk", "created": created,
                     "model": model, "provider": pname,
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": text},
                                  "finish_reason": None}]}
            done = {"id": "chatcmpl-pool", "object": "chat.completion.chunk", "created": created,
                    "model": model, "provider": pname,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            payload = (f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                       f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
                       "data: [DONE]\n\n").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self._json(200, {
            "id": "chatcmpl-pool", "object": "chat.completion", "created": created,
            "model": model, "provider": pname,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                          "finish_reason": "stop"}],
        })

    def do_GET(self):
        path = self.path.rstrip("/")
        if path == "":
            self._home()
            return
        if path == "/pool":
            self._pool()
            return
        if path == "/benefits":
            self._benefits()
            return
        if path == "/help":
            self._help()
            return
        if path == "/usage":
            self._usage()
            return
        if path in ("/healthz", "/health"):
            self._json(200, {"status": "ok", "upstreams": len(STATE.cfg.get("upstreams", []))})
            return
        if path in ("/v1/models", "/models"):
            ids = [u.get("name") for u in STATE.cfg.get("upstreams", [])] + ["auto"]
            self._json(200, {"object": "list",
                             "data": [{"id": i, "object": "model"} for i in ids]})
            return
        self._json(404, {"error": {"message": "not found"}})

    def _home(self):
        """一个简单首页，打开就能看到中转站的状态。"""
        plats, names, ts = {}, [], ""
        try:
            if free_pool is not None:
                data = free_pool.load_status()
                ts = data.get("ts", "")
                for pn, pv in data.get("platforms", {}).items():
                    ok = [m for m, v in pv["models"].items() if v["status"] == "ok"]
                    plats[pn] = len(ok)
                    names.extend(ok)
        except Exception as e:
            log(f"首页读池状态失败：{e}")
        total = sum(plats.values())
        base = f"http://127.0.0.1:{STATE.cfg.get('listen_port', '')}/v1"
        plat_rows = "".join(
            f'<div class="pr"><span>{k}</span><b>{v}</b></div>' for k, v in plats.items()
        ) or '<div class="muted">池状态还没探过，跑一次 free_pool.py</div>'
        chips = "".join(f'<span class="chip">{m}</span>' for m in names[:16]) \
            + (f'<span class="chip more">…共 {len(names)} 个</span>' if len(names) > 16 else "")
        html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 中转站 · 本地</title>
<style>
:root{{--navy:#003366;--navy2:#00264d;--orange:#FF6600;--ink:#1c2530;--muted:#5b6672;--line:#e2e7ee}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;color:var(--ink);background:#f5f7fa;line-height:1.7;-webkit-font-smoothing:antialiased}}
.hero{{background:linear-gradient(135deg,var(--navy2),var(--navy));color:#fff;padding:66px 24px 58px;text-align:center}}
.kicker{{color:#ff9a52;font-size:13px;letter-spacing:.22em;font-weight:700}}
.hero h1{{font-size:42px;margin:12px 0;font-weight:800;letter-spacing:.5px}}
.hero .pitch{{color:#c7d6e6;max-width:660px;margin:0 auto;font-size:15.5px}}
.badges{{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:20px}}
.badge{{border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:5px 14px;font-size:13px;color:#e2ecf6}}
.led{{display:inline-block;width:9px;height:9px;border-radius:50%;background:#35d07f;margin-right:7px;vertical-align:middle;box-shadow:0 0 0 4px rgba(53,208,127,.2)}}
.wrap{{max-width:1000px;margin:0 auto;padding:0 24px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(154px,1fr));gap:16px;margin:-32px 0 0}}
.metric{{background:#fff;border:1px solid var(--line);border-radius:16px;padding:20px 16px;text-align:center;box-shadow:0 10px 26px -18px rgba(0,51,102,.45)}}
.metric .n{{font-size:32px;font-weight:800;color:var(--navy)}}
.metric .t{{color:var(--muted);font-size:13px}}
h2{{color:var(--navy);font-size:20px;margin:44px 0 14px;padding-left:12px;border-left:5px solid var(--orange)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(228px,1fr));gap:16px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px 20px}}
.card h3{{margin:0 0 6px;font-size:15.5px;color:var(--navy);font-family:Consolas,monospace}}
.card p{{margin:0;color:var(--muted);font-size:13.5px}}
.pool{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 20px}}
.pr{{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding:9px 0;font-size:14.5px}}
.pr b{{color:var(--navy)}}
.chip{{display:inline-block;background:#eef3f9;color:#12395f;border-radius:8px;padding:3px 10px;margin:4px 6px 0 0;font-family:Consolas,monospace;font-size:12.5px}}
.chip.more{{background:#fff0e6;color:#b34700}}
.btn{{display:inline-block;margin-top:12px;background:var(--navy);color:#fff;text-decoration:none;border-radius:10px;padding:8px 18px;font-size:13.5px;font-weight:600}}
pre{{background:#0e2233;color:#dfe9f3;border-radius:12px;padding:16px 18px;overflow:auto;font-family:Consolas,"JetBrains Mono",monospace;font-size:13px;line-height:1.6}}
.muted{{color:var(--muted);font-size:13px}}
.foot{{color:var(--muted);font-size:12.5px;text-align:center;padding:40px 0 56px}}
.nav{{background:#fff;border-bottom:1px solid var(--line);display:flex;gap:6px;align-items:center;padding:10px 24px;position:sticky;top:0;z-index:9}}
.nav b{{color:var(--navy);font-weight:800;margin-right:10px}}
.nav a{{color:var(--muted);text-decoration:none;padding:5px 12px;border-radius:8px;font-size:13.5px}}
.nav a:hover{{background:#f0f4f8;color:var(--navy)}}
.nav a.on{{background:var(--navy);color:#fff}}
</style></head><body>
<div class="nav"><b>AI 中转站</b>
  <a class="on" href="/">首页</a><a href="/pool">模型看板</a><a href="/usage">用量</a><a href="/help">帮助</a>
</div>
<div class="hero">
  <div class="kicker">LOCAL · AI GATEWAY</div>
  <h1>AI 中转站</h1>
  <div class="pitch">一个地址，通吃你的免费额度池。百炼 + 千问AI平台里还有免费额度的模型，自动轮换；哪个额度尽就换下一个。</div>
  <div class="badges">
    <span class="badge">OpenAI 兼容</span>
    <span class="badge">本地优先 · 数据不出门</span>
    <span class="badge">失败自动切换</span>
    <span class="badge">免费额度池</span>
  </div>
</div>
<div class="wrap">
  <div class="metrics">
    <div class="metric"><div class="n">{total}</div><div class="t">可用模型</div></div>
    <div class="metric"><div class="n">{len(plats)}</div><div class="t">接入平台</div></div>
    <div class="metric"><div class="n">¥0</div><div class="t">优先走免费额度</div></div>
    <div class="metric"><div class="n">0</div><div class="t">客户端要改的地方</div></div>
  </div>

  <h2>状态</h2>
  <div class="pool">
    <div class="pr"><span><span class="led"></span>运行中</span><b>{base}</b></div>
    <div class="pr"><span class="muted">模型快照时间</span><span class="muted">{ts or '还没探过'}</span></div>
    {plat_rows}
  </div>

  <h2>可用模型（示例）</h2>
  <div class="pool">{chips or '<span class="muted">暂无</span>'}
    <div><a class="btn" href="/pool">查看全部模型看板 →</a> <a class="btn" href="/benefits" style="margin-left:8px">权益页 →</a></div>
  </div>

  <h2>接入方式</h2>
  <pre># 客户端 base_url 指向这里，model 填 auto（或指定某个模型名）
POST {base}/chat/completions
Authorization: Bearer local
Content-Type: application/json

{{"model": "auto", "messages": [{{"role": "user", "content": "你好"}}]}}</pre>

  <h2>接口</h2>
  <div class="grid">
    <div class="card"><h3>POST /v1/chat/completions</h3><p>聊天补全，OpenAI 兼容，支持流式。</p></div>
    <div class="card"><h3>GET /v1/models</h3><p>列出网关的上游名字。</p></div>
    <div class="card"><h3>GET /healthz</h3><p>健康检查，返回 status=ok。</p></div>
  </div>
</div>
<div class="foot">AI 中转站 · 本地服务，只听 127.0.0.1　|　Hanako 整理</div>
</body></html>"""
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _pool(self):
        """免费额度池看板：全部模型 + 状态。"""
        d, ts = {}, ""
        try:
            if free_pool is not None:
                d = free_pool.load_status()
                ts = d.get("ts", "")
        except Exception as e:
            log(f"看板读池状态失败：{e}")
        blocks = ""
        for pn, pv in d.get("platforms", {}).items():
            okn = sum(1 for v in pv["models"].values() if v["status"] == "ok")
            rows = ""
            for m, mv in pv["models"].items():
                pill = ('<span class="p ok">可用</span>' if mv["status"] == "ok"
                        else f'<span class="p no">{mv["status"]}</span>')
                rows += (f'<tr><td class="mono">{m}</td><td class="mono">'
                         f'{mv["http"]}</td><td>{pill}</td></tr>')
            blocks += (f'<h2>{pn} <span class="sub">可用 {okn}</span></h2>'
                       f'<table><tr><th>模型</th><th>HTTP</th><th>状态</th></tr>{rows}</table>')
        html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>免费额度池 · 看板</title>
<style>
:root{{--navy:#003366;--orange:#FF6600;--ink:#1c2530;--muted:#5b6672;--line:#e2e7ee}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;color:var(--ink);background:#f5f7fa;line-height:1.7}}
.top{{background:linear-gradient(135deg,#00264d,#003366);color:#fff;padding:34px 24px}}
.top .wrap{{max-width:1000px;margin:0 auto}}
.top a{{color:#ff9a52;text-decoration:none;font-size:13.5px}}
.top h1{{margin:8px 0 4px;font-size:26px}}
.top .sub{{color:#c7d6e6;font-size:13px}}
.wrap{{max-width:1000px;margin:0 auto;padding:8px 24px 48px}}
h2{{color:var(--navy);font-size:18px;margin:30px 0 10px;padding-left:11px;border-left:5px solid var(--orange)}}
h2 .sub{{color:var(--muted);font-weight:400;font-size:13px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:13.5px}}
th,td{{border-bottom:1px solid var(--line);padding:8px 12px;text-align:left}}
th{{background:var(--navy);color:#fff;font-weight:600;font-size:12.5px}}
tr:nth-child(even) td{{background:#fafbfd}}
.mono{{font-family:Consolas,"JetBrains Mono",monospace}}
.muted{{color:var(--muted)}}
.p{{display:inline-block;font-size:12px;padding:2px 10px;border-radius:999px;font-weight:700}}
.p.ok{{background:#e9f2ee;color:#1f7a53}}
.p.no{{background:#ffe9e9;color:#a11}}
</style></head><body>
<div class="top"><div class="wrap">
  <a href="/">← 返回中转站</a>
  <h1>免费额度池 · 看板</h1>
  <div class="sub">快照时间 {ts or '还没探过'}　|　绿=还有免费额度，红=已耗尽/不可用</div>
</div></div>
<div class="wrap">{blocks or '<p class="muted">还没有池数据，跑一次 free_pool.py。</p>'}</div>
</body></html>"""
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _benefits(self):
        """仿千问AI平台「权益」页：摘要卡 + 可筛选的模型状态表。"""
        d = {}
        try:
            if free_pool is not None:
                d = free_pool.load_status()
        except Exception as e:
            log(f"权益页读池状态失败：{e}")
        plats = d.get("platforms", {})
        ts = d.get("ts", "")
        rows, okn, non, pset = "", 0, 0, []
        for pn, pv in plats.items():
            pset.append(pn)
            for m, mv in pv["models"].items():
                ok = mv["status"] == "ok"
                okn += 1 if ok else 0
                non += 0 if ok else 1
                pill = ('<span class="p ok">可用</span>' if ok
                        else f'<span class="p no">{mv["status"]}</span>')
                rows += (f'<tr data-p="{pn}" data-ok="{1 if ok else 0}">'
                         f'<td class="mono">{m}</td><td>{pn}</td>'
                         f'<td class="mono">{mv["http"]}</td><td>{pill}</td></tr>')
        total = okn + non
        pchips = ('<button class="f on" data-t="p" data-v="*">全部平台</button>'
                  + "".join(f'<button class="f" data-t="p" data-v="{p}">{p}</button>' for p in pset))
        html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>权益 · 免费额度池</title>
<style>
:root{{--navy:#003366;--orange:#FF6600;--ink:#1c2530;--muted:#5b6672;--line:#e2e7ee}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;color:var(--ink);background:#f5f7fa;line-height:1.7}}
.top{{background:linear-gradient(135deg,#00264d,#003366);color:#fff;padding:34px 24px}}
.top .wrap,.wrapx{{max-width:1000px;margin:0 auto}}
.top a{{color:#ff9a52;text-decoration:none;font-size:13.5px}}
.top h1{{margin:8px 0 4px;font-size:26px}}
.top .sub{{color:#c7d6e6;font-size:13px}}
.wrapx{{padding:0 24px 48px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin:-26px 0 0}}
.card{{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px;text-align:center;box-shadow:0 10px 26px -18px rgba(0,51,102,.45)}}
.card .n{{font-size:30px;font-weight:800;color:var(--navy)}}
.card .n.o{{color:var(--orange)}}
.card .t{{color:var(--muted);font-size:13px}}
.filters{{margin:24px 0 10px;display:flex;flex-wrap:wrap;gap:8px}}
.f{{border:1px solid var(--line);background:#fff;color:var(--muted);border-radius:999px;padding:5px 14px;font-size:13px;cursor:pointer}}
.f.on{{background:var(--navy);color:#fff;border-color:var(--navy)}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:13.5px}}
th,td{{border-bottom:1px solid var(--line);padding:8px 12px;text-align:left}}
th{{background:var(--navy);color:#fff;font-weight:600;font-size:12.5px}}
tr:nth-child(even) td{{background:#fafbfd}}
.mono{{font-family:Consolas,"JetBrains Mono",monospace}}
.p{{display:inline-block;font-size:12px;padding:2px 10px;border-radius:999px;font-weight:700}}
.p.ok{{background:#e9f2ee;color:#1f7a53}}
.p.no{{background:#ffe9e9;color:#a11}}
</style></head><body>
<div class="top"><div class="wrap">
  <a href="/">← 返回中转站</a>
  <h1>权益 · 免费额度池</h1>
  <div class="sub">快照 {ts or '还没探过'}　|　仿千问AI平台权益页；剩余额度/到期时间需登录平台才看得到，这里用「可用/不可用」代替</div>
</div></div>
<div class="wrapx">
  <div class="cards">
    <div class="card"><div class="n">{okn}</div><div class="t">可用模型</div></div>
    <div class="card"><div class="n o">{non}</div><div class="t">不可用</div></div>
    <div class="card"><div class="n">{total}</div><div class="t">探测总数</div></div>
    <div class="card"><div class="n">{len(pset)}</div><div class="t">平台数</div></div>
  </div>
  <div class="filters">
    {pchips}
    <button class="f on" data-t="s" data-v="*">全部状态</button>
    <button class="f" data-t="s" data-v="1">可用</button>
    <button class="f" data-t="s" data-v="0">不可用</button>
  </div>
  <table><thead><tr><th>模型</th><th>平台</th><th>HTTP</th><th>状态</th></tr></thead><tbody>{rows}</tbody></table>
</div>
<script>
let fp=null, fs=null;
function apply(){{document.querySelectorAll('tbody tr').forEach(function(tr){{
  var a=!fp||tr.dataset.p===fp, b=!fs||tr.dataset.ok===fs;
  tr.style.display=(a&&b)?'':'none';}});}}
document.querySelectorAll('.f').forEach(function(b){{b.onclick=function(){{
  var t=b.dataset.t;
  b.parentElement.querySelectorAll('.f[data-t="'+t+'"]').forEach(function(x){{x.classList.remove('on');}});
  b.classList.add('on');
  var v=b.dataset.v;
  if(t==='p'){{fp=(v==='*')?null:v;}}else{{fs=(v==='*')?null:v;}}
  apply();}};}});
</script>
</body></html>"""
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _help(self):
        """服务须知：怎么接、怎么用、规则。"""
        base = f"http://127.0.0.1:{STATE.cfg.get('listen_port', '')}/v1"
        html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>帮助 · AI 中转站</title>
<style>
:root{{--navy:#003366;--orange:#FF6600;--muted:#5b6672;--line:#e2e7ee}}
body{{font-family:"Noto Sans SC","Microsoft YaHei",sans-serif;color:#1c2530;background:#f5f7fa;margin:0;line-height:1.8}}
.wrap{{max-width:820px;margin:0 auto;padding:0 24px 48px}}
.nav{{background:#fff;border-bottom:1px solid var(--line);display:flex;gap:6px;align-items:center;padding:10px 24px;position:sticky;top:0}}
.nav b{{color:var(--navy);margin-right:10px}} .nav a{{color:var(--muted);text-decoration:none;padding:5px 12px;border-radius:8px;font-size:13.5px}} .nav a.on{{background:var(--navy);color:#fff}}
h1{{color:var(--navy);font-size:26px;margin:26px 0 8px}}
h2{{color:var(--navy);font-size:18px;margin:26px 0 8px;padding-left:11px;border-left:5px solid var(--orange)}}
code{{background:#eef3f9;color:#12395f;padding:1px 6px;border-radius:5px;font-family:Consolas,monospace;font-size:13px}}
pre{{background:#0e2233;color:#dfe9f3;border-radius:12px;padding:14px 16px;overflow:auto;font-family:Consolas,monospace;font-size:12.5px;line-height:1.6}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;margin:8px 0}} th,td{{border:1px solid var(--line);padding:7px 10px;text-align:left}} th{{background:var(--navy);color:#fff}}
.muted{{color:var(--muted);font-size:13px}}
</style></head><body>
<div class="nav"><b>AI 中转站</b><a href="/">首页</a><a href="/pool">模型看板</a><a href="/usage">用量</a><a class="on" href="/help">帮助</a></div>
<div class="wrap">
<h1>服务须知</h1>
<h2>1. 怎么接</h2>
<p>客户端 base_url 填 <code>{base}</code>；key 随便填（本地不需鉴权）。</p>
<pre>POST {base}/chat/completions
Authorization: Bearer local
Content-Type: application/json

{{"model": "auto", "messages": [{{"role": "user", "content": "你好"}}]}}</pre>
<h2>2. model 怎么写</h2>
<table>
<tr><th>写法</th><th>效果</th></tr>
<tr><td><code>auto</code> 或留空</td><td>自动从免费池挑一个还有额度的模型</td></tr>
<tr><td><code>上游名</code></td><td>指定某个平台</td></tr>
<tr><td><code>上游名/模型名</code></td><td>指定平台并覆盖模型名</td></tr>
</table>
<h2>3. 免费额度池</h2>
<p>把「百炼 + 千问AI平台」里还有免费额度的模型聚合起来；哪个返回 403（额度尽）就自动换下一个。</p>
<h2>4. 接口</h2>
<table>
<tr><th>接口</th><th>用途</th></tr>
<tr><td><code>POST /v1/chat/completions</code></td><td>聊天（OpenAI 兼容，支持流式）</td></tr>
<tr><td><code>GET /v1/models</code></td><td>列出上游</td></tr>
<tr><td><code>GET /healthz</code></td><td>健康检查</td></tr>
</table>
<h2>5. 边界</h2>
<p class="muted">只听 127.0.0.1；只转发，不存你的 prompt；免费额度用完会自动跳过。</p>
</div></body></html>"""
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _usage(self):
        """用量：统计 relay.log 里各平台被选中转发的次数。"""
        cnt = {}
        lp = STATE.log_path
        try:
            if lp and os.path.exists(lp):
                for ln in open(lp, encoding="utf-8", errors="ignore"):
                    if "选用" in ln:
                        tail = ln.split("选用")[-1].strip().split()
                        if tail:
                            plat = tail[0].split("/")[0]
                            cnt[plat] = cnt.get(plat, 0) + 1
        except Exception as e:
            log(f"用量统计失败：{e}")
        total = sum(cnt.values())
        rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>"
                       for k, v in sorted(cnt.items(), key=lambda x: -x[1]))
        html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>用量 · AI 中转站</title>
<style>
:root{{--navy:#003366;--orange:#FF6600;--muted:#5b6672;--line:#e2e7ee}}
body{{font-family:"Noto Sans SC","Microsoft YaHei",sans-serif;color:#1c2530;background:#f5f7fa;margin:0;line-height:1.8}}
.wrap{{max-width:760px;margin:0 auto;padding:0 24px 48px}}
.nav{{background:#fff;border-bottom:1px solid var(--line);display:flex;gap:6px;align-items:center;padding:10px 24px;position:sticky;top:0}}
.nav b{{color:var(--navy);margin-right:10px}} .nav a{{color:var(--muted);text-decoration:none;padding:5px 12px;border-radius:8px;font-size:13.5px}} .nav a.on{{background:var(--navy);color:#fff}}
h1{{color:var(--navy);font-size:26px;margin:26px 0 8px}}
.big{{font-size:34px;font-weight:800;color:var(--navy)}}
table{{width:100%;border-collapse:collapse;font-size:14px;margin-top:10px}} th,td{{border:1px solid var(--line);padding:8px 12px;text-align:left}} th{{background:var(--navy);color:#fff}}
.muted{{color:var(--muted);font-size:13px}} .foot{{color:var(--muted);font-size:12.5px;margin-top:24px}}
</style></head><body>
<div class="nav"><b>AI 中转站</b><a href="/">首页</a><a href="/pool">模型看板</a><a class="on" href="/usage">用量</a><a href="/help">帮助</a></div>
<div class="wrap">
<h1>用量</h1>
<div class="big">{total}</div>
<div class="muted">累计转发次数（读 relay.log）</div>
<table><tr><th>平台</th><th>次数</th></tr>{rows or '<tr><td colspan=2 class="muted">还没有调用记录</td></tr>'}</table>
<div class="foot">只统计本机网关转发出去的请求；不含你直接调用上游的次数。</div>
</div></body></html>"""
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        path = self.path.rstrip("/")
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._json(404, {"error": {"message": "not found"}})
            return
        if not self._authorized():
            self._json(401, {"error": {"message": "unauthorized"}})
            return
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._json(400, {"error": {"message": f"bad json: {e}"}})
            return

        up, model = pick_upstream(STATE.cfg, body)
        if not up:
            self._json(500, {"error": {"message": "没有任何可用上游，请检查 config.json"}})
            return
        # 特殊上游：免费额度池（自动挑一个还有免费额度的模型）
        if up.get("type") == "pool":
            self._handle_pool(body)
            return
        if model:
            body["model"] = model
        stream = bool(body.get("stream"))
        log(f"-> {up.get('name')}  model={body.get('model')}  stream={stream}")

        try:
            resp = call_upstream(up, body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:500]
            log(f"   上游 HTTP {e.code}: {detail}")
            self._json(e.code, {"error": {"message": detail}})
            return
        except Exception as e:
            log(f"   上游异常 {type(e).__name__}: {e}")
            self._json(502, {"error": {"message": f"{type(e).__name__}: {e}"}})
            return

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", resp.headers.get("Content-Type", "text/event-stream"))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    chunk = resp.read(1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except Exception as e:
                log(f"   流式传输中断：{e}")
            finally:
                resp.close()
        else:
            payload = resp.read()
            resp.close()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)


def serve(cfg: dict, log_path=None):
    """建好服务器并返回（不阻塞）。调用方自己决定 serve_forever 还是放线程。"""
    STATE.cfg = cfg
    STATE.log_path = log_path or cfg.get("log_path")
    if STATE.log_path and not os.path.isabs(STATE.log_path):
        STATE.log_path = os.path.join(BASE, STATE.log_path)
    try:
        httpd = RelayServer((cfg["listen_host"], int(cfg["listen_port"])), Handler)
    except OSError:
        print(f"[!] 端口 {cfg['listen_port']} 已被占用，可能已有一个网关在跑。本进程退出。")
        sys.exit(3)
    return httpd


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "config.json")
    try:
        cfg = load_config(cfg_path)
    except Exception as e:
        print(f"[×] 读取配置失败：{e}")
        print("    -> 先把 config.example.json 复制成 config.json，填好上游和 key。")
        sys.exit(1)
    if not cfg.get("upstreams"):
        print("[!] config.json 里还没有任何上游，先填一个再用。")
    httpd = serve(cfg)
    host, port = httpd.server_address[:2]
    log(f"AI 中转站已启动：http://{host}:{port}/v1  （Ctrl+C 停止）")
    for u in cfg.get("upstreams", []):
        log(f"   上游 {u.get('name')} -> {u.get('base_url')}  model={u.get('model')}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("收到停止信号，关闭中…")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
