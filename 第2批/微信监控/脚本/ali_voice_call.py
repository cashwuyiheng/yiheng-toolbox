"""阿里云语音服务 —— 拨打电话通知

用的是 SingleCallByTts 接口（文本转语音通知）。
只需要 AccessKey，不需要服务器、不需要域名。

签名算法：阿里云 RPC 风格 v1（HMAC-SHA1）

用法：
    python ali_voice_call.py "要念的内容"
"""
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import urllib.request
import uuid

# ============ 配置区（等你开通后填这里） ============
ACCESS_KEY_ID = ""          # 阿里云 AccessKey ID
ACCESS_KEY_SECRET = ""      # 阿里云 AccessKey Secret
TTS_CODE = ""               # 语音模板 ID（TtsCode）
CALLED_NUMBER = ""          # 要打给的手机号，如 13800000000
# ===================================================

ENDPOINT = "https://dyvmsapi.aliyuncs.com/"
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _percent(s):
    return urllib.parse.quote(str(s), safe="~")


def _sign(params: dict, secret: str) -> str:
    items = sorted(params.items())
    qs = "&".join(f"{_percent(k)}={_percent(v)}" for k, v in items)
    string_to_sign = "GET&%2F&" + _percent(qs)
    digest = hmac.new((secret + "&").encode("utf-8"),
                      string_to_sign.encode("utf-8"),
                      hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def call(content: str, tts_param: dict | None = None) -> dict:
    """给配置里的号码打一通电话，念 TTS 模板内容。"""
    if not all([ACCESS_KEY_ID, ACCESS_KEY_SECRET, TTS_CODE, CALLED_NUMBER]):
        raise ValueError("请先在文件顶部填好 4 个配置项")

    params = {
        "Action": "SingleCallByTts",
        "Version": "2017-05-25",
        "Format": "JSON",
        "RegionId": "cn-hangzhou",
        "AccessKeyId": ACCESS_KEY_ID,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": uuid.uuid4().hex,
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "CalledNumber": CALLED_NUMBER,
        "CalledShowNumber": "",
        "TtsCode": TTS_CODE,
    }
    if tts_param:
        params["TtsParam"] = json.dumps(tts_param, ensure_ascii=False)

    params["Signature"] = _sign(params, ACCESS_KEY_SECRET)

    qs = "&".join(f"{_percent(k)}={_percent(v)}" for k, v in params.items())
    req = urllib.request.Request(ENDPOINT + "?" + qs,
                                 headers={"User-Agent": "ali-voice/1.0"})
    with _NO_PROXY.open(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "(测试) 有一条重要消息"
    try:
        resp = call(text)
        print("返回:", json.dumps(resp, ensure_ascii=False))
        if resp.get("Code") == "OK":
            print("✅ 已拨号，CallId =", resp.get("CallId"))
        else:
            print("❌ 失败:", resp.get("Code"), resp.get("Message"))
    except Exception as e:
        print("异常:", type(e).__name__, e)
