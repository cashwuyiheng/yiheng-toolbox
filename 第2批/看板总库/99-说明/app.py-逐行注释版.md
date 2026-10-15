# 套利监控看板 · app.py 逐行注释版

> 这份文档把 `看板总库\01-套利监控看板\app.py` 整个拆开，**每一段都写了人话注释**。
> 读法建议：先看「整体结构」建立地图，再从上往下读代码，遇到不懂的注释多看两眼。
> 说明：注释里的「你」指写代码和读代码的人；原始代码一字未改，只在旁边加话。

---

## 整体结构（先看这张地图）

```
这份文件从上到下，分成六块：

  ① 文件说明（开头的三引号文字）
  ② 导入工具（import 那些行）
  ③ 路径和常量（告诉程序文件在哪、参数是多少）
  ④ 小工具函数（算结算周期、算年化）
  ⑤ 数据加载函数（把 CSV / JSON 读成表格）
  ⑥ 页面（侧栏 + 八个页面）

最重要的一句话：
  文件是「从上往下依次执行」的。
  读到最下面时，页面就画出来了。
  你每点一次按钮，整份文件会从头再跑一遍。这是 Streamlit 的规矩。
```

---

## ① 文件说明

```python
r"""
套利监控看板 — Streamlit Web 应用
====================================
版式参照 `港股打新仪表盘`：侧栏导航 + 指标卡 + Plotly 图 + 明细表。

页面：总览 / 费率历史 / 机会与告警 / 1011 情报包 / 使用说明
数据：quant 探索\数据\   （监控\funding_history.csv、1011情报包\1011情报包-合并.json）

运行：
    cd ".\\quant 探索"
    python -m streamlit run 看板\\app.py
"""
```
- 开头的 `r"""..."""` 是**多行文字**，纯粹写给人看，程序不执行它。
- `r` 的意思是「里面的反斜杠不要特殊处理」，因为 Windows 路径有 `\`，加了 r 就不用写两个。
- 最后那三行是**运行方法**，是给你自己留的备忘。

---

## ② 导入工具

```python
import json          # 处理 JSON 文件（那个情报包）
import os            # 处理路径、检查文件在不在
```
这两行是 Python **自带的**，装了 Python 就有，不用额外装。

```python
import pandas as pd            # 处理表格，取了个小名 pd
import plotly.express as px    # 画图，小名 px
import streamlit as st         # 做网页，小名 st
```
这三行是**第三方库**，要 `pip install` 才有。`as pd` 这种写法是「起小名」，这样后面写 `pd.read_csv` 比写 `pandas.read_csv` 省事。

---

## ③ 页面设置与常量

```python
st.set_page_config(
    page_title="套利监控看板",     # 浏览器标签页上显示的字
    page_icon="📡",               # 标签页那个小图标
    layout="wide",                # 用宽屏布局，不然内容挤在中间一条
    initial_sidebar_state="expanded",  # 侧栏一开始就是展开的
)
```
这是**网页的第一件事**：设置标题和图标的样式。必须在任何其他 `st.` 之前调用。

```python
# ── 路径与常量 ──────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # quant 探索
```
这行看着吓人，拆开就简单了，从里往外读：
- `__file__` = 当前这个文件自己的路径；
- `os.path.abspath(...)` = 变成完整的绝对路径；
- `os.path.dirname(...)` = **去掉最后一段**（拿到所在文件夹）；
- 套了两层 `dirname`，就是**往上退两级**。

因为 app.py 在 `quant 探索\看板\app.py`，退两级正好是 `quant 探索`。**这行的目的是：不管你在哪启动程序，都能正确定位到数据文件夹。**

```python
DATA_DIR = os.path.join(BASE, "数据")
CSV_PATH = os.path.join(DATA_DIR, "监控", "funding_history.csv")
ALERT_LOG = os.path.join(DATA_DIR, "监控", "告警记录.csv")
DEX_CSV = os.path.join(DATA_DIR, "监控", "dex_history.csv")
PUSH_CFG = os.path.join(BASE, "配置", "推送配置.json")
PACK_JSON = os.path.join(DATA_DIR, "1011情报包", "1011情报包-合并.json")
```
`os.path.join(甲, 乙)` 就是**把两段路径接起来**，它会自动处理中间的分隔符。上面五行的意思是：把后面要用到的文件，先算出完整地址存成变量，后面直接用名字引用，不用重复写长路径。

```python
DEX_EXCHANGES = ["hyperliquid", "lighter"]          # 方括号是列表，装两个名字
DEX_SYMBOLS = ["BTC/USDC:USDC", "ETH/USDC:USDC", "SOL/USDC:USDC"]  # 三个交易对

DEX_MULTI_CSV = os.path.join(DATA_DIR, "监控", "dex_multi_history.csv")
DEX_MULTI_EXCHANGES = ["hyperliquid", "lighter", "backpack", "aster",
                       "paradex", "extended", "dydx", "apex"]   # 八家平台
DEX_MULTI_COINS = ["BTC", "ETH", "SOL"]                          # 三个币种

FALLBACK_HOURS = {"hyperliquid": 1, "lighter": 1, "backpack": 1,
                  "aster": 8, "paradex": 8}
