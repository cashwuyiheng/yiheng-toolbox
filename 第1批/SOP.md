# SOP · 操作规范

> **单一入口**。本项目所有标准流程都在这份文档里；动手前先找到对应小节。
> 每套流程固定四段：**适用** → **铁律** → **步骤** → **验收**。
> 踩过的坑统一记在 `9-工作流\踩坑记录.md`，本文只引编号。

**目录**

- [一、跨平台费率对比](#一跨平台费率对比)
- [二、用 Tampermonkey 扒推文](#二用-tampermonkey-扒推文)
- [三、通用规矩](#三通用规矩)
- [四、踩坑索引](#四踩坑索引)

---

## 一、跨平台费率对比

### 适用
比较任意多个平台（DEX / CEX）的**资金费率、年化、价差**。
触发场景：新写对比脚本、往看板加一页数据、手工跑横向对比。

### 铁律

1. **周期先行**——拿到费率先问"多久结一次"。
2. **周期要落在表上**——任何输出年化的表，**必须带一列"周期"**。
3. **取不到就不猜**——查不到就显示"—"，绝不用默认值糊过去。

> 为什么：周期不同，年化能差 8 倍（见 [BUG-001](#四踩坑索引)）。口径不对，比的是假象。

### 步骤

- [ ] 每个平台都取到费率？（取不到的**明确标"—"**，不默默跳过）
- [ ] 每个平台的**结算周期**取到？（优先级：`rate["interval"]` → `market["info"]["fundingInterval"]`（毫秒 ÷ 3600000） → 兜底表 → 取不到就"—"）
- [ ] 年化公式用**该平台自己的周期**，不是全局常数？
- [ ] 价格与费率**分开列**？（两者结论常相反：价差小、费率差大）
- [ ] 结论段落写出**周期口径**？
- [ ] 脚注有"未计价差/手续费/滑点/风险"？

### 周期表（带出处）

| 平台 | 周期 | 出处 |
|---|---|---|
| hyperliquid | 1 小时 | https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding |
| lighter | 1 小时 | https://docs.lighter.xyz/trading/funding |
| backpack | 1 小时 | 接口 `info.fundingInterval = 3600000` ms |
| aster | 8 小时 | https://www.asterdex.com/en/futures/futures-info/real-time-funding-rate |
| paradex | 8 小时 | 接口返回 `interval = 8h` |
| binance / okx / bybit | 8 小时 | 各自费率页（币安：00:00 / 08:00 / 16:00 UTC） |

```
1h → rate × 24 × 365      8h → rate × 3 × 365
```

### 代码骨架

```python
FALLBACK_HOURS = {"hyperliquid": 1, "lighter": 1, "backpack": 1, "aster": 8, "paradex": 8}

def funding_hours(label, rate_dict, market):
    """结算周期(小时)；推不出来返回 None（不猜）。"""
    iv = (rate_dict or {}).get("interval")
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

def annual(rate, hours):
    return rate * (24 / hours) * 365 * 100 if (rate is not None and hours) else None
```

已落地：`脚本\scan_dex_multi.py`、`脚本\scan_dex.py`、`脚本\monitor_dex.py`、`看板\app.py`。

### 已知未适配

| 平台 | 状态 |
|---|---|
| extended / apex | ccxt 取不到费率（抛 `NotSupported`），但价格能取 |
| dydx | 完全取不到，符号格式不同，需单独适配 |
| edgeX / variational / ethereal | ccxt 不收录，需各自官方 API |

**原则**：表里**留空位并标注**，不隐藏、不用 0 顶替。

### 验收

拿一个**真实盘面**核对量级：打开该平台 App 看它显示的"资金年化利率"，与脚本输出对齐（允许因费率实时波动有小差）。

---

## 二、用 Tampermonkey 扒推文

### 适用
把任意 X（推特）账号的**历史推文**批量导出成本地文件。

### 铁律

1. **逐年搜**——个人主页只给最新 **3200 条**；用 `from:` + `since:`/`until:` **逐年**捞，绕过上限。
2. **导出再切年**——换下一年之前，务必先导出，否则数据被新页面冲掉。
3. **必勾元数据**——导出时勾 **Include all metadata**，否则拿不到"回复了哪条推"的引用，对话拼不起来。

### 步骤 A · 安装（只做一次）

- [ ] **装油猴**：Edge 到 `https://microsoftedge.microsoft.com/addons`，Chrome 到 `chrome.google.com/webstore`，搜 **Tampermonkey** → 获取/添加（作者 **Jan Biniok**）
- [ ] **装导出脚本**（二选一）
  - 网址：
    ```
    https://github.com/prinsss/twitter-web-exporter/releases/latest/download/twitter-web-exporter.user.js
    ```
  - 或把本地 `quant 探索\twitter-web-exporter.user.js` **拖进浏览器窗口**
  - 油猴弹安装页 → 点「安装」
- [ ] **登录 X**：打开 `https://x.com` 登录
- [ ] **验收**：X 页面**左侧**浮出小面板，带 **🐈 小猫按钮**

> 本地留档版本：**v1.4.3**。

### 步骤 B · 逐年导出（核心循环）

语句模板：`from:<账号> since:<年>-01-01 until:<次年>-01-01`

也可直接改网址栏（`%3A` = 冒号）：

```
https://x.com/search?q=from%3AyourQuantGuy+since%3A2014-01-01+until%3A2015-01-01&f=live
```

每年的动作：

- [ ] 粘贴语句，回车，**切到「最新」标签页**（不是「热门」）
- [ ] **一路往下滚到底**，让数据全加载（左侧面板条数会涨）
- [ ] 点面板 **↗** 看抓了多少条
- [ ] **Export Data** → 格式 **JSON** → **勾 Include all metadata** → 下载
- [ ] 重命名成带年份，如 `yourQuantGuy-2014.json`
- [ ] **导出后再切下一年**

### 步骤 C · 回复与对话（不抓就漏一半）

- [ ] **只捞回复**：语句尾加 `filter:replies`，逐年再跑一轮
      ```
      from:yourQuantGuy filter:replies since:2014-01-01 until:2015-01-01
      ```
- [ ] **只要原创**：算子前加减号 `-filter:replies`
- [ ] **补漏**：个人主页的 **「回复」标签页** 先滚一遍
- [ ] **整条对话**：用 `conversation_id:<数字>` 整串拉出

> **私信（DM）拿不到**——只有账号本人能看，脚本导不了。这是彻底盲区，先把预期放低。

### 步骤 D · 收尾

- [ ] 合并所有年份 JSON
- [ ] **按 id 去重**（逐年区间边界会重叠）
- [ ] 按时间线排序
- [ ] 落成 `数据\yourQuantGuy-推文合并.json` + `数据\yourQuantGuy-推文全档.md`
- [ ] 需要图文版：跑 `脚本\build_html_archive.ps1`
- [ ] 媒体另下；HTML 用**相对路径**引用，**档案与图片文件夹必须同级**

**参考产出（实测）**：379 条推文（2025-01-05 ~ 2026-09-14）、248 张图片（34.5 MB）。

### 风险与限制

- **速率限制**：X 会限流，抓累了停几分钟，别硬刷。
- **结果仍可能不全**：已删推文、未进索引的旧帖、部分媒体可能缺。
- **只在电脑网页版**；手机 App 不行。
- **平台条款**：抓取 X 数据踩在条款边上，自行权衡。
- **凭据**：用**你自己的账号**登录，任何情况下不外借密码。

### 验收

- [ ] 左侧出现 **🐈 小猫按钮**
- [ ] 每年 JSON 齐全，且**导出后才切年**
- [ ] 回复单独抓过一轮
- [ ] 每份导出都勾了 **Include all metadata**
- [ ] 合并**去重**后，条数 > 单年最大值
- [ ] 抽查一条，能对上它的原推链接

---

## 三、通用规矩

1. **口径先行**：比任何数字前，先确认定义与单位（周期、时间区、币种、价格类型）。
2. **取不到不猜**：宁可显示"—"，不用默认值填充。
3. **引用必附出处**：`来源 + 时间 + 链接 + 本地文件 + 原文句子`，并**区分原话与推断**。
4. **留痕**：数据落盘、产物归档，别只留在终端里。
5. **验收要核**：任何修正，都要拿一个**真实外部盘面**对一次。
6. **不编造**：查不到就说查不到。

---

## 四、踩坑索引

| 编号 | 一句话 | 详见 |
|---|---|---|
| BUG-001 | 跨平台年化口径不统一（8h 一刀切），差 8 倍 | `9-工作流\踩坑记录.md` |

---

## 五、相关文件

| 文件 | 说明 |
|---|---|
| `9-工作流\踩坑记录.md` | 踩过的坑，逐条留档 |
| `quant 探索\教程-安装与使用.md` | 油猴安装的零基础版（面向第一次装扩展的人） |
| `quant 探索\操作-导出推文.md` | 逐年导出的速查版 |
| `quant 探索\SOP-跨平台费率对比.md` | 费率对比的独立版 |
| `quant 探索\SOP-用Tampermonkey扒推文.md` | 扒推文的独立版 |
| `CLAUDE.md` | 项目门厅，含本文件的入口 |
