"""对某个群做「今天一整天」的 AI 总结。
用法：python daily_summary.py 叮咚探世界
"""
import datetime as dt
import json
import sys
import urllib.request

sys.path.insert(0, r".\微信监控\脚本")
from wechat_reader import WeChatDB  # noqa: E402
from wechat_monitor import load_config  # noqa: E402

BASE = r".\微信监控\解密"
MAX_CHARS = 24000     # 放宽的输入上限（DeepSeek 上下文够大）


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
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    return data["choices"][0]["message"]["content"].strip()


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else "叮咚探世界"
    db = WeChatDB(BASE)
    cfg = load_config()

    hits = [g for g in db.groups(120) if keyword in g.name]
    if not hits:
        print("没找到群:", keyword)
        return
    g = hits[0]

    today0 = int(dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    msgs = db.messages(g.username, since=today0, limit=3000)
    texts = [m for m in msgs if m.text and m.kind in ("text", "quote")]

    print(f"群：{g.name}")
    print(f"今天消息：{len(msgs)} 条（其中可读文本/引用 {len(texts)} 条）")
    print("正在生成总结…\n")

    lines = [f"[{m.time_str}] {m.sender or '?'}: {m.text}" for m in texts]
    digest = "\n".join(lines)
    if len(digest) > MAX_CHARS:
        digest = digest[:MAX_CHARS] + "\n…（后面还有，已截断）"

    prompt = (
        "下面是某个微信群今天一整天的聊天记录（时间顺序）。"
        "请用中文写一份给群主看的日报，格式如下：\n\n"
        "【一句话】今天这个群主要发生了什么\n\n"
        "【时间线】按时间顺序列出 3-6 个关键节点，每条一行，写清几点、谁说了什么要紧的\n\n"
        "【重点信息】把有实操价值的信息单独列出来（数字、代码、标的、时间、链接、结论），闲聊不要\n\n"
        "【需要我行动的】如果有人在 @ 群主或提出需要回应的事，列出来；没有就写“无”\n\n"
        "要求：不要复述闲聊，不要编造没出现过的内容。\n\n"
        f"群名：{g.name}\n聊天记录：\n{digest}"
    )

    print(call_ai(cfg, prompt))


if __name__ == "__main__":
    main()
