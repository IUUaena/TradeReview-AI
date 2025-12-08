#!/bin/bash
# Docker 部署脚本 (Linux/Mac)
# 用于启动 TradeReview AI 应用

echo "=== TradeReview AI Docker Deployment ==="

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
DB_PATH="${SCRIPT_DIR}/trade_review.db"
UPLOADS_PATH="${SCRIPT_DIR}/uploads"

# 停止并删除旧容器（如果存在）
echo "[1/4] 清理旧容器..."
docker stop trade-review-ai 2>/dev/null
docker rm trade-review-ai 2>/dev/null

# 构建镜像
echo "[2/4] 构建 Docker 镜像..."
docker build -t trade-review-ai:latest .

if [ $? -ne 0 ]; then
    echo "❌ 镜像构建失败！"
    exit 1
fi

# 运行容器（挂载数据库和上传文件目录）
echo "[3/4] 启动容器..."
docker run -d \
    -p 8501:8501 \
    --name trade-review-ai \
    -v "${DB_PATH}:/app/trade_review.db" \
    -v "${UPLOADS_PATH}:/app/uploads" \
    trade-review-ai:latest

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 容器启动成功！"
    echo ""
    echo "访问地址:"
    echo "  http://localhost:8501"
    echo ""
    echo "查看日志:"
    echo "  docker logs -f trade-review-ai"
    echo ""
    echo "停止容器:"
    echo "  docker stop trade-review-ai"
else
    echo "❌ 容器启动失败！"
    exit 1
fi

