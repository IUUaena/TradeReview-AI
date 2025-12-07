# Docker 部署脚本 (Windows PowerShell)
# 用于启动 TradeReview AI 应用

Write-Host "=== TradeReview AI Docker Deployment ===" -ForegroundColor Cyan

# 获取当前脚本所在目录
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$dbPath = Join-Path $scriptPath "trade_review.db"
$uploadsPath = Join-Path $scriptPath "uploads"

# 停止并删除旧容器（如果存在）
Write-Host "`n[1/4] 清理旧容器..." -ForegroundColor Yellow
docker stop trade-review-ai 2>$null
docker rm trade-review-ai 2>$null

# 构建镜像
Write-Host "[2/4] 构建 Docker 镜像..." -ForegroundColor Yellow
docker build -t trade-review-ai:latest .

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 镜像构建失败！" -ForegroundColor Red
    exit 1
}

# 运行容器（挂载数据库和上传文件目录）
Write-Host "[3/4] 启动容器..." -ForegroundColor Yellow
docker run -d `
    -p 8501:8501 `
    --name trade-review-ai `
    -v "${dbPath}:/app/trade_review.db" `
    -v "${uploadsPath}:/app/uploads" `
    trade-review-ai:latest

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✅ 容器启动成功！" -ForegroundColor Green
    Write-Host "`n访问地址:" -ForegroundColor Cyan
    Write-Host "  http://localhost:8501" -ForegroundColor White
    Write-Host "`n查看日志:" -ForegroundColor Cyan
    Write-Host "  docker logs -f trade-review-ai" -ForegroundColor White
    Write-Host "`n停止容器:" -ForegroundColor Cyan
    Write-Host "  docker stop trade-review-ai" -ForegroundColor White
} else {
    Write-Host "❌ 容器启动失败！" -ForegroundColor Red
    exit 1
}

