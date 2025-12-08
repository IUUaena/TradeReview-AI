# -------------------------------------------------------
# 升级基础镜像为 Python 3.12 (以支持最新的 pandas-ta)
# -------------------------------------------------------
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 1. 安装系统级编译依赖
# Python 3.12 的某些库可能需要更现代的编译工具
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 2. 升级 pip 并安装依赖
# 3.12 环境下 pip 通常已经很新，但升级一下保险
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 复制当前目录下所有代码到容器里
COPY . .

# 告诉 Docker 我们的网页跑在 8501 端口
EXPOSE 8501

# 启动命令
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]

