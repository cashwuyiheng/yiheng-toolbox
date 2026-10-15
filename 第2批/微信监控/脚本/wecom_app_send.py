"""企业微信自建应用 - 发消息测试（直连，不走代理）。"""
import json
import urllib.request

CORPID = "ww0311f02d3ca41db1"
SECRET = "YK7SfVVVKnClj0rqPCCGTepjRzDQvHKJdOE1n3MGwzI"
AGENTID = 1000002

# 关键：不走代理。企业微信是国内服务，走代理会被 IP 白名单拦下（60020）
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_token():
    url = (f"https://qyapi.weixin.qq.com/cgi-bin/gettoken"
           f"?corpid={CORPID}&corpsecret={SECRET}")
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with _NO_PROXY.open(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))["access_token"]


def send_app(token, content, touser="@all"):
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    body = json.dumps({
        "touser": touser,
        "msgtype": "text",
        "agentid": AGENTID,
        "text": {"content": content},
        "safe": 0,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "curl/8"})
    with _NO_PROXY.open(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def main():
    tok = get_token()
    print("token OK（已直连，不走代理）")
    r = send_app(tok, "【测试】小花提醒 应用消息已接通。")
    print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