```
- 花括号 `{键: 值, ...}` 是**字典**，用来做「名字 → 数字」的对照表。
- `FALLBACK_HOURS` 的意思是「万一问不出结算周期，就按这张表兜底」：hyperliquid 按 1 小时算，aster 按 8 小时算。
- **兜底表是这份代码里很少见的妥协，说明作者知道接口有问不出来的时候。**

---

## ④ 两个小工具函数

### 算「多久结算一次」

```python
def _funding_hours(label, d, market):
    """结算周期(小时)；推不出来返回 None。"""
```
- `def` 是**定义一个函数**；括号里是**要传进去的东西**（参数）。
- 函数名前面加下划线 `_` 是**约定**：表示「这是内部的，外面不用管它」。
- 三引号那行是**说明**，别人调用时能看到这句提示。
- `return None` 的含义是：算不出来就交回一个空值，**不硬编造**。

```python
    iv = (d or {}).get("interval")
```
从交易所返回的数据 `d` 里，找名为 `interval` 的字段。
`(d or {})` 是个**保险动作**：万一 `d` 是空的，就用一个空字典代替，**避免程序报错**。

```python
    if isinstance(iv, str) and iv.endswith("h"):
        try:
            return float(iv[:-1])
        except ValueError:
            pass
```
- `isinstance(iv, str)` 问的是「iv 是不是文字」；
- `iv.endswith("h")` 问的是「结尾是不是字母 h」，比如 `"8h"`；
- 如果是，`iv[:-1]` 意思是**砍掉最后一个字符**，`"8h"` 就剩 `"8"`，再用 `float()` 变成数字 8；
- `try / except` 是**保险绳**：万一转数字失败（比如是个奇怪字符），不要崩，`pass` 直接跳过。

```python
    if isinstance(iv, (int, float)) and iv:
        return iv / 3600000 if iv > 1000 else float(iv)
```
两种情况都考虑到了：
- 如果这个数字**很大**（大于 1000），说明单位是**毫秒**，要除以 3600000 换成小时；
- 否则它本来就是小时数，直接用。
那行 `甲 if 条件 else 乙` 是**三元表达式**，等于「条件成立就用甲，否则用乙」。

```python
    info = (market or {}).get("info") or {}
    fi = info.get("fundingInterval")
    if isinstance(fi, (int, float)) and fi:
        return fi / 3600000
    return FALLBACK_HOURS.get(label)
```
前两行：换个地方再找一遍，去 `market` 里的 `info` 里找 `fundingInterval`。
找到了就按毫秒换算成小时。
最后一行：**实在找不到，就去兜底表里按平台名取一个值**（取不到会返回 None）。

> 这个函数体现的是一条很实在的工程习惯：**同一个信息，从三个地方依次找，最后兜底，找不到也不编。**

### 算「年化百分比」

```python
def _annual(label, rate, d, market):
    h = _funding_hours(label, d, market)
    if rate is None or not h:
        return None
    return rate * (24 / h) * 365 * 100
```
这是整份代码里**最核心的一行公式**，三句话：
1. 先问「多久结算一次」，拿到小时数 `h`；
2. 如果有任何一个数缺了，返回 None，**算不了就说算不了**；
3. 否则：**单次费率 × 一天结算几次（24 ÷ h） × 一年 365 天 × 100（换成百分比）**。

举例：费率 0.01%、每 8 小时结算一次。
每天结算 3 次，一天就是 0.03%，一年 365 天约 10.95%。
就是 `0.0001 × 3 × 365 × 100 ≈ 10.95%`。

---

## ⑤ 另外几个常量

```python
SYMBOL = "ETH/USDT:USDT"       # 主要盯的合约（以太坊永续）
PROXY = "http://127.0.0.1:7897"  # 本地代理，Clash 的地址
EXCHANGES = ["binance", "okx", "bybit"]   # 主要盯的三家中心化交易所
ALERT_PCT = 5.0                # 告警阈值：年化差超过 5% 就提醒
COLORS = ["#1a569b", "#ED7D31", ...]      # 画图用的六种颜色，免得每次重挑
```
`COLORS` 是**十六进制颜色码**，`#1a569b` 就是某个深蓝色。把它们存成一个列表，后面画图轮流用，**保证每张图颜色统一**。

---

## ⑥ 数据加载：把文件读成表格

### 读费率历史

```python
@st.cache_data(ttl=30)
def load_history() -> pd.DataFrame:
    if not os.path.exists(CSV_PATH):
        return pd.DataFrame(columns=["时间", "交易所", "单次费率", "年化(%)"])
    return pd.read_csv(CSV_PATH)
```
- 第一行 `@st.cache_data(ttl=30)` 是**装饰器**，你理解成「给下面这个函数套了个壳」就行。作用：**读到的结果先记住 30 秒**，这 30 秒内再有人要，直接给旧的，不用重新读文件。
- `-> pd.DataFrame` 是**声明返回值类型**，告诉读代码的人：这个函数交回来的是一张表格。这只是说明，不强制。
- `os.path.exists(CSV_PATH)` 问的是**文件在不在**；
- `if not` 就是「不在的话」，那就返回一张**只有列名、没有数据的空表**。
**这行是整个看板不会崩的关键**：数据还没生成时，看板照样能打开，只是显示空。

### 读告警记录

