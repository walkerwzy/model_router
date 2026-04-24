Inspired by [https://github.com/RuleViz/ModelScopeApiRouter](https://github.com/RuleViz/ModelScopeApiRouter)，增加了模型级别，负载均衡，熔断，主动检测等特性，增加vercel部署兼容。

# ModelScope 智能模型路由器 (ModelScope Smart Router)

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.95%2B-green)
![Vercel](https://img.shields.io/badge/Vercel-Ready-black)
![License](https://img.shields.io/badge/license-MIT-blue)

**用于 ModelScope 服务的企业级负载均衡与高可用路由网关**

</div>

---

## 📖 项目简介

ModelScope Smart Router 是一个基于 FastAPI 构建的高性能 AI 模型网关。它就像一个智能交通指挥官，旨在解决**单点故障**和**API调用限流**问题。通过智能路由算法，它能自动管理多个 ModelScope 模型实例，实现负载均衡、故障转移（Failover）和精细化的限流控制，确保您的 AI 应用始终保持高可用性。

无论您是个人开发者还是企业用户，都可以通过本系统统一管理 API 访问，提升服务的稳定性和成功率。完全兼容 OpenAI API 格式，可直接接入现有的 AI 工具链（如 Cursor, NextChat, LangChain 等）。

## ✨ 核心功能

- **🤖 智能路由策略**: 按 level 优先级选模型（level 1 > 2 > 3），同 level 内负载均衡
- **⚖️ 负载均衡**: 基于调用次数的负载均衡，防止单一模型过载
- **🛡️ 自动故障转移**: 当某个模型调用失败或超时，自动无缝切换到备用模型
- **🚦 熔断器**: 连续 3 次失败自动熔断 30 秒，避免反复尝试已挂的模型
- **🔍 健康探测**: 启动时自动探测所有模型可用性，实时更新状态
- **🔐 Token 认证**: 支持 Bearer Token 认证，保护 API 访问安全
- **📊 健康端点**: 提供 `/health` 接口查看模型状态和统计信息
- **🔌 OpenAI 兼容**: 提供与 OpenAI `v1/chat/completions` 完全兼容的接口
- **🌊 流式响应支持**: 完美支持 Server-Sent Events (SSE) 流式输出

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
   - `MS_API_KEY` - ModelScope API Key
   - `MS_BASE_URL` - 模型服务 URL（可选，默认 `https://api-inference.modelscope.cn/v1`）
   - `TOKEN` - 访问 Token（可选，用于保护 API）
4. 部署完成

## ⚙️ 配置详解

### 环境变量

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|------|
| `MS_API_KEY` | ModelScope 平台的 API Key | 无 | ✅ 是 |
| `MS_BASE_URL` | 模型服务基础 URL | `https://api-inference.modelscope.cn/v1` | ❌ 否 |
| `TOKEN` | API 访问 Token | 无 | ❌ 否 |
| `PORT` | 服务监听端口（本地） | `2166` | ❌ 否 |

### 模型配置 (config.json)

```json
[
  {
    "level": 1,
    "name": "deepseek-v3-2",
    "model_id": "deepseek-ai/DeepSeek-V3.2",
    "estimated_limit": 50
  },
  {
    "level": 2,
    "name": "deepseek-v3-1",
    "model_id": "deepseek-ai/DeepSeek-V3.1",
    "estimated_limit": 50
  }
]
```

- **level**: 优先级，数字越小越优先使用
- **name**: 内部标识名称（需唯一）
- **model_id**: ModelScope 上的真实模型 ID
- **estimated_limit**: 每日预估调用次数限制

## 💻 使用指南

### API 端点

| 端点 | 说明 |
|------|------|
| `/` | 根路径，返回 API 信息 |
| `/health` | 健康检查，返回模型状态统计 |
| `/v1/chat/completions` | 聊天接口（OpenAI 兼容） |

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
    ├── main.py              # FastAPI 应用
    ├── settings.py          # 配置加载
    ├── network.py           # 网络请求
    ├── stats.py             # 统计与熔断
    ├── schema.py            # 数据模型
    ├── ui.py                # 终端 UI
    ├── config.json          # 模型配置
    └── router_data/         # 数据存储目录
```

## 🖥️ 监控

- **本地**: 终端 Rich UI 实时显示模型状态、日志
- **Vercel**: 访问 `/health` 端点查看 JSON 状态

## 📄 许可证

MIT License