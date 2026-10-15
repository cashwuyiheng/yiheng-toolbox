# AI 中转站（本地优先）

> 日期：2026-10-10　｜　位置：`.\AI中转站\`
> 目标：一个地址、一套 key，按规则把请求分给不同模型；数据只在你和上游之间走。

## 一、它是什么

在本机起一个 OpenAI 风格的网关（默认 `http://127.0.0.1:8788/v1`）。
你的聊天客户端、脚本、编辑器插件都指向它，由它决定这条请求去哪家上游模型。

解决三个实际问题：
1. **换模型不用改客户端**。客户端永远写 `127.0.0.1:8788`，后台换谁由这里决定。
2. **key 集中管理**。上游 key 只存在这一个本地文件里，客户端不碰。
3. **数据可控**。中转站自身不落你的 prompt（日志只记「路由到谁」，默认不记内容）。

## 二、架构

```
客户端(聊天/脚本/IDE)
        │  OpenAI 格式请求，base_url = 127.0.0.1:8788/v1
        ▼
┌──────────────────────────────┐
│  ai_relay.py（本机，127.0.0.1）│
│  ① 鉴权(可选 relay_token)      │
│  ② 路由：显式名 / 上游名/模型 / │
│          关键字 / 默认          │
│  ③ 转发 + 流式透传             │
└──────────────────────────────┘
        │  只转发到你自己配置的上游
   ┌────┴─────┬─────────┐
   ▼          ▼         ▼
 qwen      deepseek   其他兼容 OpenAI 的端点
```

## 三、快速开始

```powershell
# 1. 填配置
copy config.example.json config.json
#    编辑 config.json：填每个上游的 base_url、api_key、model

# 2. 启动
python ai_relay.py

# 3. 客户端 base_url 指向
http://127.0.0.1:8788/v1
```

看看活着没：浏览器打开 `http://127.0.0.1:8788/healthz`，或 `GET /v1/models` 列上游。

## 四、配置说明（config.json）

| 键 | 含义 |
|---|---|
| `listen_host` / `listen_port` | 监听地址与端口，默认 `127.0.0.1:8788`（只对本机开放） |
| `relay_token` | 本地鉴权口令；填了以后客户端要带 `Authorization: Bearer <口令>`。留空则不校验 |
| `default_upstream` | 兜底走哪个上游 |
| `log_path` | 日志文件；留空则只打印不落盘 |
| `upstreams[]` | 上游列表：`name` / `base_url` / `api_key` / `model` / `timeout` / `proxy` |
| `upstreams[].proxy` | 该上游单独走代理，如 `http://127.0.0.1:7897`；留空走直连 |
| `routes[]` | 路由规则：`match.keywords`（命中最后一条 user 消息）或 `match.model_prefix` |

## 五、路由规则

按顺序判断，命中即用：

1. 客户端 `model` 写成 `上游名/真实模型` → 用该上游，并覆盖模型名。
2. 客户端 `model` 写成 `上游名` → 用该上游。
3. `model` 为 `auto` 或空 → 按 `routes` 关键字 / 前缀匹配，命中就用规则里的上游。
4. 都没命中 → `default_upstream`，再退到第一个上游。

例子：客户端写 `deepseek/deepseek-reasoner`，就用 deepseek 上游、模型名换成 `deepseek-reasoner`。

## 六、安全边界

- **只听 127.0.0.1**，不对外网开放；同一台机器上的程序才能访问。
- **不改写你的数据**，转发后即走即弃，不缓存对话。
- **日志不记内容**，只记「时间 + 路由到哪个上游 + 模型 + 是否流式」。
- **要不要 proxy 由你定**，按上游单独开，避免给国内端点白白套梯子。
- 想再紧一层：填 `relay_token`，客户端带口令才放行。

## 七、目录结构

```
AI中转站/
├── ai_relay.py             # 主程序（纯标准库，零依赖）
├── config.example.json     # 配置模板
├── config.json             # 你的实际配置（自己建，别外传）
├── README.md               # 本文件
└── _调试脚本/
    └── test_relay.py       # 端到端自测（起假上游，不联网）
```

## 八、自测结果

起两个假上游（qwen / deepseek），验证四类路由 + 健康检查，全部通过：

| 用例 | 期望 | 实测 |
|---|---|---|
| `auto` 无关键字 | qwen/qwen-plus | ✅ |
| 含"写文章" | deepseek/deepseek-chat | ✅ |
| 显式 `qwen` | qwen/qwen-plus | ✅ |
| `deepseek/deepseek-reasoner` | deepseek/deepseek-reasoner | ✅ |
| `/healthz` | status=ok | ✅ |

## 九、下一步可以加

- 用量统计与成本核算（每个上游各自计 token）
- 失败自动换备用上游（和推特监控的失败告警一个思路）
- 更细的路由：按 token 长度、按时间段、按调用方
- 接进你现有的推送通道，出错时推一条

## 十、免费额度池模式（推荐，把乱的收拢成一条线）

```
客户端 → ai_relay(127.0.0.1:8788/v1) → free_pool → 还有免费额度的模型
```

- `config.json` 里 `default_upstream` 设为 `free-pool`，`upstreams` 只放 `{"name":"free-pool","type":"pool"}`。
- 网关收到请求后，**自动**去池里挑一个「还有免费额度」的模型（可传 `model` 名做优先提示，传 `auto` 则随便挑）。
- 哪个模型返回 403（额度尽）就**自动换下一个**。
- 两个平台：百炼（借微信监控里的 key）+ 千问AI平台（`千问平台配置.json`）。
- 看板：`python make_pool_dashboard.py` → `额度池看板.html`。

自测：本地网关 → 池 → 免费模型，普通 + 流式都通过。