```python
@st.cache_data(ttl=30)
def load_alerts() -> pd.DataFrame:
    if not os.path.exists(ALERT_LOG):
        return pd.DataFrame(columns=["时间", "年化差(%)"])
    return pd.read_csv(ALERT_LOG)
```
跟上面几乎一样，只是换了个文件、换了个列名。**这类重复在这份代码里很常见，说明作者没有过度抽象，宁可重复也要看得懂。**

### 看推送通道配了哪些

```python
def push_channels() -> list:
    """看推送配置里到底填了哪些通道。"""
    if not os.path.exists(PUSH_CFG):
        return []
    try:
        cfg = json.load(open(PUSH_CFG, encoding="utf-8"))
    except Exception:
        return []
```
- `json.load(...)` 把 JSON 文件读成一个**字典**；
- `open(..., encoding="utf-8")` 那句的 `encoding="utf-8"` 很重要，**不加中文会乱码**；
- 外面包 try/except，意思是「**配置坏了也别崩**，当作没配就行」。

```python
    names = [k for k in ("bark", "serverchan", "pushdeer", "wecom")
             if (cfg.get(k) or "").strip()]
    tg = cfg.get("telegram") or {}
    if tg.get("token") and tg.get("chat_id"):
        names.append("telegram")
    return names
```
- `names = [...]` 是**列表推导**，一行干了「循环 + 筛选」两件事。翻译成人话：**挨个检查这几个通道名，哪个在配置里有值，就收进名单。**
- `.strip()` 是**去掉首尾空格**，防止有人填了个纯空格也算配了。
- telegram 单独处理，因为它要**同时有 token 和 chat_id** 才算配好。
- `names.append(...)` 是**往列表末尾追加一个**。

### 读 DEX 数据 / 现场抓取

```python
@st.cache_data(ttl=30)
def load_dex() -> pd.DataFrame:
    if not os.path.exists(DEX_CSV):
        return pd.DataFrame(columns=["时间", "标的", "交易所", "资金费率", "年化(%)", "价格"])
    return pd.read_csv(DEX_CSV)
```
又是同一套路：先看文件在不在，在就读进来。到这里你应该发现，**这四五个读文件的函数是同一个模子刻出来的。**

```python
def fetch_dex_live(symbols) -> pd.DataFrame:
    """现场抓 Lighter 与 Hyperliquid（需要 Clash 代理）。"""
    import ccxt           # 在函数内部才导入，因为只在真正抓取时才需要
    rows = []             # 先准备一个空列表，等会儿一行行往里装
    for label in DEX_EXCHANGES:              # 挨个平台
        try:
            ex = getattr(ccxt, label)({"httpsProxy": PROXY, "enableRateLimit": True})
            ex.load_markets()
        except Exception:
            continue     # 这个平台连不上，跳过，抓下一个
```
- `getattr(ccxt, label)` 的意思是「**从 ccxt 这个工具箱里，按名字取出对应的那个工具**」，`label` 是 `"hyperliquid"` 就取 hyperliquid 的接口。
- `{"httpsProxy": PROXY, "enableRateLimit": True}` 是**传给接口的设置**：走本地代理，并且限速（免得把人家服务器惹毛）。
- `ex.load_markets()` 是**先把这家平台的合约清单加载进来**。
- `continue` 是「**这一轮别干了，直接跳到下一轮**」。平台连不上就跳过，这是很稳妥的写法。

```python
        for s in symbols:            # 再挨个交易对
            fr = pr = ann = None     # 三个结果先都设成空
            try:
                d = ex.fetch_funding_rate(s)     # 问：资金费率多少
                fr = float(d["fundingRate"])
                ann = _annual(label, fr, d, ex.market(s))   # 顺手算成年化
            except Exception:
                pass
            try:
                t = ex.fetch_ticker(s)           # 再问：现在什么价
                pr = float(t["last"]) if t.get("last") else None
            except Exception:
                pass
            rows.append({"标的": s, "交易所": label, "资金费率": fr,
                         "年化(%)": ann, "价格": pr})   # 装成一行
```
要点有两个：
1. **费率问不到不影响价格**，价格问不到也不影响费率。两件事各自 try 各自的，**互不拖累**。
2. `rows.append({...})` 每次往里加**一个字典**，最后会变成一张表。字典的键就是列名。

```python
    return pd.DataFrame(rows)    # 把「一行行记录的列表」变成表格
```
这一行是**列表变表格**的关键动作，以后你会经常见到。

```python
@st.cache_data(ttl=30)
def load_dex_multi() -> pd.DataFrame:
    if not os.path.exists(DEX_MULTI_CSV):
        return pd.DataFrame(columns=["时间", "币种", "平台", "年化(%)", "价格"])
    return pd.read_csv(DEX_MULTI_CSV)
```
还是同一个模子，不重复解释了。

```python
def fetch_dex_multi_live(coins, exchanges) -> pd.DataFrame:
    """现场抓多家 DEX（需要 Clash 代理）。"""
    import ccxt
    rows = []
    for label in exchanges:
        try:
            ex = getattr(ccxt, label)({"httpsProxy": PROXY, "enableRateLimit": True})
            mk = ex.load_markets()
        except Exception:
            continue
```
跟前面几乎一样，区别只有一个：**这次要把合约清单 `mk` 接住**，因为下面要用它挑交易对。

