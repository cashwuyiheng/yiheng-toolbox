# -*- coding: utf-8 -*-
"""163 邮箱监控：定时拉新邮件 -> 过滤 -> AI 摘要 -> 企业微信推送。

用法
----
    python 邮箱监控.py                 # 跑一轮
    python 邮箱监控.py --test           # 只测 IMAP 登录，不读信、不推送
    python 邮箱监控.py --init           # 只建基线（把当前最新 UID 记账），不推送
    python 邮箱监控.py --loop 300       # 每 300 秒一轮（常驻）
    python 邮箱监控.py --loop 300 --log "..\\数据\\monitor.log"

前提
----
163 邮箱已开启 IMAP，并拿到「客户端授权码」（不是登录密码）。
授权码写进配置里 auth_code_file 指向的文件，本脚本只读、不打印、不外传。
"""
from __future__ import annotations

import argparse
import email
import email.header
import email.utils
import imaplib
import json
import os
import re
import socket
import sys
import time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE, "邮箱监控配置.json")
DATA_DIR = os.path.join(BASE, "数据")
STATE_PATH = os.path.join(DATA_DIR, "状态.json")
MAIL_LOG = os.path.join(DATA_DIR, "邮件流水.jsonl")

# 复用微信监控的 AI 分级通道和企业微信推送，避免密钥和代码各存一份
WX_SCRIPT_DIR = r".\微信监控\脚本"
if WX_SCRIPT_DIR not in sys.path:
    sys.path.insert(0, WX_SCRIPT_DIR)

# 163 的 IMAP 要求客户端先发 ID 声明身份，否则 SELECT 会报 "Unsafe Login"
imaplib.Commands["ID"] = ("AUTH", "SELECTED")

_LOCK_PORT = 49531
_LOCK_SOCK = None


def log(msg, logfile=None):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    if logfile:
        try:
            with open(logfile, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def acquire_single_instance():
    """本机端口占用即视为已有实例在跑。进程退出时系统自动释放。"""
    global _LOCK_SOCK
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", _LOCK_PORT))
        s.listen(1)
    except OSError:
        print(f"[!] 已经有一个邮箱监控在运行（{_LOCK_PORT} 端口被占）。")
        sys.exit(1)
    _LOCK_SOCK = s


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("email"):
        raise SystemExit("配置里 email 还没填。打开 邮箱监控配置.json，把 email 填成你的完整地址。")
    return cfg


def load_ai_cfg(cfg):
    """AI 配置：本文件内嵌 ai 优先；否则从 ai_config_file 借用。"""
    if cfg.get("ai"):
        return cfg
    path = cfg.get("ai_config_file")
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                other = json.load(f)
            if other.get("ai"):
                return other
        except Exception:
            pass
    return {}


def read_auth_code(cfg):
    p = cfg.get("auth_code_file", "")
    if not p:
        raise SystemExit("配置里没写 auth_code_file。")
    if not os.path.isfile(p):
        raise SystemExit(
            f"找不到授权码文件：{p}\n"
            "请把 163 的客户端授权码存成这个文件（文件里只写那一串码）。"
        )
    with open(p, "r", encoding="utf-8-sig") as f:
        code = f.read().strip()
    if not code:
        raise SystemExit(f"授权码文件是空的：{p}")
    return code


def _dec(s):
    if not s:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(s)))
    except Exception:
        return str(s)


def send_id(M, name="XiaoHuaMailMonitor", version="1.0.0", vendor="XiaoHua"):
    """163 专属：登录后必须发一次 ID，声明客户端身份。"""
    args = ("name", name, "version", version, "vendor", vendor)
    typ, dat = M._simple_command("ID", '("' + '" "'.join(args) + '")')
    try:
        M._untagged_response(typ, dat, "ID")
    except Exception:
        pass
    return typ


def connect(cfg):
    user = cfg["email"]
    code = read_auth_code(cfg)
    host = cfg.get("imap_host", "imap.163.com")
    port = int(cfg.get("imap_port", 993))
    M = imaplib.IMAP4_SSL(host, port)
    M.login(user, code)
    send_id(M)
    return M


