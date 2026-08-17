# ETK 精简版 - Emby 翻译服务（从 hbq0405/emby-toolkit 裁剪）
# 保留: AI 翻译引擎 + 豆瓣演员表 + 全库人物翻译 + Web UI + webhook + 任务队列
# 剔除: 115整理/订阅/分享/前端框架/nginx/ffmpeg/PostgreSQL
FROM python:3.12-slim

# 时区支持（北京时间）
ENV TZ=Asia/Shanghai
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制翻译服务核心
COPY ai_translator.py constants.py config_manager.py utils.py \
     app.py emby_api.py task_queue.py translate_service.py \
     scheduler.py ai_compat.py ./
COPY database/ ./database/
COPY handler/ ./handler/
COPY tasks/ ./tasks/

# 依赖
RUN pip install --no-cache-dir requests openai flask flask-cors apscheduler

# 数据目录（SQLite + 配置 + 日志）
RUN mkdir -p /config
ENV ETK_DB_PATH=/config/etk.db \
    ETK_CONFIG_FILE=/config/config.json \
    ETK_LOG_FILE=/config/etk.log \
    PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python3", "app.py"]