```python
        for coin in coins:
            cands = [s for s, m in mk.items()
                     if m.get("swap") and m.get("linear")
                     and (m.get("base") or "").upper() == coin]
            if not cands:
                continue
            cands.sort(key=lambda s: (0 if "USDC" in s else 1, len(s)))
            sym = cands[0]
```
这段是整份代码里**最需要解释的一段**，它在做「**给一个币，找它最合适的合约**」：
1. `mk.items()` 是把合约清单拆成一对对（名字, 详情）；
2. 从里面筛出**同时满足三个条件**的：是永续合约（swap）、是线性合约（linear）、基础币种等于我们要找的币（BTC/ETH/SOL）；
3. `cands` 是候选名单，一个都没有就跳过这个币；
4. `cands.sort(key=lambda ...)` 是**按优先顺序排队**：
   - 名字里带 USDC 的排前面（第 0 档），不带的后排（第 1 档）；
   - 同一档里，名字短的排前面；
5. `sym = cands[0]` 取排第一的那个。
**一句话：优先选 USDC 计价、名字最短的合约。**
（那个 `lambda` 你不用会写，理解成「一个临时的排队规则」就够。）

```python
            fr = pr = ann = None
            try:
                d = ex.fetch_funding_rate(sym)
                fr = float(d["fundingRate"])
                ann = _annual(label, fr, d, ex.market(sym))
            except Exception:
                pass
            try:
                t = ex.fetch_ticker(sym)
                pr = float(t["last"]) if t.get("last") else None
            except Exception:
                pass
            rows.append({"币种": coin, "平台": label, "年化(%)": ann, "价格": pr})
    return pd.DataFrame(rows)
```
跟上面那段的抓取逻辑完全一致，**同一个模式用了第二次**。

### 读情报包

```python
@st.cache_data
def load_pack() -> list:
    if not os.path.exists(PACK_JSON):
        return []
    with open(PACK_JSON, encoding="utf-8") as f:
        return json.load(f)
```
- 这里 `@st.cache_data` **后面没写 ttl**，意思是**永久缓存**（相对地，前面那些写 ttl=30 的只缓存 30 秒）。因为情报包是固定的历史数据，不会天天变。
- `with open(...) as f:` 是**标准的打开文件写法**。`with` 的好处是**用完自动关掉文件**，不用手动 close。

### 抓主要三家（中心化交易所）

```python
def fetch_live() -> pd.DataFrame:
    """实时抓一次费率（需要 Clash 代理）。"""
    import ccxt
    rows = []
    for name in EXCHANGES:          # 币安、OKX、Bybit
        try:
            ex = getattr(ccxt, name)({"enableRateLimit": True, "httpsProxy": PROXY})
            d = ex.fetch_funding_rate(SYMBOL)
            rows.append({"交易所": name, "单次费率": float(d["fundingRate"]),
                         "年化(%)": float(d["fundingRate"]) * 3 * 365 * 100})
        except Exception:
            pass
    return pd.DataFrame(rows)
```
注意最后那行计算：`* 3 * 365 * 100`。
这里的 **3** 是写死的，代表「**每天结算 3 次**」（也就是 8 小时一次）。**这是这份代码里一个粗疏的地方**：它是硬编码的，不像是 `_annual` 那样会去问真实周期。对这个标的（ETH 永续）大概率没错，但如果换个结算周期不同的合约，这里就会算错。

### 往历史里追加

```python
def append_history(df: pd.DataFrame) -> None:
    if df.empty:
        return
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    out = df.copy()
    out.insert(0, "时间", pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"))
    out.to_csv(CSV_PATH, mode="a", header=not os.path.exists(CSV_PATH),
               index=False, encoding="utf-8-sig")
```
- `df.empty` 问「表格是不是空的」，空的就什么也不做；
- `os.makedirs(..., exist_ok=True)` 是**确保文件夹存在**，`exist_ok=True` 表示「已经有了也别报错」；
- `df.copy()` 是**先复制一份再改**，避免弄脏传进来的原表；
- `out.insert(0, ...)` 在**第 0 列（最左边）插入一列**，内容是当前时间，格式化成 `年-月-日 时:分:秒`。`strftime` 可以理解成「**按模板打印时间**」；
- `out.to_csv(...)` 是**写入 CSV 文件**，这里几个参数都很关键：
  - `mode="a"` 是**追加**，不是覆盖（覆盖的话老数据就没了）；
  - `header=not os.path.exists(CSV_PATH)` 的意思是「**文件还不存在时才写表头**」。已经存在就不要再写一遍列名，否则表里会混进一行假数据；
  - `index=False` 表示**不要最左边那列自动编号**；
  - `encoding="utf-8-sig"` 是**带 BOM 的 UTF-8**，这样用 Excel 打开中文不乱码。

> 这个小函数是「采集层往存储层滴水」的**唯一入口**，看板里点「实时抓取」也走它。

---

## ⑦ 文件一跑起来，先执行这几行

```python
hist = load_history()
pack = load_pack()
```
- 这是**模块级代码**，意思是「文件被跑到这里时，就直接执行」。
- 目的：**一进来就把费率历史和情报包读好**，后面侧栏和各个页面都能直接用 `hist`、`pack`。
- Streamlit 每次重跑都会重新执行这两行，但因为上面有 30 秒缓存，**不会真的反复读硬盘**。

---

## ⑧ 侧栏

