# Git 推送脚本 - V7.0-K线数据本地储存
# 安全检查：确保没有数据库文件被提交

Write-Host "=== Git 推送脚本 - V7.0 ===" -ForegroundColor Cyan

# 1. 检查状态
Write-Host "`n[1/4] 检查 Git 状态..." -ForegroundColor Yellow
git status

Write-Host "`n⚠️  请仔细检查上面的输出！" -ForegroundColor Red
Write-Host "   确保没有看到任何 .db 文件（如 trade_review.db, market_data.db）" -ForegroundColor Yellow
Write-Host "   如果看到 .db 文件，请按 Ctrl+C 停止，然后检查 .gitignore" -ForegroundColor Yellow

$confirm = Read-Host "`n确认没有 .db 文件后，按 Enter 继续，或按 Ctrl+C 取消"

# 2. 添加所有修改
Write-Host "`n[2/4] 添加所有修改..." -ForegroundColor Yellow
git add .

# 3. 提交更改
Write-Host "[3/4] 提交更改..." -ForegroundColor Yellow
git commit -m "feat: V7.0-K线数据本地储存

- 新增 MarketDataEngine：本地 K 线数据仓库
- 升级到 Python 3.12，支持最新版 pandas_ta
- 添加侧边栏 K 线同步功能（一键同步）
- 修复币种名称匹配问题（清洗逻辑）
- 启用 Docker 热重载模式（开发效率提升）
- 优化价格行为分析（支持 ATR 和 MAD 计算）"

# 4. 推送到远程
Write-Host "[4/4] 推送到 GitHub..." -ForegroundColor Yellow
git push

Write-Host "`n✅ 推送完成！" -ForegroundColor Green

