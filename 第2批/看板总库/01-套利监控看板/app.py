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
import json
import os

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="套利监控看板",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 路径与常量 ──────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # quant 探索
DATA_DIR = os.path.join(BASE, "数据")
CSV_PATH = os.path.join(DATA_DIR, "监控", "funding_history.csv")
ALERT_LOG = os.path.join(DATA_DIR, "监控", "告警记录.csv")
DEX_CSV = os.path.join(DATA_DIR, "监控", "dex_history.csv")
PUSH_CFG = os.path.join(BASE, "配置", "推送配置.json")
PACK_JSON = os.path.join(DATA_DIR, "1011情报包", "1011情报包-合并.json")

DEX_EXCHANGES = ["hyperliquid", "lighter"]
DEX_SYMBOLS = ["BTC/USDC:USDC", "ETH/USDC:USDC", "SOL/USDC:USDC"]

DEX_MULTI_CSV = os.path.join(DATA_DIR, "监控", "dex_multi_history.csv")
DEX_MULTI_EXCHANGES = ["hyperliquid", "lighter", "backpack", "aster",
                       "paradex", "extended", "dydx", "apex"]
DEX_MULTI_COINS = ["BTC", "ETH", "SOL"]

FALLBACK_HOURS = {"hyperliquid": 1, "lighter": 1, "backpack": 1,
                  "aster": 8, "paradex": 8}


def _funding_hours(label, d, market):
    """结算周期(小时)；推不出来返回 None。"""
    iv = (d or {}).get("interval")
    if isinstance(iv, str) and iv.endswith("h"):
        try:
            return float(iv[:-1])
        except ValueError:
            pass
    if isinstance(iv, (int, float)) and iv:
        return iv / 3600000 if iv > 1000 else float(iv)
    info = (market or {}).get("info") or {}
    fi = info.get("fundingInterval")
    if isinstance(fi, (int, float)) and fi:
        return fi / 3600000
    return FALLBACK_HOURS.get(label)


def _annual(label, rate, d, market):
    h = _funding_hours(label, d, market)
    if rate is None or not h:
        return None
    return rate * (24 / h) * 365 * 100

SYMBOL = "ETH/USDT:USDT"
PROXY = "http://127.0.0.1:7897"
EXCHANGES = ["binance", "okx", "bybit"]
ALERT_PCT = 5.0
COLORS = ["#1a569b", "#ED7D31", "#70AD47", "#c0392b", "#8e44ad", "#16a085"]


# ── 数据加载 ────────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_history() -> pd.DataFrame:
    if not os.path.exists(CSV_PATH):
        return pd.DataFrame(columns=["时间", "交易所", "单次费率", "年化(%)"])
    return pd.read_csv(CSV_PATH)


@st.cache_data(ttl=30)
def load_alerts() -> pd.DataFrame:
    if not os.path.exists(ALERT_LOG):
        return pd.DataFrame(columns=["时间", "年化差(%)"])
    return pd.read_csv(ALERT_LOG)


def push_channels() -> list:
    """看推送配置里到底填了哪些通道。"""
    if not os.path.exists(PUSH_CFG):
        return []
    try:
        cfg = json.load(open(PUSH_CFG, encoding="utf-8"))
    except Exception:
        return []
    names = [k for k in ("bark", "serverchan", "pushdeer", "wecom")
             if (cfg.get(k) or "").strip()]
    tg = cfg.get("telegram") or {}
    if tg.get("token") and tg.get("chat_id"):
        names.append("telegram")
    return names


@st.cache_data(ttl=30)
def load_dex() -> pd.DataFrame:
    if not os.path.exists(DEX_CSV):
        return pd.DataFrame(columns=["时间", "标的", "交易所", "资金费率", "年化(%)", "价格"])
    return pd.read_csv(DEX_CSV)


def fetch_dex_live(symbols) -> pd.DataFrame:
    """现场抓 Lighter 与 Hyperliquid（需要 Clash 代理）。"""
    import ccxt

    rows = []
    for label in DEX_EXCHANGES:
        try:
            ex = getattr(ccxt, label)({"httpsProxy": PROXY, "enableRateLimit": True})
            ex.load_markets()
        except Exception:
            continue
        for s in symbols:
            fr = pr = ann = None
            try:
                d = ex.fetch_funding_rate(s)
                fr = float(d["fundingRate"])
                ann = _annual(label, fr, d, ex.market(s))
            except Exception:
                pass
            try:
                t = ex.fetch_ticker(s)
                pr = float(t["last"]) if t.get("last") else None
            except Exception:
                pass
            rows.append({"标的": s, "交易所": label, "资金费率": fr,
                         "年化(%)": ann, "价格": pr})
    return pd.DataFrame(rows)