```python
with st.sidebar:
```
`with` 在这里是「**下面缩进的这些内容，都放进侧栏**」。这段一结束，后面的内容就回到主区域。

```python
    st.title("📡 套利监控看板")
    st.caption("quant 探索 · 资金费率 / 价差")
    st.divider()
    st.metric("标的", SYMBOL.split(":")[0])
    st.metric("告警阈值", f"{ALERT_PCT}%")
```
- `st.title` 是大标题，`st.caption` 是小字说明，`st.divider()` 是一条分隔线；
- `st.metric(标题, 数值)` 是**数字卡**；
- `SYMBOL.split(":")[0]` 把 `"ETH/USDT:USDT"` 按冒号切开，取第一段，得到 `"ETH/USDT"`。

```python
    _chans = push_channels()
    st.subheader("🔔 值班状态")
    if _chans:
        st.success("已配推送：" + "、".join(_chans))
    else:
        st.warning("未配推送通道\n（只能看，不会喊）")
```
- `if _chans:` 问「名单是不是空的」，非空就为真。**空列表在 Python 里等于假**，这是个常用技巧；
- `"、".join(_chans)` 把列表里的名字**用顿号连成一句话**；
- `st.success` 是绿框，`st.warning` 是黄框。`\n` 是换行符。
- 那句「只能看，不会喊」是这个看板里很有人味的一句提示。

```python
    st.caption(f"最后数据：{hist['时间'].iloc[-1] if not hist.empty else '暂无'}")
```
一层层拆：
- `hist['时间']` 取「时间」这一列；
- `.iloc[-1]` 取**最后一行**（`iloc` 是按位置取，`-1` 表示倒数第一）；
- `if not hist.empty else '暂无'` 是三元表达式：**有数据就显示最新那个时间，没数据就显示"暂无"**。
- 最外面的 `f"..."` 是 f-string，**能把变量的值直接塞进文字里**。

```python
    page = st.radio(
        "",
        ["🏠 总览", "📈 费率历史", "🚨 机会与告警", "🔔 告警记录",
         "🪙 DEX 对比", "🌐 多平台", "📚 1011 情报包", "🧭 使用说明"],
        label_visibility="collapsed",
    )
```
- `st.radio` 是**单选框**，返回值是「用户当前选了哪个」；
- 第一个参数 `""` 是空标题（标题由上面的 subheader 担任）；
- `label_visibility="collapsed"` 是**把标签藏起来**，让界面干净；
- **`page` 这个变量，就是整个页面的路由开关**，下面全靠它决定画哪一页。

```python
    if st.button("🔄 实时抓取一次", use_container_width=True):
        live = fetch_live()
        if live.empty:
            st.error("抓取失败：检查 Clash 是否开着（代理 7897）")
        else:
            append_history(live)
            load_history.clear()
            st.success("已抓取并写入历史")
            st.rerun()
```
这个按钮是**整份代码里最能说明 Streamlit 机制的地方**，四步：
1. `st.button(...)` 被点击时返回真，里面的代码才执行；
2. 抓一次数据；
3. 抓到了就**追加进 CSV**，然后 `load_history.clear()` **手动清掉缓存**（否则还是读到旧的 30 秒缓存）；
4. `st.rerun()` **让整页重跑一遍**，新数据就出现在界面上了。

**记住这个顺序：改数据 → 清缓存 → 重跑。** 以后你自己写 Streamlit 会用得上。

---

## ⑨ 八个页面

下面每个页面都是同样的写法：**判断 `page` 是不是这一页，是就画**。

### 页面一：总览

```python
if page == "🏠 总览":
    st.title("套利监控 · 总览")
    st.caption("资金费率快照 · 数据来自本地历史 CSV")

    if hist.empty:
        st.info("还没有历史数据。点侧栏「🔄 实时抓取一次」，或先跑一次监控脚本。")
        st.stop()
```
- `st.stop()` 是**就地停下**，下面的代码不再执行。用在这里的意思是「没数据就别往下画了」。
- `st.info` 是蓝框提示。

```python
    latest_t = hist["时间"].iloc[-1]           # 最后一次的时刻
    latest = hist[hist["时间"] == latest_t].copy()  # 只留那个时刻的行
```
这两行是**整份代码里最常用的套路**，务必看懂：
1. 先从「时间」列里取最后一行，得到最新时刻；
2. 然后用**布尔筛选**：`hist["时间"] == latest_t` 会生成一串 真/假，`hist[那一串]` 就把真的那些行留下。
翻译成人话：**"把所有时间等于最新时刻的行挑出来"**。

```python
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("数据点", f"{hist['时间'].nunique()} 次")
    c2.metric("覆盖交易所", f"{hist['交易所'].nunique()} 家")
```
- `st.columns(5)` 把页面**横向切成 5 格**，返回 5 个对象；
- `.nunique()` 数的是「**有几个不重复的值**」，比如有 100 行但只有 20 个不同时刻，就返回 20。

