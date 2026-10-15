"""微信本地数据读取模块（只读）
====================================
从已解密的数据库中读取群列表和消息。

用法：
    db = WeChatDB(r".\微信监控\\解密")
    for g in db.groups(10):
        print(g.name, g.username, g.unread)
    for m in db.messages("xxxxx@chatroom", limit=30):
        print(m.time_str, m.sender, m.text)

不修改微信任何数据，全部走只读连接。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import os
import re
import sqlite3
from dataclasses import dataclass, field

try:
    import zstandard as zstd
except ImportError:  # 没装也不炸，只是压缩消息读不了
    zstd = None

X8 = "\x08"


@dataclass
class Message:
    local_id: int
    timestamp: int
    sender: str          # 显示名
    sender_id: str       # wxid
    kind: str            # text / image / voice / emoji / quote / system / other
    text: str
    is_mine: bool = False   # 是不是我自己发的

    @property
    def time_str(self) -> str:
        return dt.datetime.fromtimestamp(self.timestamp).strftime("%m-%d %H:%M")


@dataclass
class Group:
    name: str
    username: str
    last_ts: int
    unread: int
    table: str
    dbfile: str
    member_count: int = 0
    aliases: list = field(default_factory=list)

    @property
    def last_str(self) -> str:
        return dt.datetime.fromtimestamp(self.last_ts).strftime("%m-%d %H:%M")


class WeChatDB:
    def __init__(self, base_dir: str, my_wxid: str = ""):
        self.base = base_dir
        self.session_path = os.path.join(base_dir, "session", "session.db")
        self.cfts_path = os.path.join(base_dir, "contact", "contact_fts.db")
        self.msg_dir = os.path.join(base_dir, "message")
        self.my_wxid = my_wxid          # 我自己的 wxid，用于判断“这句是不是我发的”
        self._names = None
        self._tabs = None
        self._my_ids = None

    # ---------- 基建 ----------
    @staticmethod
    def _ro(p: str) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True)

    def my_rowids(self) -> dict:
        """每个 message 库里我自己的 real_sender_id。{库路径: rowid}"""
        if self._my_ids is not None:
            return self._my_ids
        m: dict = {}
        if self.my_wxid:
            for db in ("message_0.db", "message_1.db", "message_2.db"):
                p = os.path.join(self.msg_dir, db)
                if not os.path.exists(p):
                    continue
                try:
                    c = self._ro(p)
                    row = c.execute(
                        "SELECT rowid FROM Name2Id WHERE user_name=?",
                        (self.my_wxid,)).fetchone()
                    m[p] = row[0] if row else None
                    c.close()
                except Exception:
                    m[p] = None
        self._my_ids = m
        return m

    def names(self) -> dict:
        """username -> (显示名, kind)；kind 1=人 2=群"""
        if self._names is not None:
            return self._names
        m = {}
        c = self._ro(self.cfts_path)
        ids = {r: u for r, u in c.execute("SELECT rowid, username FROM name2id")}
        # 主名：contact_fts_v5_content
        for rid, c0, c1 in c.execute("SELECT id, c0, c1 FROM contact_fts_v5_content"):
            u = ids.get(rid)
            if not u:
                continue
            parts = [p for p in (c0 or "").split(X8) if p]
            m[u] = (parts[0] if parts else u, c1)
        c.close()
        self._names = m
        return m

    def msg_tables(self) -> dict:
        """Msg_xxx 表名 -> [所在库路径]（同一会话可能分散在多个库）"""
        if self._tabs is not None:
            return self._tabs
        m: dict = {}
        for db in ("message_0.db", "message_1.db", "message_2.db", "biz_message_0.db"):
            p = os.path.join(self.msg_dir, db)
            if not os.path.exists(p):
                continue
            c = self._ro(p)
            for (t,) in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg\\_%' ESCAPE '\\'"):
                m.setdefault(t, []).append(p)
            c.close()
        self._tabs = m
        return m

    @staticmethod
    def table_of(username: str) -> str:
        return "Msg_" + hashlib.md5(username.encode()).hexdigest()

    # ---------- 群 ----------
    def groups(self, limit: int = 50) -> list:
        names = self.names()
        tabs = self.msg_tables()
        out = []
        c = self._ro(self.session_path)
        rows = c.execute(
            """SELECT username, last_timestamp, unread_count FROM SessionTable
               WHERE last_timestamp > 0 ORDER BY last_timestamp DESC""").fetchall()
        c.close()
        for u, ts, unread in rows:
            if not u.endswith("@chatroom"):
                continue
            t = self.table_of(u)
            paths = tabs.get(t)
            if not paths:
                continue
            nm = names.get(u, (u, 2))[0]
            out.append(Group(nm, u, ts, unread, t, paths[0]))
            if len(out) >= limit:
                break
        return out

    def find_group(self, keyword: str) -> list:
        """按名字模糊找一个群"""
        kw = keyword.strip()
        return [g for g in self.groups(500) if kw and kw in g.name]

    def rowid_names(self) -> dict:
        """{库路径: {real_sender_id: username}}，用来反查发送者。"""
        if getattr(self, "_rid_names", None) is not None:
            return self._rid_names
        m: dict = {}
        for db in ("message_0.db", "message_1.db", "message_2.db"):
            p = os.path.join(self.msg_dir, db)
            if not os.path.exists(p):
                continue
            try:
                c = self._ro(p)
                m[p] = {r: u for r, u in
                        c.execute("SELECT rowid, user_name FROM Name2Id")}
                c.close()
            except Exception:
                m[p] = {}
        self._rid_names = m
        return m

    def private_sessions(self, limit: int = 300) -> list:
        """私聊（1对1）会话列表。排除群、公众号、系统号。"""
        names = self.names()
        tabs = self.msg_tables()
        out = []
        c = self._ro(self.session_path)
        rows = c.execute(
            """SELECT username, last_timestamp, unread_count FROM SessionTable
               WHERE last_timestamp > 0 ORDER BY last_timestamp DESC""").fetchall()
        c.close()
        for u, ts, unread in rows:
            if not u or u.endswith("@chatroom"):        # 群
                continue
            if u.startswith("gh_"):                     # 公众号
                continue
            if u.startswith("brandservice") or u.startswith("brandsession"):
                continue
            if u in ("filehelper", "weixin", "notifymessage", "fmessage",
                      "floatbottle", "newsapp", "masssendapp", "medianote"):
                continue
            if "@openim" in u or "@kefu" in u or "@weclaw" in u:
                continue
            if u == self.my_wxid:
                continue
            t = self.table_of(u)
            paths = tabs.get(t)
            if not paths:
                continue
            nm = names.get(u, (u, 1))[0]
            out.append(Group(nm, u, ts, unread, t, paths[0]))
            if len(out) >= limit:
                break
        return out

    def find_private(self, keyword: str) -> list:
        """按名字 / wxid 找一个私聊"""
        kw = (keyword or "").strip()
        if not kw:
            return []
        return [s for s in self.private_sessions(500)
                if kw in s.name or kw in s.username]

    # ---------- 消息 ----------
    def messages(self, username: str, limit: int = 50, since: int | None = None) -> list:
        tabs = self.msg_tables()
        t = self.table_of(username)
        paths = tabs.get(t) or []
        if not paths:
            return []
        names = self.names()

        rows = []
        for p in paths:
            c = self._ro(p)
            sql = (f'SELECT local_id, create_time, real_sender_id, local_type, '
                   f'message_content, WCDB_CT_message_content FROM "{t}"')
            params: list = []
            if since:
                sql += " WHERE create_time > ?"
                params.append(since)
            sql += " ORDER BY create_time DESC LIMIT ?"
            params.append(limit)
            try:
                rows.extend((p, *r) for r in c.execute(sql, params).fetchall())
            except Exception:
                pass
            c.close()

        rows.sort(key=lambda r: r[2])
        rows = rows[-limit:]

        my = self.my_rowids()
        n2i = self.rowid_names()
        out = []
        for p, lid, ts, rsid, lt, content, ct in rows:
            sid, text, kind = self.parse_content(content, ct)
            is_mine = my.get(p) is not None and rsid == my.get(p)
            # 显示名：优先用消息前缀，其次是 real_sender_id 反查
            display = names.get(sid, (sid, 1))[0] if sid else ""
            if not display and rsid:
                u = (n2i.get(p) or {}).get(rsid, "")
                if u and u != self.my_wxid:
                    display = names.get(u, (u, 1))[0]
                elif u == self.my_wxid:
                    is_mine = True
            if not sid and rsid:
                sid = (n2i.get(p) or {}).get(rsid, "")
            out.append(Message(lid, ts, display, sid, kind, text, is_mine))
        return out

    @staticmethod
    def parse_content(content, ct) -> tuple:
        """返回 (发送者标识, 文本, 类型)"""
        raw = content
        if isinstance(content, (bytes, bytearray)) and ct == 4:
            if zstd is None:
                return "", "<压缩消息，缺 zstandard 库>", "error"
            try:
                raw = zstd.ZstdDecompressor().decompress(content)
            except Exception:
                try:
                    with zstd.ZstdDecompressor().stream_reader(io.BytesIO(content)) as r:
                        raw = r.read()
                except Exception:
                    return "", "<解压失败>", "error"
        s = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)

        # 第一步：剥掉 "发送者标识:" 前缀（可能是 wxid，也可能是群昵称）
        sender = ""
        m = re.match(r"^([^:\n]{1,64}):[ \t]?\n?", s)
        if m:
            sender = m.group(1).strip()
            s = s[m.end():]

        # 第二步：按内容形态分类
        b = s.strip()
        if not b.startswith("<"):
            return sender, b.replace("\n", " "), "text"

        if "<img" in b:
            return sender, "[图片]", "image"
        if "<voicemsg" in b:
            return sender, "[语音]", "voice"
        if "<emoji" in b:
            return sender, "[表情]", "emoji"
        if "<sysmsg" in b:
            mt = re.search(r"<template><!\[CDATA\[(.*?)\]\]></template>", b, re.S)
            return "", f"[系统] {mt.group(1)[:60]}" if mt else "[系统消息]", "system"
        mt = re.search(r"<title>(.*?)</title>", b, re.S)
        if mt:
            return sender, f"[引用] {mt.group(1).strip()[:80]}", "quote"
        return sender, b[:80], "other"


if __name__ == "__main__":
    db = WeChatDB(r".\微信监控\解密")
    print("最近活跃的群：")
    for g in db.groups(10):
        print(f"  {g.name:<28} {g.username:<24} {g.last_str}  未读 {g.unread}")
    print()
    for g in db.groups(3):
        print(f"=== {g.name} ===")
        for m in db.messages(g.username, limit=5):
            who = m.sender + ": " if m.sender else ""
            print(f"  {m.time_str}  {who}{m.text[:60]}")