@st.cache_data(ttl=30)
def load_dex_multi() -> pd.DataFrame:
    if not os.path.exists(DEX_MULTI_CSV):
        return pd.DataFrame(columns=["时间", "币种", "平台", "年化(%)", "价格"])
    return pd.read_csv(DEX_MULTI_CSV)


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
        for coin in coins:
            cands = [s for s, m in mk.items()
                     if m.get("swap") and m.get("linear")
                     and (m.get("base") or "").upper() == coin]
            if not cands:
                continue
            cands.sort(key=lambda s: (0 if "USDC" in s else 1, len(s)))
            sym = cands[0]
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


@st.cache_data
def load_pack() -> list:
    if not os.path.exists(PACK_JSON):
        return []
    with open(PACK_JSON, encoding="utf-8") as f:
        return json.load(f)


def fetch_live() -> pd.DataFrame:
    """实时抓一次费率（需要 Clash 代理）。"""
    import ccxt

    rows = []
    for name in EXCHANGES:
        try:
            ex = getattr(ccxt, name)({"enableRateLimit": True, "httpsProxy": PROXY})
            d = ex.fetch_funding_rate(SYMBOL)
            rows.append({"交易所": name, "单次费率": float(d["fundingRate"]),
                         "年化(%)": float(d["fundingRate"]) * 3 * 365 * 100})
        except Exception:
            pass
    return pd.DataFrame(rows)