```python
    if not latest.empty:
        hi = latest.loc[latest["年化(%)"].idxmax()]
        lo = latest.loc[latest["年化(%)"].idxmin()]
        spread = hi["年化(%)"] - lo["年化(%)"]
        c3.metric("最新年化差", f"{spread:.2f}%",
                  f"{'⚠️ 越阈值' if abs(spread) >= ALERT_PCT else '正常'}")
        c4.metric("费率最高", f"{hi['交易所']}", f"{hi['年化(%)']:.2f}%")
        c5.metric("费率最低", f"{lo['交易所']}", f"{lo['年化(%)']:.2f}%")
```
- `.idxmax()` 返回**最大值所在的行标签**，`.loc[...]` 再按标签把那行取出来。合起来就是「**找出年化最高的那一家**」；
- `spread` 是最高减最低，也就是**年化差**；
- `f"{spread:.2f}%"` 里的 `:.2f` 意思是「**保留两位小数**」，`:.3f` 就是三位；
- `abs(spread) >= ALERT_PCT` 是拿绝对值去比阈值，超过就显示「⚠️ 越阈值」；
- `st.metric` 的第三个参数是**卡片下方的小字**，可以是一句话，也可以是带箭头的数字。

```python
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("最新费率（年化）")
        fig = px.bar(latest, x="交易所", y="年化(%)", color="交易所",
                     color_discrete_sequence=COLORS, text_auto=".2f")
        fig.update_layout(height=350, margin=dict(t=10, b=0, l=0, r=0),
                          showlegend=False)
        fig.add_hline(y=0, line_dash="dot", line_color="#888")
        st.plotly_chart(fig, use_container_width=True)
```
- `with col1:` 表示「下面这些放进左边那一格」；
- `px.bar(...)` 画**柱状图**，参数读法很直白：**x 轴放交易所，y 轴放年化，颜色也按交易所区分**；
- `text_auto=".2f"` 让**每根柱子上自动标出数值**，保留两位小数；
- `fig.update_layout(...)` 调**高度和四周留白**（t/b/l/r 是上下左右）；
- `fig.add_hline(y=0, ...)` 在 **y=0 处加一条虚线**，方便看正负；
- `st.plotly_chart(fig, ...)` 把图**放到页面上**。注意：**前面都是"准备好一张图"，这一行才真正上屏。**

```python
    with col2:
        st.subheader("费率占比（绝对值）")
        tmp = latest.copy()
        tmp["|年化|"] = tmp["年化(%)"].abs()
        fig = px.pie(tmp, names="交易所", values="|年化|", hole=0.4,
                     color_discrete_sequence=COLORS)
        fig.update_traces(textinfo="label+percent")
        st.plotly_chart(fig, use_container_width=True)
```
- `.abs()` 取**绝对值**，因为费率有正有负，饼图不能拿负数算比例；
- `tmp["|年化|"] = ...` 是**新增一列**（注意 `tmp` 是复制出来的，没动原表）；
- `px.pie(..., hole=0.4)` 是**环形图**，`hole` 是中间那个洞的大小；
- `textinfo="label+percent"` 让图上同时显示**名字和百分比**。

```python
    st.subheader("最新明细")
    st.dataframe(latest.style.format({"单次费率": "{:.8f}", "年化(%)": "{:.3f}"}),
                 use_container_width=True, hide_index=True)
```
- `st.dataframe` 是**把表格显示出来**；
- `.style.format({...})` 控制**每列显示几位小数**（单次费率很小，要 8 位才看得出来）；
- `hide_index=True` 是**藏掉最左边那列自动编号**。

### 页面二：费率历史

```python
elif page == "📈 费率历史":
    st.title("费率历史")

    if hist.empty or hist["时间"].nunique() < 2:
        st.info("历史数据还不够画曲线。让监控脚本多跑几轮（`--loop 300`），或多次点「实时抓取」，这里就会长出走势。")
        if not hist.empty:
            st.dataframe(hist, use_container_width=True, hide_index=True)
        st.stop()
```
- `or` 是「或者」：数据为空 **或者** 时刻少于 2 个，都不够画线；
- 判断完如果还有数据，就**先显示原始表格**再停，不让用户面对空白。

```python
    names = st.multiselect("交易所", sorted(hist["交易所"].unique()),
                           default=sorted(hist["交易所"].unique()))
    sub = hist[hist["交易所"].isin(names)].copy()
    sub["时间"] = pd.to_datetime(sub["时间"])
```
- `st.multiselect` 是**多选框**，`default=...` 是默认全选；
- `.unique()` 去重拿到所有交易所名字，`sorted(...)` 排个序；
- `.isin(names)` 是「**在这一串名单里**」的筛选，比写一长串 `==` 简洁；
- `pd.to_datetime(...)` 把「时间」列从**文字**变成**真正的时间类型**，只有这样 Plotly 才能正确当横轴用。

```python
    fig = px.line(sub, x="时间", y="年化(%)", color="交易所",
                  markers=True, color_discrete_sequence=COLORS)
    fig.update_layout(height=420, margin=dict(t=10, b=0, l=0, r=0))
    fig.add_hline(y=0, line_dash="dot", line_color="#888")
    st.plotly_chart(fig, use_container_width=True)
```
`px.line` 是**折线图**，`markers=True` 让每个数据点**画个小圆点**。其余和柱状图一模一样。