def load_state():
    if os.path.isfile(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_uid": 0, "pending": [], "last_digest_ts": 0}


def save_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def fetch_new(M, cfg, state):
    """按 UID 增量抓新邮件的头部（只取头部，省流量、避开 163 频控）。"""
    mailbox = cfg.get("mailbox", "INBOX")
    M.select(mailbox, readonly=True)
    typ, data = M.uid("search", None, "ALL")
    if typ != "OK" or not data or not data[0]:
        return []
    uids = [int(x) for x in data[0].split()]
    last = int(state.get("last_uid") or 0)

    if last == 0:
        # 首次运行：最多回看最近 300 封，避免一次抓几千封
        fresh = uids[-300:]
        initial = int(cfg.get("initial_hours", 6) or 0)
        cutoff = datetime.now().astimezone() - timedelta(hours=initial) if initial else None
    else:
        fresh = [u for u in uids if u > last]
        cutoff = None

    if not fresh:
        return []

    out = []
    for uid in fresh:
        typ, d = M.uid("fetch", str(uid), "(BODY.PEEK[HEADER])")
        if typ != "OK" or not d or not isinstance(d[0], tuple):
            continue
        msg = email.message_from_bytes(d[0][1])
        dt = None
        if msg.get("Date"):
            try:
                dt = email.utils.parsedate_to_datetime(msg.get("Date"))
            except Exception:
                dt = None
        if cutoff and dt and dt < cutoff:
            continue
        who = _dec(msg.get("From"))
        name, addr = email.utils.parseaddr(who)
        out.append({
            "uid": uid,
            "from": _dec(name) or addr or who,
            "addr": addr,
            "subject": _dec(msg.get("Subject")).replace("\n", " ").strip() or "(无标题)",
            "date": dt.strftime("%m-%d %H:%M") if dt else "",
            "ts": dt.timestamp() if dt else 0,
        })
        time.sleep(0.15)  # 温柔一点，别把 163 惹毛

    state["last_uid"] = max(uids)
    return out


def is_ignored(mail, cfg):
    hay = ((mail.get("addr") or "") + " " + (mail.get("from") or "")).lower()
    if any(kw and kw.lower() in hay for kw in cfg.get("ignore_senders", [])):
        return True
    subj = mail.get("subject") or ""
    return any(kw and kw in subj for kw in cfg.get("ignore_subject_keywords", []))


def classify(mail, cfg):
    """ignore=直接扔；instant=立即单推；digest=进每小时汇总。"""
    if is_ignored(mail, cfg):
        return "ignore"
    if is_important(mail, cfg):
        return "instant"
    return "digest"


def is_important(mail, cfg):
    hay = (mail.get("subject") or "") + " " + (mail.get("from") or "")
    return any(kw and kw in hay for kw in cfg.get("important_keywords", []))


def push(content, logfile=None):
    try:
        from wecom_app_send import get_token, send_app
        tok = get_token()
        r = send_app(tok, content)
        if r.get("errcode") == 0:
            log("   推送成功。", logfile)
            return True
        log(f"   推送失败: {json.dumps(r, ensure_ascii=False)}", logfile)
        return False
    except Exception as e:
        log(f"   推送异常: {type(e).__name__}: {e}", logfile)
        return False


def build_digest(mails, ai_cfg, logfile=None):
    lines = [f'{m["from"]} | {m["date"]} | {m["subject"]}' for m in mails]
    body = "\n".join(lines)
    head = f"收件箱新增 {len(mails)} 封："
    if not (ai_cfg and ai_cfg.get("ai")):
        return head + "\n" + body
    try:
        import ai_helper
        prompt = (
            "你是邮件助理。下面是某邮箱最近的新邮件（发件人 | 时间 | 标题）。\n"
            "请用中文输出一个简短汇总，分两段：\n"
            "【要处理的】验证码、账单、登录/安全提醒、打新中签认购、资金变动、人工来信等；\n"
            "【可忽略的】广告、促销、系统通知等。\n"
            "每条一行，不超过 40 字。只依据标题判断，不要编造正文内容；判断不了就照实写。\n\n"
            f"{body}"
        )
        text, _who = ai_helper.chat(ai_cfg, prompt, task="summary", max_tokens=800)
        return f"【邮箱】新增 {len(mails)} 封\n{text}"
    except Exception as e:
        log(f"   AI 摘要失败（{type(e).__name__}），改为原文列表。", logfile)
        return head + "\n" + body


def scan(cfg, limit=120):
    """只看不推：列出最近 N 封的头部，并统计发件人分布。"""
    from collections import Counter
    M = connect(cfg)
    rows = []
    try:
        M.select(cfg.get("mailbox", "INBOX"), readonly=True)
        typ, data = M.uid("search", None, "ALL")
        uids = [int(x) for x in data[0].split()] if data and data[0] else []
        for uid in uids[-int(limit):]:
            typ, d = M.uid("fetch", str(uid), "(BODY.PEEK[HEADER])")
            if typ != "OK" or not d or not isinstance(d[0], tuple):
                continue
            msg = email.message_from_bytes(d[0][1])
            who = _dec(msg.get("From"))
            name, addr = email.utils.parseaddr(who)
            dtx = ""
            if msg.get("Date"):
                try:
                    dtx = email.utils.parsedate_to_datetime(msg.get("Date")).strftime("%m-%d %H:%M")
                except Exception:
                    pass
            rows.append((addr or who, _dec(name), _dec(msg.get("Subject")).strip(), dtx))
            time.sleep(0.15)
    finally:
        try:
            M.logout()
        except Exception:
            pass

    groups = {"instant": [], "digest": [], "ignore": []}
    for r in rows:
        groups[classify({"addr": r[0], "from": r[1], "subject": r[2]}, cfg)].append(r)

    for key, title in (("instant", "命中关键词、会立即单推"),
                       ("digest", "只进每小时汇总"),
                       ("ignore", "按规则直接忽略")):
        print(f"\n=== {title}（{len(groups[key])} 封）===")
        for addr, name, subj, dtx in groups[key]:
            print(f"{dtx:<12} {addr:<38} | {subj[:60]}")

    cnt = Counter(r[0] for r in rows)
    print(f"\n=== 发件人分布（共 {len(rows)} 封）===")
    for addr, n in cnt.most_common():
        print(f"{n:>4}  {addr}")


def _payload_text(part):
    try:
        data = part.get_payload(decode=True)
    except Exception:
        return ""
    if not data:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return data.decode(charset, "ignore")
    except Exception:
        return data.decode("utf-8", "ignore")


def _body_text(msg, max_chars=4000):
    """取正文：优先 text/plain，退而求其次 text/html（去标签）。"""
    def _clean(t):
        t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
        t = re.sub(r"(?s)<[^>]+>", " ", t)
        t = (t.replace("&nbsp;", " ").replace("&amp;", "&")
              .replace("&lt;", "<").replace("&gt;", ">"))
        return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()

    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition") or "")
            if part.get_content_type() == "text/plain" and "attachment" not in disp:
                return _clean(_payload_text(part))[:max_chars]
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return _clean(_payload_text(part))[:max_chars]
        return ""
    return _clean(_payload_text(msg))[:max_chars]


def read_one(cfg, uid, max_chars=4000):
    """拆一封邮件：打印头部 + 正文 + 附件清单。"""
    M = connect(cfg)
    try:
        M.select(cfg.get("mailbox", "INBOX"), readonly=True)
        typ, d = M.uid("fetch", str(uid), "(RFC822)")
        if typ != "OK" or not d or not isinstance(d[0], tuple):
            print(f"没取到 UID={uid} 的邮件。")
            return
        msg = email.message_from_bytes(d[0][1])
        print(f"UID:     {uid}")
        print(f"From:    {_dec(msg.get('From'))}")
        print(f"To:      {_dec(msg.get('To'))}")
        print(f"Date:    {msg.get('Date')}")
        print(f"Subject: {_dec(msg.get('Subject'))}")
        atts = []
        for part in msg.walk():
            fn = part.get_filename()
            if fn:
                atts.append(f"{_dec(fn)} ({part.get_content_type()})")
        if atts:
            print("附件:    " + "; ".join(atts))
        print("-" * 60)
        print(_body_text(msg, max_chars))
    finally:
        try:
            M.logout()
        except Exception:
            pass


def save_attachments(cfg, uid, out_dir=None):
    """把某封邮件的附件存到 数据/附件/<uid>/ 下。"""
    out_dir = out_dir or os.path.join(DATA_DIR, "附件", str(uid))
    os.makedirs(out_dir, exist_ok=True)
    M = connect(cfg)
    saved = []
    try:
        M.select(cfg.get("mailbox", "INBOX"), readonly=True)
        typ, d = M.uid("fetch", str(uid), "(RFC822)")
        if typ != "OK" or not d or not isinstance(d[0], tuple):
            print(f"没取到 UID={uid} 的邮件。")
            return saved
        msg = email.message_from_bytes(d[0][1])
        for part in msg.walk():
            fn = part.get_filename()
            if not fn:
                continue
            fn = re.sub(r'[\\/:*?"<>|]', "_", _dec(fn))
            data = part.get_payload(decode=True) or b""
            path = os.path.join(out_dir, fn)
            with open(path, "wb") as f:
                f.write(data)
            saved.append(path)
    finally:
        try:
            M.logout()
        except Exception:
            pass
    for p in saved:
        print(f"已保存: {p}  ({os.path.getsize(p)} 字节)")
    return saved


def run_once(cfg, ai_cfg, state, logfile=None, do_push=True, init_only=False):
    try:
        M = connect(cfg)
    except SystemExit:
        raise
    except imaplib.IMAP4.error as e:
        log(f"IMAP 登录失败: {e}", logfile)
        log("  常见原因：① 没开 IMAP；② 填的是登录密码而不是授权码；③ 授权码已重置。", logfile)
        return
    except Exception as e:
        log(f"连接失败: {type(e).__name__}: {e}", logfile)
        return

    try:
        mails = fetch_new(M, cfg, state)
    finally:
        try:
            M.logout()
        except Exception:
            pass

    if init_only:
        save_state(state)
        log(f"[init] 基线已建立，最新 UID = {state['last_uid']}", logfile)
        return

    if not mails:
        log("没有新邮件。", logfile)
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MAIL_LOG, "a", encoding="utf-8") as f:
        for m in mails:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    kept = [m for m in mails if not is_ignored(m, cfg)]
    log(f"新邮件 {len(mails)} 封，忽略 {len(mails) - len(kept)} 封，保留 {len(kept)} 封。", logfile)

    mode = cfg.get("push_mode", "both")
    if do_push and mode in ("instant", "both"):
        for m in kept:
            if is_important(m, cfg):
                push(f'【邮箱·重要】{m["from"]}：{m["subject"]}\n{m["date"]}', logfile)
                time.sleep(0.5)

    state["pending"].extend(kept)
    now = time.time()
    due = (now - float(state.get("last_digest_ts") or 0)) >= int(cfg.get("digest_minutes", 60)) * 60

    if not do_push:
        state["pending"] = []
    elif mode in ("digest", "both") and state["pending"] and due:
        if push(build_digest(state["pending"], ai_cfg, logfile), logfile):
            state["pending"] = []
            state["last_digest_ts"] = now

    save_state(state)