def append_history(df: pd.DataFrame) -> None:
    if df.empty:
        return
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    out = df.copy()
    out.insert(0, "时间", pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"))
    out.to_csv(CSV_PATH, mode="a", header=not os.path.exists(CSV_PATH),
               index=False, encoding="utf-8-sig")


hist = load_history()
pack = load_pack()

# ── 侧栏 ────────────────────────────────────────────────────
with st.sidebar:
    st.title("📡 套利监控看板")
    st.caption("quant 探索 · 资金费率 / 价差")
    st.divider()
    st.metric("标的", SYMBOL.split(":")[0])
    st.metric("告警阈值", f"{ALERT_PCT}%")
    st.divider()
    _chans = push_channels()
    st.subheader("🔔 值班状态")
    if _chans:
        st.success("已配推送：" + "、".join(_chans))
    else:
        st.warning("未配推送通道\n（只能看，不会喊）")
    st.caption(f"最后数据：{hist['时间'].iloc[-1] if not hist.empty else '暂无'}")
    st.divider()
    st.subheader("📑 导航")
    page = st.radio(
        "",
        ["🏠 总览", "📈 费率历史", "🚨 机会与告警", "🔔 告警记录", "🪙 DEX 对比", "🌐 多平台", "📚 1011 情报包", "🧭 使用说明"],
        label_visibility="collapsed",
    )
    st.divider()
    if st.button("🔄 实时抓取一次", use_container_width=True):
        live = fetch_live()
        if live.empty:
            st.error("抓取失败：检查 Clash 是否开着（代理 7897）")
        else:
            append_history(live)
            load_history.clear()
            st.success("已抓取并写入历史")
            st.rerun()

# ══════════════════════════════════════════════════════════
# 总览
# ══════════════════════════════════════════════════════════
if page == "🏠 总览":
    st.title("套利监控 · 总览")
    st.caption("资金费率快照 · 数据来自本地历史 CSV")

    if hist.empty:
        st.info("还没有历史数据。点侧栏「🔄 实时抓取一次」，或先跑一次监控脚本。")
        st.stop()

    latest_t = hist["时间"].iloc[-1]
    latest = hist[hist["时间"] == latest_t].copy()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("数据点", f"{hist['时间'].nunique()} 次")
    c2.metric("覆盖交易所", f"{hist['交易所'].nunique()} 家")
    if not latest.empty:
        hi = latest.loc[latest["年化(%)"].idxmax()]
        lo = latest.loc[latest["年化(%)"].idxmin()]
        spread = hi["年化(%)"] - lo["年化(%)"]
        c3.metric("最新年化差", f"{spread:.2f}%",
                  f"{'⚠️ 越阈值' if abs(spread) >= ALERT_PCT else '正常'}")
        c4.metric("费率最高", f"{hi['交易所']}", f"{hi['年化(%)']:.2f}%")
        c5.metric("费率最低", f"{lo['交易所']}", f"{lo['年化(%)']:.2f}%")
    st.caption(f"快照时间：{latest_t}")
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("最新费率（年化）")
        fig = px.bar(latest, x="交易所", y="年化(%)", color="交易所",
                     color_discrete_sequence=COLORS, text_auto=".2f")
        fig.update_layout(height=350, margin=dict(t=10, b=0, l=0, r=0),
                          showlegend=False)
        fig.add_hline(y=0, line_dash="dot", line_color="#888")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.subheader("费率占比（绝对值）")
        tmp = latest.copy()
        tmp["|年化|"] = tmp["年化(%)"].abs()
        fig = px.pie(tmp, names="交易所", values="|年化|", hole=0.4,
                     color_discrete_sequence=COLORS)
        fig.update_traces(textinfo="label+percent")
        fig.update_layout(height=350, margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("最新明细")
    st.dataframe(latest.style.format({"单次费率": "{:.8f}", "年化(%)": "{:.3f}"}),
                 use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════
# 费率历史
# ══════════════════════════════════════════════════════════
elif page == "📈 费率历史":
    st.title("费率历史")

    if hist.empty or hist["时间"].nunique() < 2:
        st.info("历史数据还不够画曲线。让监控脚本多跑几轮（`--loop 300`），或多次点「实时抓取」，这里就会长出走势。")
        if not hist.empty:
            st.dataframe(hist, use_container_width=True, hide_index=True)
        st.stop()

    names = st.multiselect("交易所", sorted(hist["交易所"].unique()),
                           default=sorted(hist["交易所"].unique()))
    sub = hist[hist["交易所"].isin(names)].copy()
    sub["时间"] = pd.to_datetime(sub["时间"])

    st.subheader("年化费率走势")
    fig = px.line(sub, x="时间", y="年化(%)", color="交易所",
                  markers=True, color_discrete_sequence=COLORS)
    fig.update_layout(height=420, margin=dict(t=10, b=0, l=0, r=0))
    fig.add_hline(y=0, line_dash="dot", line_color="#888")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    pivot = sub.pivot_table(index="时间", columns="交易所",
                            values="年化(%)", aggfunc="last").round(3)
    pivot["年化差(最高-最低)"] = (pivot.max(axis=1) - pivot.min(axis=1)).round(3)
    st.subheader("逐次明细（含价差）")
    st.dataframe(pivot, use_container_width=True)

# ══════════════════════════════════════════════════════════
# 机会与告警
# ══════════════════════════════════════════════════════════
elif page == "🚨 机会与告警":
    st.title("机会与告警")
    thr = st.slider("告警阈值（年化差 %）", 0.0, 20.0, ALERT_PCT, 0.5)

    if hist.empty:
        st.info("还没有数据。")
        st.stop()

    g = hist.groupby("时间")["年化(%)"].agg(["max", "min"])
    g["年化差"] = (g["max"] - g["min"]).round(2)
    hits = g[g["年化差"] >= thr]

    c1, c2 = st.columns(2)
    c1.metric("观测次数", f"{len(g)}")
    c2.metric("越过阈值次数", f"{len(hits)}",
              f"{'有' if len(hits) else '暂无'}")

    st.divider()
    st.subheader("年化差走势")
    fig = px.bar(g.reset_index(), x="时间", y="年化差",
                 color_discrete_sequence=["#1a569b"])
    fig.add_hline(y=thr, line_dash="dash", line_color="#c0392b",
                  annotation_text=f"阈值 {thr}%")
    fig.update_layout(height=360, margin=dict(t=10, b=0, l=0, r=0))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    if hits.empty:
        st.success("没有越过阈值的时刻。")
    else:
        st.subheader(f"越过阈值的 {len(hits)} 个时刻")
        st.dataframe(hits.reset_index(), use_container_width=True, hide_index=True)
        st.caption("思路：在费率最高的所做空、最低的所做多，赚费率差。⚠️ 仅为费率差，未计价差、手续费、滑点与风险。")

# ██████████████████████████████████████████████████████
# DEX 对比
# ██████████████████████████████████████████████████████
elif page == "🪙 DEX 对比":
    st.title("Lighter × Hyperliquid")
    st.caption("两家去中心化永续平台的资金费率与价格对比")

    if st.button("🔄 现场抓一次（需 Clash 开着）", use_container_width=False):
        with st.spinner("正在抓 Lighter 与 Hyperliquid ..."):
            live = fetch_dex_live(DEX_SYMBOLS)
        if live.empty:
            st.error("抓取失败：确认 Clash 开着（代理 7897）")
        else:
            st.session_state["dex_live"] = live
            st.success(f"抓到 {len(live)} 条")

    live = st.session_state.get("dex_live")
    if live is None or live.empty:
        hist = load_dex()
        if hist.empty:
            st.info("还没有数据。点上面的按钮现场抓一次。")
            st.stop()
        st.caption("以下是历史最后一次快照（点上面按钮可刷新）")
        live = hist[hist["时间"] == hist["时间"].iloc[-1]].copy()
        live = live.rename(columns={"资金费率": "资金费率", "年化(%)": "年化(%)"})

    piv = live.pivot_table(index="标的", columns="交易所",
                           values="年化(%)", aggfunc="last")
    if not piv.empty:
        piv["年化差"] = (piv.max(axis=1) - piv.min(axis=1)).round(2)
        piv = piv.sort_values("年化差", ascending=False)

        st.subheader("资金费率年化对比")
        fig = px.bar(piv.reset_index().melt(id_vars="标的", value_vars=DEX_EXCHANGES,
                                            var_name="平台", value_name="年化(%)"),
                     x="标的", y="年化(%)", color="平台", barmode="group",
                     color_discrete_sequence=COLORS)
        fig.add_hline(y=0, line_dash="dot", line_color="#888")
        fig.update_layout(height=380, margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("年化差排名")
        st.dataframe(piv, use_container_width=True)

    st.divider()
    st.subheader("原始数据")
    st.dataframe(live, use_container_width=True, hide_index=True)

    st.caption("⚠️ 年化按 8 小时结算粗算，未计价差、手续费、滑点与风险，不构成投资建议。")

# ██████████████████████████████████████████████████████
# 多平台
# ██████████████████████████████████████████████████████
elif page == "🌐 多平台":
    st.title("多平台费率横截面")
    st.caption("一次铺开多家去中心化永续平台的资金费率")

    if st.button("🔄 现场抓一次（需 Clash 开着）"):
        with st.spinner("正在抓多家平台 ..."):
            live = fetch_dex_multi_live(DEX_MULTI_COINS, DEX_MULTI_EXCHANGES)
        if live.empty:
            st.error("抓取失败：确认 Clash 开着（代理 7897）")
        else:
            st.session_state["multi_live"] = live
            st.success(f"抓到 {len(live)} 条")

    live = st.session_state.get("multi_live")
    if live is None or live.empty:
        hist = load_dex_multi()
        if hist.empty:
            st.info("还没有数据。点上面的按钮现场抓一次。")
            st.stop()
        st.caption(f"以下为历史快照：{hist['时间'].iloc[-1]}")
        live = hist[hist["时间"] == hist["时间"].iloc[-1]].copy()

    piv = live.pivot_table(index="平台", columns="币种", values="年化(%)", aggfunc="last")
    order = [c for c in DEX_MULTI_COINS if c in piv.columns]
    if order:
        piv = piv[order]
    piv["最大差"] = (piv.max(axis=1) - piv.min(axis=1)).round(2) if not piv.empty else None

    st.subheader("年化费率 · 平台 × 币种")
    plot = live.dropna(subset=["年化(%)"])
    if not plot.empty:
        fig = px.bar(plot, x="平台", y="年化(%)", color="币种", barmode="group",
                     color_discrete_sequence=COLORS)
        fig.add_hline(y=0, line_dash="dot", line_color="#888")
        fig.update_layout(height=400, margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)
    st.dataframe(piv, use_container_width=True)

    st.divider()
    st.subheader("机会提示（费率差）")
    for c in order:
        col = piv[c].dropna()
        if len(col) < 2:
            st.caption(f"{c}: 数据不足")
            continue
        hi, lo = col.idxmax(), col.idxmin()
        st.markdown(f"- **{c}**：最高 {hi} ({col[hi]:+.2f}%) ／ 最低 {lo} ({col[lo]:+.2f}%) "
                    f"→ 差 **{col[hi]-col[lo]:.2f}%**")

    st.divider()
    with st.expander("原始数据"):
        st.dataframe(live, use_container_width=True, hide_index=True)

    st.caption("⚠️ 年化按 8 小时结算粗算；extended/dydx/apex 的费率接口尚未适配，会显示为空。不构成投资建议。")

# ══════════════════════════════════════════════════════════
# 1011 情报包
# ══════════════════════════════════════════════════════════
elif page == "📚 1011 情报包":
    st.title("1011 闪崩 · 情报包")
    st.caption("来源：crash.wqu.guru ｜ 90 条推文，按时间排列")

    if not pack:
        st.info("未找到情报包数据。")
        st.stop()

    df = pd.DataFrame([{
        "时间": t.get("sourceLocalTime") or t.get("timestamp", ""),
        "账号": t.get("userId", ""),
        "正文": (t.get("content", "") or "").replace("\n", " "),
        "情绪": (t.get("analysis") or {}).get("sentiment", ""),
        "链接": t.get("link", ""),
        "话题": "、".join((t.get("analysis") or {}).get("topics", [])[:4]),
    } for t in pack])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("推文", f"{len(df)} 条")
    c2.metric("账号", f"{df['账号'].nunique()}")
    c3.metric("语言", f"中{sum(1 for t in pack if (t.get('analysis') or {}).get('language')=='zh')} / 英{sum(1 for t in pack if (t.get('analysis') or {}).get('language')=='en')}")
    top_topic = pd.Series([x for t in pack for x in (t.get("analysis") or {}).get("topics", [])]).value_counts()
    c4.metric("最高频话题", top_topic.index[0] if len(top_topic) else "-")
    st.divider()

    col1, col2 = st.columns([3, 2])
    with col1:
        st.subheader("话题分布")
        tt = top_topic.head(10).reset_index()
        tt.columns = ["话题", "次数"]
        fig = px.bar(tt, x="次数", y="话题", orientation="h",
                     color_discrete_sequence=["#1a569b"])
        fig.update_layout(height=360, margin=dict(t=10, b=0, l=0, r=0),
                          yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.subheader("发文最多的账号")
        ac = df["账号"].value_counts().head(8).reset_index()
        ac.columns = ["账号", "条数"]
        fig = px.pie(ac, names="账号", values="条数", hole=0.4,
                     color_discrete_sequence=COLORS)
        fig.update_traces(textinfo="label+value")
        fig.update_layout(height=360, margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("检索")
    q = st.text_input("关键词（账号 / 正文）", "")
    show = df.copy()
    if q:
        m = show["账号"].str.contains(q, case=False, na=False) | \
            show["正文"].str.contains(q, case=False, na=False)
        show = show[m]
    st.caption(f"命中 {len(show)} 条")
    st.dataframe(
        show[["时间", "账号", "情绪", "话题", "正文"]],
        use_container_width=True, hide_index=True, height=460,
        column_config={"链接": st.column_config.LinkColumn("链接")},
    )

# ██████████████████████████████████████████████████████
# 告警记录
# ██████████████████████████████████████████████████████
elif page == "🔔 告警记录":
    st.title("告警记录")
    st.caption("值班脚本每次越阈都会记一笔，这里是它的账本")

    alerts = load_alerts()
    c1, c2 = st.columns(2)
    c1.metric("累计告警", f"{len(alerts)} 次")
    c2.metric("已推送", f"{int((alerts['已推送'] == '是').sum()) if '已推送' in alerts.columns and not alerts.empty else 0} 次")

    if alerts.empty:
        st.info("还没有告警记录。让值班脚本跑起来（双击 `脚本\\启动监控.bat`），越阈时这里就会有。")
        st.stop()

    st.divider()
    st.subheader("告警明细")
    st.dataframe(alerts, use_container_width=True, hide_index=True)

    if "年化差(%)" in alerts.columns and len(alerts) > 1:
        st.subheader("告警次数 / 年化差趋势")
        fig = px.line(alerts, x="时间", y="年化差(%)", markers=True,
                      color_discrete_sequence=["#c0392b"])
        fig.update_layout(height=320, margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)

# ══════════════════════════════════════════════════════════
# 使用说明
# ══════════════════════════════════════════════════════════
elif page == "🧭 使用说明":
    st.title("使用说明")
    st.markdown("""
### 这个看板是什么
把「quant 探索」里的监控数据，做成一块能看的仪表盘。版式参照你的 `港股打新仪表盘`。

### 数据从哪来
| 页 | 数据源 |
|---|---|
| 总览 / 费率历史 / 机会与告警 | `数据\\监控\\funding_history.csv` |
| 1011 情报包 | `数据\\1011情报包\\1011情报包-合并.json` |

### 怎么让它长数据
```powershell
cd ".\\quant 探索"
python 脚本\\monitor_funding_v2.py --loop 300 --alert 5
```
或者在看板侧栏点 **🔄 实时抓取一次**。

### 前提
- **Clash 开着**（代理 `127.0.0.1:7897`），否则抓不到币安/OKX/Bybit。
- 用 Streamlit 跑：
```powershell
cd ".\\quant 探索"
python -m streamlit run 看板\\app.py
```

### 注意
- 费率年化是**粗略估算**（按 8 小时结算、365 天）。
- 一切数字**不构成投资建议**。
""")
