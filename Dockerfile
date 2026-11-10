# ---- 桌上剧团 · 诸伶无名 · 生产镜像 ----
# 单实例设计：房间状态全在内存里，绝不能开多 worker / 多副本。
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    AI_DEBUG=0

WORKDIR /app

# 运行期依赖先装（利用层缓存）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 只带运行期需要的代码
COPY server ./server
COPY scripts ./scripts
COPY config ./config

# 非 root 运行
RUN useradd --create-home --uid 10001 stage \
    && chown -R stage:stage /app
USER stage

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys;p=os.environ.get('PORT','8000');sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz',timeout=3).status==200 else 1)"

# 平台（Railway / Render / Koyeb / HF Spaces）会注入 $PORT，这里跟着走。
# --proxy-headers：平台在边缘终结 TLS 后转发，不信任头会导致重定向/WS 地址出错。
# --workers 1：内存态，多 worker 会各自持有不同房间 → 玩家互相看不到。
CMD ["sh", "-c", "exec uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75"]
