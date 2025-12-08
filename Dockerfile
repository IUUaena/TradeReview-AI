# 使用官方轻量级 Python 镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制当前目录下所有代码到容器里
COPY . .

# 告诉 Docker 我们的网页跑在 8501 端口
EXPOSE 8501

# 启动命令
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]

