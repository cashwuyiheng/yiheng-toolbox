"""微信群消息监控 · 定时扫描 + 摘要 + 推手机
============================================================
用法：
    python wechat_monitor.py                  # 扫一次
    python wechat_monitor.py --loop 900       # 常驻，每 900 秒扫一次
    python wechat_monitor.py --no-push        # 只打印不推送
    python wechat_monitor.py --init           # 只建基线：把当前消息全部标记为已读

配置：微信监控\\微信监控配置.json
状态：微信监控\\数据\\微信监控状态.json
推送：复用 quant 探索\\脚本\\push.py 的通道配置

依赖：zstandard（解压长消息）
前提：Clash 开着，微信在运行
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 微信监控\
CONFIG_PATH = os.path.join(BASE, "微信监控配置.json")
DATA_DIR = os.path.join(BASE, "数据")
STATE_PATH = os.path.join(DATA_DIR, "微信监控状态.json")
LOG_PATH = os.path.join(DATA_DIR, "微信消息流水.csv")

# 复用 quant 探索 的 push.py
QUANT_DIR = os.path.join(os.path.dirname(BASE), "quant 探索", "脚本")
sys.path.insert(0, QUANT_DIR)
sys.path.insert(0, os.path.join(BASE, "脚本"))

try:
    import push as push_mod
except Exception:
    push_mod = None

from wechat_reader import WeChatDB  # noqa: E402
import ai_helper  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------- 配置 / 状态 ----------------
def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        print(f"缺少配置：{CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"seen": {}}          # username -> [最后时间戳, 最后 local_id]


def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 解密 ----------------
def _run_tool(tool: str, args: list, timeout: int = 300):
    try:
        return subprocess.run([sys.executable, tool] + args,
                              capture_output=True, encoding="utf-8",
                              errors="replace", timeout=timeout,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        print(f"  命令执行失败：{type(e).__name__}: {e}")
        return None


def wechat_running(cfg: dict = None) -> bool:
    """微信还在不在。查不到就当作在，宁可漏报也不误报。

    注意：tasklist 是控制台程序。本监控用 pythonw 无声启动（无控制台），
    若不给子进程加 CREATE_NO_WINDOW，Windows 会另开一个控制台窗口，
    每轮都会在屏幕上闪一下。这里必须带这个标志。
    """
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, encoding="gbk", errors="replace", timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode != 0:
            return True          # 权限不足等，不误判成“微信没了”
        return "weixin.exe" in (r.stdout or "").lower()
    except Exception:
        return True


def verify_decrypt(cfg: dict) -> bool:
    """解密后验证：关键库能打开、表能读。不看工具的措辞，看实际结果。"""
    try:
        p = os.path.join(cfg["decrypt_dir"], "session", "session.db")
        if not os.path.exists(p):
            return False
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        n = con.execute("SELECT COUNT(*) FROM SessionTable").fetchone()[0]
        con.close()
        return n > 0
    except Exception:
        return False


def redecrypt(cfg: dict) -> bool:
    """重新解密（2~3 秒）。失败则自动重扫密钥再试。"""
    tool = cfg["tool_path"]

    def _decrypt() -> bool:
        r = _run_tool(tool, ["decrypt",
                             "--db-dir", cfg["source_db_dir"],
                             "--keys", cfg["keys_file"],
                             "--output", cfg["decrypt_dir"]])
        if r is None:
            return False
        for line in (r.stdout or "").splitlines()[-3:]:
            print(f"  {line}")
        return verify_decrypt(cfg)

    if _decrypt():
        return True

    # 验证不过 = 密钥多半失效了（微信重登后会换密钥）
    print("  [!] 解密结果不可用，密钥可能已失效，尝试重新扫一次…")
    if not wechat_running(cfg):
        print("  [!] 微信没在运行，扫不到新密钥。请启动并登录微信。")
        return False

    r2 = _run_tool(tool, ["extract",
                          "--db-dir", cfg["source_db_dir"],
                          "--output", cfg["keys_file"]], timeout=600)
    if r2 is None:
        return False
    txt = (r2.stdout or "") + (r2.stderr or "")
    if "found key" in txt:
        print("  [√] 密钥已刷新，用新密钥重试…")
        return _decrypt()
    print("  [!] 重扫密钥也没成功。")
    return False


# ---------------- AI 摘要 ----------------
def summarize(cfg: dict, group_name: str, msgs: list) -> str:
    """把一段群消息交给 AI 压成要点。失败返回空字符串。"""
    ai = cfg.get("ai") or {}
    if not (ai.get("providers") or ai.get("base_url")):
        return ""
    lines = [f"[{m.time_str}] {m.sender or '?'}: {m.text}" for m in msgs if m.text]
    if not lines:
        return ""
    digest = "\n".join(lines)[-6000:]
    prompt = (
        "下面是微信群里最近的一段消息。\n"
        "如果这段内容全是闲聊、寒暄、广告、推销、无信息量的内容，只回复两个字母：SKIP\n"
        "否则按下面格式回复：\n"
        "1) 一句话概括大家在聊什么\n"
        "2) 最多 3 条要点（只保留有信息量的，闲聊忽略）\n"
        "3) 如果有需要我行动的事项，单独列出，没有就写“无”\n"
        f"\n群名：{group_name}\n消息：\n{digest}"
    )
    try:
        text, used = ai_helper.chat(cfg, prompt, task="summary", timeout=90)
        if used:
            print(f"     （AI: {used}）")
        return text
    except Exception as e:
        print(f"  AI 摘要失败：{e}")
        return ""


# ---------------- 主扫描 ----------------
def scan_once(cfg: dict, state: dict, use_push: bool, init_only: bool = False) -> int:
    print(f"[{now_str()}] 重新解密…")
    if not redecrypt(cfg):
        # 解密失败要出声，不能默默跳过
        if use_push and push_mod:
            push_mod.send("⚠️ 微信监控出问题了",
                          "解密失败，无法读取微信消息。\n"
                          "常见原因：微信重新登录后密钥变了，或微信没在运行。\n"
                          f"时间：{now_str()}")
        print("  [!] 已尝试自动恢复，仍失败。本轮跳过并已告警。")
        return 0

    if not wechat_running(cfg):
        print("  微信进程不在，数据不会更新（本轮仍按现存数据扫）。")

    db = WeChatDB(cfg["decrypt_dir"], my_wxid=detect_my_wxid(cfg))
    seen = state.setdefault("seen", {})
    total_new = 0
    initial_hours = int(cfg.get("initial_hours", 6))

    # 要监控哪些群：配置里有就按名字找，空 = 全部
    wanted = cfg.get("groups") or []
    if wanted:
        groups = []
        for want in wanted:
            hits = db.find_group(want)
            if not hits:
                print(f"  [×] 找不到群：{want}")
            groups.extend(hits)
    else:
        groups = db.groups(400)
        print(f"  （未指定群名，监控全部：{len(groups)} 个群）")

    # 忽略清单：营销群、门店群直接不看
    ignore = cfg.get("ignore_groups") or []
    if ignore:
        before = len(groups)
        groups = [g for g in groups if not any(k in g.name for k in ignore)]
        if before != len(groups):
            print(f"  （按忽略清单跳过 {before - len(groups)} 个群）")

    for g in groups:
        last = seen.get(g.username)
        if last:
            since, last_id = last[0], last[1]
        else:
            since = int(time.time()) - initial_hours * 3600
            last_id = 0
        msgs = db.messages(g.username, since=since, limit=300)
        msgs = [m for m in msgs if (m.timestamp, m.local_id) > (since, last_id)]
        if not msgs:
            continue
        total_new += len(msgs)
        print(f"\n  【{g.name}】{len(msgs)} 条新消息")
        for m in msgs:
            who = f"{m.sender}: " if m.sender else ""
            print(f"     {m.time_str}  {who}{m.text[:60]}")

        if init_only:
            pass
        else:
            append_log(g.name, g.username, msgs)
            if use_push:
                mode = cfg.get("push_mode", "instant")
                pri = [m for m in msgs if is_priority(m.sender, m.sender_id, cfg)]
                normal = [m for m in msgs
                          if not is_priority(m.sender, m.sender_id, cfg)]

                # 路一：重点联系人，任何模式下都立即推（强提醒）
                if pri and push_mod:
                    bell = "🔔🔔 " if cfg.get("priority_sound") else ""
                    title = f"{bell}{g.name} · 重点 {len(pri)} 条"
                    body = format_body(g.name, pri, cfg, db)
                    if body:
                        for name, ok, info in push_mod.send(title, body, urgent=True):
                            print(f"     🔔 推送 {name} {'✅' if ok else '❌'} {info}")

                # 路二：普通消息。instant 就立即推
                if mode == "instant" and normal and push_mod:
                    title = f"📱 {g.name} · {len(normal)} 条新消息"
                    body = format_body(g.name, normal, cfg, db)
                    if body is None:
                        print("     （AI 判定是闲聊/广告，不推）")
                    else:
                        for name, ok, info in push_mod.send(title, body):
                            print(f"     推送 {name} {'✅' if ok else '❌'} {info}")

                # 路二（hourly / both）：攼起来等汇总
                if mode in ("hourly", "both") and normal:
                    pending = state.setdefault("pending", {})
                    pending.setdefault(g.name, []).extend(
                        _msg_to_dict(m) for m in normal)
                    print(f"     攼入汇总池（{len(normal)} 条）")

                if not push_mod and not init_only:
                    print("     （push.py 不可用，未推送）")

        last_msg = max(msgs, key=lambda m: (m.timestamp, m.local_id))
        seen[g.username] = [last_msg.timestamp, last_msg.local_id]

    if init_only:
        print(f"\n  基线已建立，共标记 {total_new} 条。下次起只报新消息。")
    save_state(state)
    return total_new


def format_body(group_name: str, msgs: list, cfg: dict, db):
    """拼推送正文。AI 判定不值得推时返回 None。"""
    ai_text = ""
    wants_ai = bool(cfg.get("use_ai"))
    if wants_ai:
        ai_text = summarize(cfg, group_name, msgs)
        if cfg.get("ai_filter") and ai_text.strip().upper().startswith("SKIP"):
            return None
    lines = []
    if ai_text:
        lines.append(ai_text)
        lines.append("──────────")
    elif wants_ai:
        # AI 没生成出来要说一声，不能让你默默收到一堆没头绪的原文
        lines.append("⚠️ 这次的 AI 摘要没生成出来，下面是原始消息")
        lines.append("──────────")
    for m in msgs[-15:]:
        who = f"{m.sender}: " if m.sender else ""
        lines.append(f"{m.time_str} {who}{m.text[:100]}")
    return "\n".join(lines)


def detect_my_wxid(cfg: dict) -> str:
    """找出我自己的 wxid：配置优先，否则从数据目录名里抠。"""
    if cfg.get("my_wxid"):
        return cfg["my_wxid"]
    m = re.search(r"(wxid_[A-Za-z0-9]+)", cfg.get("source_db_dir", "") or "")
    return m.group(1) if m else ""


def is_priority(sender: str, sender_id: str, cfg: dict) -> bool:
    """这个消息是不是重点联系人发的。"""
    pats = [p for p in (cfg.get("priority_contacts") or []) if p]
    if not pats:
        return False
    hay = f"{sender or ''}|{sender_id or ''}"
    return any(p in hay for p in pats)


def _msg_to_dict(m) -> dict:
    return {"i": m.local_id, "t": m.timestamp, "s": m.sender,
            "sid": m.sender_id, "k": m.kind, "x": m.text}


def _dict_to_msg(d: dict):
    from wechat_reader import Message
    return Message(d.get("i", 0), d.get("t", 0), d.get("s", ""),
                   d.get("sid", ""), d.get("k", "text"), d.get("x", ""))


ARCHIVE_PATH = os.path.join(DATA_DIR, "话题存档.json")
ARCHIVE_KEEP_HOURS = 72      # 存档保留多久


def _parse_topics(raw: str) -> list:
    """把 AI 返回的 JSON 解析成话题列表，尽量容错。"""
    txt = (raw or "").strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
    data = None
    try:
        data = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = None
    if not isinstance(data, dict):
        return []
    out = []
    for t in (data.get("topics") or []):
        if not isinstance(t, dict):
            continue
        ids = t.get("ids") or []
        if not isinstance(ids, list):
            continue
        clean = []
        for i in ids:
            s = str(i).strip()
            if s.isdigit():
                clean.append(int(s))
        out.append({
            "group": str(t.get("group") or "").strip(),
            "title": str(t.get("title") or "").strip(),
            "ids": clean,
        })
    return out


def load_archive() -> list:
    if not os.path.exists(ARCHIVE_PATH):
        return []
    try:
        with open(ARCHIVE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def save_archive(batches: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    cut = int(time.time()) - ARCHIVE_KEEP_HOURS * 3600
    keep = [b for b in batches if b.get("ts", 0) >= cut]
    with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False, indent=1)


def flush_pending(cfg: dict, state: dict, use_push: bool = True) -> int:
    """把攼着的消息按话题分类：存档 + 只推送话题目录。"""
    pending = state.get("pending") or {}
    state["last_flush"] = int(time.time())
    if not pending:
        return 0

    total = sum(len(v) for v in pending.values())
    ngroup = len(pending)
    print(f"\n[{now_str()}] 汇总推送：{ngroup} 个群 / {total} 条")

    # 1. 给每条消息编号
    numbered = []
    n = 0
    for gname, items in pending.items():
        for it in items:
            n += 1
            numbered.append((n, gname, it))

    lines = []
    for i, gname, it in numbered:
        t = dt.datetime.fromtimestamp(it.get("t", 0)).strftime("%H:%M")
        lines.append(f"[{i}] [{gname}] {t} {it.get('s') or '?'}: {it.get('x', '')}")
    digest = "\n".join(lines)[-10000:]

    prompt = (
        "下面是编号过的微信群消息。请把它们按【话题】归类。\n"
        "只输出严格的 JSON，不要 markdown 代码块，不要多余文字：\n"
        '{"topics":[{"group":"群名","title":"话题标题","ids":[编号]}]}\n'
        "规则：\n"
        "- 同一个话题的消息归到一起，ids 写它们的编号\n"
        "- 每个群最多 3 个话题\n"
        "- 纯闲聊、没实质内容的群直接省略\n"
        "- title 控制在 15 字以内，能一眼看出在聊什么\n"
        f"\n消息：\n{digest}"
    )

    topics = []
    if cfg.get("use_ai"):
        try:
            raw, used = ai_helper.chat(cfg, prompt, task="topic", timeout=180,
                                       json_mode=True)
            print(f"     （AI 汇总: {used}）")
            topics = _parse_topics(raw)
        except Exception as e:
            print(f"  AI 汇总失败：{e}")

    # 2. 组装存档（话题 -> 消息明细）
    by_id = {i: (gname, it) for i, gname, it in numbered}
    batch = {"ts": int(time.time()), "time_str": now_str(), "topics": []}
    for k, t in enumerate(topics, 1):
        msgs = []
        for i in t["ids"]:
            if i in by_id:
                gname, it = by_id[i]
                msgs.append({"g": gname, **it})
        if not msgs:
            continue
        batch["topics"].append({
            "id": f"T{k}",
            "group": t["group"] or (msgs[0].get("g") or ""),
            "title": t["title"] or "(未命名话题)",
            "count": len(msgs),
            "msgs": msgs,
        })

    if batch["topics"]:
        arch = load_archive()
        arch.append(batch)
        save_archive(arch)

    # 3. 推送：只有话题目录
    if batch["topics"]:
        body = "\n".join(
            f"{t['id']} [{t['group']}] {t['title']}（{t['count']}条）"
            for t in batch["topics"])
        body += "\n\n想看哪个话题的详细消息，回我编号就行"
    elif total > 0:
        # 有消息，但 AI 没提炼出来 → 要告诉你，不能静默吞掉
        body = (f"⚠️ 这一小时有 {ngroup} 个群、{total} 条消息，"
                f"但 AI 总结没做出来（接口或网络问题）。\n"
                f"消息没丢，都在流水里。")
    else:
        body = "（这一小时没什么值得提的话题）"

    print("  ----- 话题目录 -----")
    for ln in body.splitlines():
        print("  " + ln)

    if use_push and push_mod:
        title = f"📊 近一小时话题 · {len(batch['topics'])} 个"
        for name, ok, info in push_mod.send(title, body):
            print(f"     推送 {name} {'✅' if ok else '❌'} {info}")

    state["pending"] = {}
    save_state(state)
    return total


def append_log(group_name: str, username: str, msgs: list):
    import csv
    os.makedirs(DATA_DIR, exist_ok=True)
    new_file = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["抓取时间", "群名", "会话ID", "消息时间", "发送者", "类型", "内容"])
        for m in msgs:
            w.writerow([now_str(), group_name, username, m.time_str,
                        m.sender, m.kind, m.text])


# 纯应答词白名单（去掉表情后长度≤8 且在这里面的，算“不需要回”）
TRIVIAL_WORDS = {
    "好", "好的", "好吧", "好滴", "好嘞", "好的好的", "行", "可以", "可以可以",
    "对", "对的", "是", "是的", "嗯", "嗯嗯", "嗯呢", "晓得", "知道了",
    "收到", "谢谢", "多谢", "感谢", "麻烦了", "辛苦", "辛苦了",
    "哈哈", "哈哈哈", "哈", "哦", "哦哦", "噢", "呢",
    "ok", "okok", "okay", "okk", "OK", "👌", "👍", "🆗",
    "没问题", "没事", "没事儿", "晚安", "早安", "明天见", "再聊",
    "牛逼", "牛", "强", "厉害", "不错", "可以啦", "那就这样", "辛苦啦",
}


def is_trivial_reply(msg) -> bool:
    """纯应答/表情，不算“等你回复”（不提醒）。

    算trivial的情况：
      - 表情消息（[表情]这类）
      - 整句全是 [xx] 表情
      - 去掉表情后很短，且每个词都是应答词（好 / 嗯 / ok / 收到…）
      - 整句只有符号/emoji，没有任何中文/字母/数字（如 👌🏻、〜〜）
    不算trivial的：图片、语音、以及任何有实际内容的句子（宁可多提醒）
    """
    t = (msg.text or "").strip()
    if not t:
        return True
    # 图片/语音可能有真内容（图纸、报价、口述事情），不当应答
    if msg.kind in ("image", "voice"):
        return False
    if msg.kind == "emoji":
        return True
    rest = re.sub(r"\[[^\]]{1,12}\]", "", t).strip()
    if not rest:
        return True          # 全是表情
    compact = re.sub(r"\s+", "", rest)
    if len(compact) <= 12 and compact.lower() in TRIVIAL_WORDS:
        return True
    # 拆成词，每个词都是应答词
    parts = [p for p in re.split(r"[\s,，。！!?？~·、]+", rest) if p]
    if parts and len(rest) <= 16 and all(p.lower() in TRIVIAL_WORDS for p in parts):
        return True
    # 纯符号 / emoji，没有实际字符
    if not re.search(r"[\u4e00-\u9fff\w]", rest):
        return True
    return False


def check_private_replies(cfg: dict, db, state: dict, use_push: bool = True) -> int:
    """盯私聊：对方发来消息，超过 N 分钟我没回，就提醒。

    返回本轮新提醒的数量。
    """
    pa = cfg.get("private_alert") or {}
    if not pa.get("enabled"):
        return 0
    contacts = [c for c in (pa.get("contacts") or []) if c]
    if not contacts:
        return 0

    minutes = int(pa.get("minutes", 5))
    alert_after = minutes * 60
    # 提醒过一次后，多久之内不再打扰（分钟）
    quiet_sec = int(pa.get("quiet_minutes", 30)) * 60
    # 等太久就不提了（小时）——几个月前的老消息没意义
    max_wait_sec = int(pa.get("max_wait_hours", 12)) * 3600
    now = int(time.time())
    alerted = state.setdefault("private_alerted", {})
    fired = 0

    for sess in db.private_sessions(400):
        if not any(c in sess.name or c in sess.username for c in contacts):
            continue
        msgs = db.messages(sess.username, limit=30)
        if not msgs:
            continue

        # 找出“我上次回复之后”对方发的所有消息
        group = []
        for m in reversed(msgs):
            if m.is_mine:
                break
            group.append(m)
        group.reverse()
        group = [m for m in group if m.kind != "system"]

        # 我已是最后发言，没欠别人话
        if not group:
            alerted.pop(sess.username, None)
            continue

        # 按时间间隔切分成多波对话：中间断开超过 GAP 就是两波
        # （避免几个月前的老消息把今天的新消息拖下水）
        GAP = int(pa.get("session_gap_hours", 6)) * 3600
        waves = []
        cur = []
        for m in group:
            if cur and m.timestamp - cur[-1].timestamp > GAP:
                waves.append(cur)
                cur = []
            cur.append(m)
        if cur:
            waves.append(cur)

        # 只看最近这一波
        wave = waves[-1]

        # 这一波全是表情/短应答 → 不打扰（他在收尾，不是找你）
        if all(is_trivial_reply(m) for m in wave):
            alerted.pop(sess.username, None)
            continue

        # 计时起点用这一波里“第一条实质消息”，而不是最后那个收尾表情
        first = next((m for m in wave if not is_trivial_reply(m)), wave[0])
        tail = wave[-1]
        waited = now - first.timestamp
        if waited < alert_after:
            continue
        # 等太久（默认超 12 小时）就不提了——对话已经凉了
        if waited > max_wait_sec:
            alerted.pop(sess.username, None)
            continue

        # 提醒过的记录：{"id": 提醒的那句, "ts": 提醒时间}
        rec = alerted.get(sess.username)
        if isinstance(rec, dict):
            quiet_until = rec.get("ts", 0) + quiet_sec
            if now < quiet_until:
                continue                     # 静默期内，不再打扰
            if rec.get("id") == tail.local_id:
                continue                     # 最后一句没变，提醒过了
        elif rec is not None:
            continue                         # 兼容老格式，已提过就不再提

        mins = waited // 60
        title = f"🔔🔔 还没回：{sess.name}"
        body = (f"{sess.name} 在 {tail.time_str} 给你发了消息，"
                f"已经等了 {mins} 分钟。\n\n"
                f"他/她说：{tail.text[:120]}")
        print(f"\n  🔔 待回复提醒：{sess.name}（等了 {mins} 分钟）")
        if use_push and push_mod:
            for name, ok, info in push_mod.send(title, body, urgent=True):
                print(f"     推送 {name} {'✅' if ok else '❌'} {info}")
        alerted[sess.username] = {"id": tail.local_id, "ts": now}
        fired += 1

    if fired:
        save_state(state)
    return fired


# 单实例锁：防止重复启动的进程互相覆盖进度
_LOCK_SOCK = None
LOCK_PORT = 49527


def acquire_single_instance():
    """本机端口占用即视为已有实例在跑。进程退出时操作系统自动释放。"""
    global _LOCK_SOCK
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
    except OSError:
        print(f"[!] 已经有一个监控在运行（{LOCK_PORT} 端口被占）。")
        print("    不用重复开，否则两个进程会互相冲掉进度。")
        sys.exit(1)
    _LOCK_SOCK = s


def main():
    ap = argparse.ArgumentParser(description="微信群消息监控")
    ap.add_argument("--loop", type=int, default=0,
                    help="常驻模式，间隔秒数（不给则用配置里的 interval_sec）")
    ap.add_argument("--no-push", action="store_true", help="只打印不推送")
    ap.add_argument("--init", action="store_true", help="只建基线，不推送")
    ap.add_argument("--log", default="", help="同时把输出写进这个文件（相对路径基于 微信监控\\)")
    args = ap.parse_args()

    # 后台运行时没有控制台，把输出写进日志文件
    if args.log:
        lp = args.log if os.path.isabs(args.log) else os.path.join(BASE, args.log)
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        _f = open(lp, "a", encoding="utf-8", buffering=1)

        class _Tee:
            def write(self, s):
                try:
                    _f.write(s)
                except Exception:
                    pass
                return len(s)

            def flush(self):
                try:
                    _f.flush()
                except Exception:
                    pass

            def isatty(self):
                return False

        sys.stdout = _Tee()
        sys.stderr = sys.stdout
        print(f"\n{'=' * 60}\n[{now_str()}] 监控启动（日志模式）")

    cfg = load_config()
    state = load_state()
    use_push = not args.no_push

    # 没指定 --loop 就用配置里的间隔
    if args.loop is None or args.loop == 0:
        args.loop = int(cfg.get("interval_sec", 900))

    if not args.loop:
        scan_once(cfg, state, use_push, init_only=args.init)
        return

    interval = max(60, args.loop)
    acquire_single_instance()
    print(f"微信群监控启动：每 {interval} 秒一次。Ctrl+C 停止。")
    cfg = load_config()
    mode = cfg.get("push_mode", "instant")
    hourly = int(cfg.get("hourly_minutes", 60)) * 60
    print(f"推送模式：{mode}（汇总周期 {hourly // 60} 分钟）")
    if state.get("last_flush") is None:
        state["last_flush"] = int(time.time())
        save_state(state)
    init_pending = args.init
    try:
        while True:
            cfg = load_config()
            mode = cfg.get("push_mode", "instant")
            hourly = int(cfg.get("hourly_minutes", 60)) * 60
            try:
                scan_once(cfg, state, use_push, init_only=init_pending)
            except Exception as e:
                print(f"  本轮异常：{type(e).__name__}: {e}")
            init_pending = False

            # 待回复提醒：只在第一轮之后开始盯
            if use_push:
                try:
                    check_private_replies(cfg, WeChatDB(cfg["decrypt_dir"],
                                                        my_wxid=detect_my_wxid(cfg)),
                                          state, use_push)
                except Exception as e:
                    print(f"  私聊检查异常：{type(e).__name__}: {e}")

            # 到点了就把攼着的消息汇总推一条
            if use_push and mode in ("hourly", "both"):
                last = state.get("last_flush") or int(time.time())
                if time.time() - last >= hourly:
                    try:
                        flush_pending(cfg, state, use_push)
                    except Exception as e:
                        print(f"  汇总异常：{type(e).__name__}: {e}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