```python
    pivot = sub.pivot_table(index="时间", columns="交易所",
                            values="年化(%)", aggfunc="last").round(3)
    pivot["年化差(最高-最低)"] = (pivot.max(axis=1) - pivot.min(axis=1)).round(3)
    st.dataframe(pivot, use_container_width=True)
```
这是 pandas 里**最有用的一个操作**，叫**透视表**：
- `index="时间"` 竖着排时间；
- `columns="交易所"` 横着排交易所；
- `values="年化(%)"` 中间填年化数字；
- `aggfunc="last"` 如果同一个格子有多个值，取最后一个。
**效果就是把「长条数据」变成「横竖对照表」**，一眼能横向比。
- `axis=1` 表示「**横着算**」（每行取最大减最小），`axis=0` 才是竖着算。这个方向容易记反，多留意。

### 页面三：机会与告警

```python
elif page == "🚨 机会与告警":
    st.title("机会与告警")
    thr = st.slider("告警阈值（年化差 %）", 0.0, 20.0, ALERT_PCT, 0.5)
```
`st.slider(名字, 最小值, 最大值, 默认值, 每次跳多少)`，返回值是**用户选的数字**。

```python
    g = hist.groupby("时间")["年化(%)"].agg(["max", "min"])
    g["年化差"] = (g["max"] - g["min"]).round(2)
    hits = g[g["年化差"] >= thr]
```
- `groupby("时间")` 是**按时间分组**；`.agg(["max","min"])` 是**每组算最高和最低**；
- 结果 `g` 是一张**每个时刻一行**的表，有两列：max、min；
- 加一列「年化差」，再筛出**大于等于阈值**的那些时刻，存成 `hits`。

```python
    c1.metric("观测次数", f"{len(g)}")
    c2.metric("越过阈值次数", f"{len(hits)}", f"{'有' if len(hits) else '暂无'}")
```
`len(...)` 数的是**有多少行**。

```python
    fig = px.bar(g.reset_index(), x="时间", y="年化差",
                 color_discrete_sequence=["#1a569b"])
    fig.add_hline(y=thr, line_dash="dash", line_color="#c0392b",
                  annotation_text=f"阈值 {thr}%")
```
- `.reset_index()` 是因为分组后「时间」变成了索引而不是普通列，**重置一下**才能直接当 x 轴；
- `annotation_text` 是**线上那行说明文字**。

```python
        st.dataframe(hits.reset_index(), use_container_width=True, hide_index=True)
        st.caption("思路：在费率最高的所做空、最低的所做多，赚费率差。⚠️ 仅为费率差，未计价差、手续费、滑点与风险。")
```
**最后这句 caption 是这份代码里最该认真读的一句话**：它在老实交代，图上算的只是「费率差」，**没算价差、手续费、滑点和风险**。也就是说，图上那个数字不等于你能赚到的钱。

### 页面四：DEX 对比

```python
elif page == "🪙 DEX 对比":
    st.title("Lighter × Hyperliquid")
    if st.button("🔄 现场抓一次（需 Clash 开着）", use_container_width=False):
        with st.spinner("正在抓 Lighter 与 Hyperliquid ..."):
            live = fetch_dex_live(DEX_SYMBOLS)
        if live.empty:
            st.error("抓取失败：确认 Clash 开着（代理 7897）")
        else:
            st.session_state["dex_live"] = live
            st.success(f"抓到 {len(live)} 条")
```
- `st.spinner("...")` 是**转圈等待的提示**，抓取期间显示；
- `st.session_state["dex_live"] = live` 是**把抓到的数据暂时存起来**。
  `session_state` 可以理解成「**这个页面的一块小抽屉**」，用来在重跑之间**记住东西**。因为 Streamlit 每次交互都重跑，普通变量会被冲掉，要存住就得放这个抽屉里。

```python
    live = st.session_state.get("dex_live")
    if live is None or live.empty:
        hist = load_dex()
        if hist.empty:
            st.info("还没有数据。点上面的按钮现场抓一次。")
            st.stop()
        st.caption("以下是历史最后一次快照（点上面按钮可刷新）")
        live = hist[hist["时间"] == hist["时间"].iloc[-1]].copy()
```
逻辑是「**抽屉里有就用抽屉里的，没有就退回历史最后一份快照**」。这种「优先实时、退而求其次用历史」的写法，整个看板里反复出现。

```python
        piv = live.pivot_table(index="标的", columns="交易所",
                               values="年化(%)", aggfunc="last")
        piv["年化差"] = (piv.max(axis=1) - piv.min(axis=1)).round(2)
        piv = piv.sort_values("年化差", ascending=False)
```
又是透视表。`sort_values(..., ascending=False)` 是**按年化差从大到小排**，机会最大的排最上面。

```python
        fig = px.bar(piv.reset_index().melt(id_vars="标的", value_vars=DEX_EXCHANGES,
                                            var_name="平台", value_name="年化(%)"),
                     x="标的", y="年化(%)", color="平台", barmode="group",
                     color_discrete_sequence=COLORS)
```
`.melt(...)` 是**把横表掰回长条**（透视表的逆操作），因为分组柱状图需要长条格式。`barmode="group"` 表示**同组柱子并排站**（不堆叠）。

### 页面五：多平台

```python
    piv = live.pivot_table(index="平台", columns="币种", values="年化(%)", aggfunc="last")
    order = [c for c in DEX_MULTI_COINS if c in piv.columns]
    if order:
        piv = piv[order]
```
- 先透视成「平台 × 币种」的表；
- `order` 那句是**把列的顺序固定成 BTC、ETH、SOL**，免得 Plotly 按字母乱排；
- `piv = piv[order]` 用这个顺序**重排表的列**。

