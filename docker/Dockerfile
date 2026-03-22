FROM python:3.11-slim

LABEL maintainer="auto_pt authors"
LABEL description="PT Auto Downloader - Automatic torrent manager for PT sites"

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN apt-get update && apt-get install -y procps tzdata && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir -r requirements.txt

# 设置时区
ENV TZ=Asia/Shanghai
ENV AUTO_PT_KEY_FILE=/app/data/auto_pt.key

# 复制源代码
COPY src/ ./src/
COPY static/ ./static/
COPY main.py .
COPY web.py .
COPY docker/start.sh .

# 复制示例配置（容器内默认使用示例配置）
COPY config.yaml.example ./config.yaml.example

# 设置执行权限和目录
RUN chmod +x /app/start.sh && \
    mkdir -p /app/logs /app/data

# 数据持久化卷（config.yaml 不应作为 VOLUME，应作为文件挂载）
VOLUME ["/app/logs", "/app/data"]

EXPOSE 5000

# 禁用 Flask 调试模式
ENV FLASK_DEBUG=false

# 启动命令
CMD ["/app/start.sh"]
