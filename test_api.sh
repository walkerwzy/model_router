#!/bin/bash

# 用法: ./test_api.sh <vercel-url>
# 示例: ./test_api.sh https://your-app.vercel.app

BASE_URL="${1:-https://your-app.vercel.app}"

echo "=== 测试 ModelScope Router API ==="
echo "URL: $BASE_URL"
echo ""

# 1. 测试根路径
echo "1. 测试根路径 /"
curl -s "$BASE_URL/"
echo ""

# 2. 测试健康检查
echo "2. 测试健康检查 /health"
curl -s "$BASE_URL/health"
echo ""

# 3. 测试聊天接口 (非流式)
echo "3. 测试聊天接口 (非流式)"
curl -s "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "modelscope-router",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
echo ""

# 4. 测试聊天接口 (流式)
echo "4. 测试聊天接口 (流式)"
curl -s -N "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "modelscope-router",
    "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
    "stream": true
  }'
echo ""
echo ""

echo "=== 测试完成 ==="