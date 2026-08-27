Inspired by [https://github.com/RuleViz/ModelScopeApiRouter](https://github.com/RuleViz/ModelScopeApiRouter)，增加了模型级别，负载均衡，熔断，主动检测等特性，增加vercel部署兼容。
2026-08 升级：由单提供商切换为**多提供商路由**（每条配置自带 `base_url` / `model_id` / API key），按配额批量轮换，用于聚合多家大模型公开服务的免费额度；原单提供商路由原样保留在 `/old` 前缀下。

# 多提供商智能路由器 (Multi-Provider Smart Router)

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.95%2B-green)
![Vercel](https://img.shields.io/badge/Vercel-Ready-black)
![License](https://img.shields.io/badge/license-MIT-blue)

**聚合多家大模型免费额度的 OpenAI 兼容路由网关**

---

## 📖 项目简介

Multi-Provider Smart Router 是一个基于 FastAPI 构建的 AI 模型网关。它把多个提供商的免费额度"拼"成一个池子：每条提供商配置（`base_url` + `model_id` + API key）按配额批量轮换，配合故障转移、限流冷却和熔断，让你用统一的 OpenAI 兼容接口白嫖多家服务，同时避免单点故障和限流。

老的单提供商路由（ModelScope 全局 key + level 优先级）完整保留在 `/old` 前缀下，行为与升级前一致。

完全兼容 OpenAI API 格式，可直接接入现有的 AI 工具链（如 Cursor, NextChat, LangChain 等）。

## ✨ 核心功能

- **🔄 多提供商批量轮换**: 每条配置连续成功服务 5 次（可配）后切换到下一条，公平分摊各家额度
- **🛡️ 自动故障转移**: 当前配置调用失败自动试下一家；失败不消耗轮换配额
- **⏳ 限流冷却**: 某配置被 429 限流后冷却 300 秒（可配）自动恢复，不再一封封一天
- **🚦 熔断器**: 连续 3 次失败自动熔断 30 秒（新路由为修正版实现，见下方说明）
- **🔍 健康探测开关**: 启动探测默认本地开、Vercel 关（冷启动探测会消耗免费额度，可用 `HEALTH_PROBE` 覆盖）
- **🕰️ 老路由保留**: `/old/*` 端点原样保留单提供商 + level 路由的旧行为
- **🔐 Token 认证**: 新老路由统一支持 Bearer Token 认证
- **📊 健康端点**: `/health` 查看轮换状态与各提供商统计，`/old/health` 查看老路由状态
- **🔌 OpenAI 兼容**: 与 OpenAI `v1/chat/completions` 完全兼容
- **🌊 流式响应支持**: 完美支持 Server-Sent Events (SSE) 流式输出，流正常结束才计成功

## 🚀 快速启动

### 本地运行

```bash
pip install -r requirements.txt
python -m refactored_router.main
```

服务将在 `http://localhost:2166` 启动。

### Vercel 部署

1. 将代码推送到 GitHub
2. 在 Vercel 中导入项目
3. 配置环境变量：
   - `MS_API_KEY` - 第 1 个 ModelScope API Key（老路由也用它）
   - `MS_API_KEY_2` - 第 2 个 ModelScope API Key（按 providers.json 引用添加，可继续加 `MS_API_KEY_3` 等）
   - `TOKEN` - 访问 Token（可选，用于保护 API）
4. 部署完成

## ⚙️ 配置详解

### 环境变量

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|------|
| `MS_API_KEY` | 老路由（/old）使用的 ModelScope API Key，也是示例提供商配置的 key | 无 | ✅ 是 |
| `MS_BASE_URL` | 老路由的模型服务 URL | `https://api-inference.modelscope.cn/v1` | ❌ 否 |
| `TOKEN` | API 访问 Token（新老路由共用） | 无 | ❌ 否 |
| `PORT` | 服务监听端口（本地） | `2166` | ❌ 否 |
| `ROTATION_QUOTA` | 每条配置轮换前连续服务的次数 | `5` | ❌ 否 |
| `LIMITED_COOLDOWN` | 限流(429)后多少秒恢复可用 | `300` | ❌ 否 |
| `HEALTH_PROBE` | 启动探测开关（`1/0`），缺省本地开、Vercel 关 | 见左 | ❌ 否 |
| `ROUTER_ALIAS` | `/v1/models` 返回的模型别名 | `modelscope-router` | ❌ 否 |

### 提供商配置 (providers.json) — 新路由

每条是一个完整的提供商三元组，轮换、熔断、限流、统计都按 `name` 记账：

```json
[
  {"name": "MS-DSV4Pro-K1", "base_url": "https://api-inference.modelscope.cn/v1", "model_id": "deepseek-ai/DeepSeek-V4-Pro-0813", "api_key_env": "MS_API_KEY", "quota": 5},
  {"name": "MS-DSV4Pro-K2", "base_url": "https://api-inference.modelscope.cn/v1", "model_id": "deepseek-ai/DeepSeek-V4-Pro-0813", "api_key_env": "MS_API_KEY_2", "quota": 5}
]
```

- **name**: 内部标识，**必须唯一**（重名的配置会被跳过并告警；同一模型挂多个 key 时用不同名字区分，如 `-K1`/`-K2`）
- **base_url**: 该提供商自己的服务地址（以 `/v1` 结尾）
- **model_id**: 转发时替换进请求体的真实模型 ID
- **api_key_env**: 存放 API key 的**环境变量名**（key 本身放 `.env` / Vercel 环境变量，不进仓库）；变量未设置时该配置自动标记不可用，不影响其他配置
- **quota**: 该配置每轮连续服务多少次，缺省取 `ROTATION_QUOTA`

接入新提供商只需加一行，并在环境变量里补上对应 key。

### 模型配置 (config.json) — 老路由 (/old)

老路由专用，格式不变：

```json
[
  {
    "level": 1,
    "name": "deepseek-v3-2",
    "model_id": "deepseek-ai/DeepSeek-V3.2",
    "estimated_limit": 50
  }
]
```

- **level**: 优先级，数字越小越优先使用
- **name**: 内部标识名称（需唯一）
- **model_id**: ModelScope 上的真实模型 ID
- **estimated_limit**: 每日预估调用次数限制（仅用于展示）

## 🛤️ 轮换语义（新路由）

- 游标指向"当前值日"的配置，它连续**成功**服务满 `quota` 次后，游标切到下一条配置，循环往复
- 当前配置调用失败：本次请求自动故障转移到下一条可用配置；失败不消耗配额，游标不动
- 当前配置被限流或熔断：游标让位给下一条可用配置，开启新一轮
- 429 限流：标记后冷却 `LIMITED_COOLDOWN` 秒自动恢复
- 熔断：连续 3 次失败熔断 30 秒（注意：老实现因 `open_time=0` 时判断恒真，熔断从未真正生效；为保持 `/old` 行为等价不做修改，仅新路由用修正版）
- 请求体里直接写某条配置的 `model_id`（而非别名）可固定从该配置开始尝试
- 轮换状态持久化在 `DATA_DIR`（Vercel 上是 `/tmp`）；serverless 多实例各自计数，属于**近似轮换**，按设计接受

## 💻 使用指南

### API 端点

| 端点 | 说明 |
|------|------|
| `/` | 根路径，返回 API 信息 |
| `/health` | 健康检查：轮换状态 + 各提供商统计 |
| `/v1/chat/completions` | 聊天接口（OpenAI 兼容，走多提供商轮换） |
| `/v1/models` | 模型列表（返回路由别名） |
| `/old/` | 老路由根路径 |
| `/old/health` | 老路由健康检查 |
| `/old/v1/chat/completions` | 老路由聊天接口（单提供商 + level 路由） |
| `/old/v1/models` | 老路由模型列表 |

### 调用示例

```bash
# 非流式调用
curl https://your-vercel-app.vercel.app/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "modelscope-router",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'

# 流式调用
curl -N https://your-vercel-app.vercel.app/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "modelscope-router",
    "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
    "stream": true
  }'

# 老路由（升级前的行为）
curl https://your-vercel-app.vercel.app/old/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "modelscope-router",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

### Python 客户端

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-token", 
    base_url="https://your-vercel-app.vercel.app/v1"
)

response = client.chat.completions.create(
    model="modelscope-router",
    messages=[{"role": "user", "content": "写一首关于AI的诗"}],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

## 📁 目录结构

```
.
├── README.md                # 说明文档
├── vercel.json              # Vercel 配置
├── requirements.txt         # Python 依赖
├── test_api.sh              # API 测试脚本
├── logo.jpg                 # 项目 Logo
├── roo-code-example.png     # UI 截图
├── .gitignore               # Git 忽略配置
├── api/                     # Vercel Serverless 函数
│   ├── __init__.py
│   └── index.py             # 入口文件
└── refactored_router/       # 核心代码包
    ├── __init__.py
    ├── main.py              # FastAPI 应用（新路由 + 挂载 /old）
    ├── settings.py          # 配置加载（含 providers 校验）
    ├── providers.json       # 多提供商配置
    ├── rotation.py          # 批量轮换服务（游标 + 配额）
    ├── provider_api.py      # 多提供商网络层
    ├── stats.py             # 统计与熔断（新老各一份）
    ├── legacy.py            # 老路由（原样冻结，挂 /old）
    ├── network.py           # 老路由网络层
    ├── schema.py            # 数据模型
    ├── ui.py                # 终端 UI（新老双区显示）
    ├── config.json          # 老路由模型配置
    └── router_data/         # 运行时数据（统计/轮换状态，不入 git）
```

## 🖥️ 监控

- **本地**: 终端 Rich UI 实时显示新路由提供商（含轮换进度）与老路由模型两组状态
- **Vercel**: 访问 `/health` 查看轮换状态与各提供商统计（`/old/health` 为老路由）

## 📄 许可证

MIT License
