"""群日报：时间线 + 话题，一份出两段。
用法：
    python daily_report.py 叮咚探世界          # 今天
    python daily_report.py 叮咚探世界 2        # 最近 2 天
"""
import datetime as dt
import json
import sys
import urllib.request

sys.path.insert(0, r".\微信监控\脚本")
from wechat_reader import WeChatDB  # noqa: E402
from wechat_monitor import load_config  # noqa: E402

BASE = r".\微信监控\解密"
MAX_CHARS = 26000


def call_ai(cfg, prompt):
    ai = cfg["ai"]
    body = json.dumps({
        "model": ai.get("model", "deepseek-chat"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }).encode("utf-8")
    url = ai["base_url"].rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ai['api_key']}",
    })
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    return data["choices"][0]["message"]["content"].strip()


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else "叮咚探世界"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    db = WeChatDB(BASE)
    cfg = load_config()
    hits = [g for g in db.groups(120) if keyword in g.name]
    if not hits:
        print("没找到群:", keyword)
        return
    g = hits[0]

    now = dt.datetime.now()
    start = (now.replace(hour=0, minute=0, second=0, microsecond=0)
             - dt.timedelta(days=days - 1))
    since = int(start.timestamp())
    msgs = db.messages(g.username, since=since, limit=4000)
    texts = [m for m in msgs if m.text and m.kind in ("text", "quote")]

    span = start.strftime("%m-%d") if days > 1 else "今天"
    print(f"群：{g.name}   {span}   消息 {len(msgs)} 条（可读 {len(texts)} 条）")
    print("生成日报中…\n")

    digest = "\n".join(f"[{m.time_str}] {m.sender or '?'}: {m.text}" for m in texts)
    if len(digest) > MAX_CHARS:
        digest = digest[:MAX_CHARS] + "\n…（已截断）"

    prompt = (
        "下面是某个微信群的聊天记录。请输出一份给群主看的日报，"
        "必须**同时包含**下面两个部分，顺序不能变：\n\n"
        "═══ 一、时间线 ═══\n"
        "按时间顺序列出 4~8 个关键节点，每条一行，格式：[大致的时刻] 谁 说了什么要紧的。\n"
        "用于回答「这一天是怎么走过来的」。\n\n"
        "═══ 二、话题 ═══\n"
        "把内容按主题归类，3~6 个话题，每个话题给短标题 + 2~5 条要点。\n"
        "用于回答「有几件事在同时发酵」。纯闲聊合并成最后一个话题，一句带过。\n\n"
        "规则：\n"
        "- 只写记录里真实出现过的内容，数字、代码、标的、结论必须来自原文，不许编造\n"
        "- 不要重复：时间线里讲过的过程，话题里只提炼结论\n"
        "- 全文用中文，紧凑，不写客套话\n\n"
        f"群名：{g.name}\n聊天记录：\n{digest}"
    )

    print(call_ai(cfg, prompt))


if __name__ == "__main__":
    main()
