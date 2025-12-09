# 使用官方轻量级 Python 镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 1. 安装系统级编译依赖 (wget 用于下载，build-essential 用于编译 C 代码)
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    git \
    wget \
    tar \
    && rm -rf /var/lib/apt/lists/*

# 2. 【核心修复】下载并编译安装 TA-Lib C 库
# 这是 pandas_ta 形态识别功能的必须地基
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# 3. 升级 pip 并安装 Python 依赖
# 这一步会安装 requirements.txt 里的 ta-lib 库，它会去调用上面刚安装好的 C 库
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 4. 复制当前目录下所有代码到容器里
COPY . .

# 告诉 Docker 我们的网页跑在 8501 端口
EXPOSE 8501

# 启动命令
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]