def main():
    ap = argparse.ArgumentParser(description="163 邮箱监控")
    ap.add_argument("--loop", type=int, default=0, help="常驻模式，间隔秒数")
    ap.add_argument("--test", action="store_true", help="只测 IMAP 登录")
    ap.add_argument("--scan", type=int, default=0, metavar="N",
                    help="只看不推：列出最近 N 封并统计发件人")
    ap.add_argument("--read", type=int, default=0, metavar="UID",
                    help="打印某封邮件的正文（按 UID）")
    ap.add_argument("--att", type=int, default=0, metavar="UID",
                    help="把某封邮件的附件存到 数据/附件/<UID>/")
    ap.add_argument("--init", action="store_true", help="只建基线，不推送")
    ap.add_argument("--no-push", action="store_true", help="只打印不推送")
    ap.add_argument("--log", default="", help="同时写进这个日志文件")
    args = ap.parse_args()

    logfile = args.log or None
    if logfile and not os.path.isabs(logfile):
        logfile = os.path.join(BASE, logfile)

    cfg = load_config()
    ai_cfg = load_ai_cfg(cfg)

    if args.att:
        save_attachments(cfg, args.att)
        return

    if args.read:
        read_one(cfg, args.read)
        return

    if args.scan:
        scan(cfg, args.scan)
        return

    if args.test:
        M = connect(cfg)
        typ, data = M.select(cfg.get("mailbox", "INBOX"), readonly=True)
        n = data[0].decode() if data and data[0] else "?"
        try:
            M.logout()
        except Exception:
            pass
        log(f"登录成功 ✓ 收件箱共 {n} 封。", logfile)
        return

    acquire_single_instance()
    interval = args.loop or int(cfg.get("interval_sec", 300))
    state = load_state()

    while True:
        try:
            run_once(cfg, ai_cfg, state, logfile,
                     do_push=not args.no_push, init_only=args.init)
        except SystemExit:
            raise
        except Exception as e:
            log(f"本轮出错: {type(e).__name__}: {e}", logfile)
        if args.loop <= 0:
            break
        log(f"休眠 {interval} 秒...", logfile)
        time.sleep(interval)


if __name__ == "__main__":
    main()