```python
    for c in order:
        col = piv[c].dropna()
        if len(col) < 2:
            st.caption(f"{c}: 数据不足")
            continue
        hi, lo = col.idxmax(), col.idxmin()
        st.markdown(f"- **{c}**：最高 {hi} ({col[hi]:+.2f}%) ／ 最低 {lo} ({col[lo]:+.2f}%) "
                    f"→ 差 **{col[hi]-col[lo]:.2f}%**")
```
- `.dropna()` 是**把没有值的格子丢掉**（可能某些平台某个币没数据）；
- `continue` 是「这个币数据不够，跳到下一个」；
- `st.markdown("...")` 会**把 markdown 语法渲染出来**，比如 `**加粗**`；
- `:+.2f` 里的加号意思是「**正数也显示 + 号**」，一眼能看出正负。

### 页面六：1011 情报包

```python
elif page == "📚 1011 情报包":
    df = pd.DataFrame([{
        "时间": t.get("sourceLocalTime") or t.get("timestamp", ""),
        "账号": t.get("userId", ""),
        "正文": (t.get("content", "") or "").replace("\n", " "),
        "情绪": (t.get("analysis") or {}).get("sentiment", ""),
        "链接": t.get("link", ""),
        "话题": "、".join((t.get("analysis") or {}).get("topics", [])[:4]),
    } for t in pack])
```
这是**列表推导 + 字典推导的组合**，一次把 90 条推文整理成表格。几个要点：
- `t.get("键", 默认值)` 的好处是**键不存在也不报错**，返回默认值。比 `t["键"]` 安全得多；
- `甲 or 乙` 的意思是「**甲有值就用甲，否则用乙**」，用来兼容两种不同的字段名；
- `.replace("\n", " ")` 把**换行换成空格**，免得表格里一行太高；
- `[:4]` 是**只取前 4 个话题**。

```python
    c3.metric("语言", f"中{sum(1 for t in pack if (t.get('analysis') or {}).get('language')=='zh')} / 英{...}")
```
`sum(1 for ... if ...)` 是个小技巧：**符合条件的每项算 1，最后加起来**，就得到「有多少条是中文」。

```python
    q = st.text_input("关键词（账号 / 正文）", "")
    show = df.copy()
    if q:
        m = show["账号"].str.contains(q, case=False, na=False) | \
            show["正文"].str.contains(q, case=False, na=False)
        show = show[m]
```
- `st.text_input` 是**输入框**；
- `.str.contains(q, case=False, na=False)` 是**在文字里找关键词**，`case=False` 忽略大小写，`na=False` 遇到空值当「不匹配」；
- 中间那个 `|` 是**「或」**，意思是账号里有 **或者** 正文里有；
- 行尾的 `\` 是**换行续写**，因为一行太长了。

```python
    st.dataframe(
        show[["时间", "账号", "情绪", "话题", "正文"]],
        use_container_width=True, hide_index=True, height=460,
        column_config={"链接": st.column_config.LinkColumn("链接")},
    )
```
`column_config` 是**给某列设定显示方式**，这里是把「链接」列显示成可点击的样子。

### 页面七：告警记录

```python
    c2.metric("已推送", f"{int((alerts['已推送'] == '是').sum()) if '已推送' in alerts.columns and not alerts.empty else 0} 次")
```
这行很长的原因是在**层层设防**：先确认表不为空、再确认有「已推送」这一列，然后才去数有多少个「是」。
`(alerts['已推送'] == '是')` 生成一串真假，`.sum()` 把真当成 1 加起来，`int(...)` 转成整数。
**如果直接写一半，表还没生成时就会报错**，所以这里写得啰嗦但稳。

### 页面八：使用说明

```python
elif page == "🧭 使用说明":
    st.markdown("""
### 这个看板是什么
...
""")
```
`st.markdown("""...""")` 是**用三引号一次写一大段带格式的文字**。里面的 `###`、表格、代码块都会被渲染出来。这一页的内容全是人话，不是程序逻辑。

---

## 读完这份代码，你实际学到的东西

```
1. 路径怎么拼（os.path.join / dirname）
2. 文件怎么安全地读（先判断在不在，try/except 包住）
3. 表格怎么做筛选、分组、透视（pandas 三件套）
4. 图怎么画、怎么上屏（px.xxx 准备，st.plotly_chart 上屏）
5. 网页怎么布局（sidebar / columns / metric）
6. Streamlit 的重跑机制（改数据 → 清缓存 → rerun）
7. 「实时优先、历史兜底」这种工程上的稳妥习惯
```

## 顺手指出的三个小问题（不是错，是提个醒）

1. **`fetch_live()` 里 `* 3 * 365 * 100` 的 3 是写死的**，代表每天结 3 次。换个结算周期不同的合约就会算错。`_annual()` 那种「先去问真实周期」的写法才严谨。
2. **`fetch_dex_multi_live()` 挑合约的规则是自定的**（优先 USDC、名字最短）。如果某平台有多种合约，可能挑中的不是你想要的那一个，值得偶尔核对。
3. **所有抓取都依赖 `127.0.0.1:7897` 这个代理**。Clash 没开，看板里带按钮的抓取都会失败，这是设计如此，不是 bug。
