#!/bin/bash

# 用法: ./test_api.sh <vercel-url> [token]
# 示例: ./test_api.sh https://your-app.vercel.app your-token

BASE_URL="${1:-https://your-app.vercel.app}"
TOKEN="${2:-}"

echo "=== 测试 ModelScope Router API ==="
echo "URL: $BASE_URL"
echo "TOKEN: ${TOKEN:-<未设置>}"
echo ""

# 设置 Auth Header
AUTH_HEADER=""
if [ -n "$TOKEN" ]; then
    AUTH_HEADER="-H \"Authorization: Bearer $TOKEN\""
fi

# 1. 测试根路径
echo "1. 测试根路径 /"
curl -s "$BASE_URL/"
echo ""

# 2. 测试健康检查
echo "2. 测试健康检查 /health"
curl -s "$BASE_URL/health"
echo ""

# 3. 测试无 Token 访问 (应返回 401)
echo "3. 测试无 Token 访问 (应返回 401)"
curl -s -w "\nHTTP Status: %{http_code}\n" "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "modelscope-router",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
echo ""

# 4. 测试有 Token (非流式)
if [ -n "$TOKEN" ]; then
    echo "4. 测试有 Token (非流式)"
    curl -s "$BASE_URL/v1/chat/completions" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "model": "modelscope-router",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": false
      }'
    echo ""
    
    # 5. 测试有 Token (流式)
    echo "5. 测试有 Token (流式)"
    curl -s -N "$BASE_URL/v1/chat/completions" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "model": "modelscope-router",
        "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
        "stream": true
      }'
    echo ""
else
    echo "4-5. 请提供 TOKEN 参数测试完整功能"
fi

echo ""
echo "=== 测试完成 ==="