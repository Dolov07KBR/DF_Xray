# DF_Xray Panel — образ без внешних зависимостей (только stdlib Python).
FROM python:3.12-alpine

LABEL org.opencontainers.image.title="DF_Xray Panel" \
      org.opencontainers.image.description="Лёгкая панель управления Xray: пользователи, подписки, QR, лимиты, ноды" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.version="1.0.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DFX_DATA_DIR=/data \
    DFX_HOST=0.0.0.0 \
    DFX_PORT=8000

WORKDIR /app

RUN addgroup -S dfxray && adduser -S -G dfxray -h /app dfxray \
 && mkdir -p /data && chown -R dfxray:dfxray /data

COPY app ./app
COPY static ./static
COPY README.md LICENSE ./

RUN chown -R dfxray:dfxray /app
USER dfxray

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('DFX_PORT','8000'), timeout=4)"

CMD ["python", "-m", "app", "serve"]
