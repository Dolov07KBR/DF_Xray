# DF_Xray Node — Xray-core + агент панели в одном контейнере.
FROM alpine:3.20

ARG TARGETARCH=amd64
ARG XRAY_VERSION=25.9.11

LABEL org.opencontainers.image.title="DF_Xray Node" \
      org.opencontainers.image.description="Нода Xray с агентом DF_Xray Panel" \
      org.opencontainers.image.licenses="GPL-3.0-only"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DFX_XRAY_BIN=/usr/local/bin/xray \
    DFX_CONFIG_PATH=/etc/xray/config.json \
    DFX_POLL=30

RUN apk add --no-cache python3 ca-certificates tzdata curl unzip \
 && case "${TARGETARCH}" in \
      amd64) xray_arch="64" ;; \
      arm64) xray_arch="arm64-v8a" ;; \
      386) xray_arch="32" ;; \
      arm) xray_arch="arm32-v7a" ;; \
      *) xray_arch="64" ;; \
    esac \
 && curl -fsSL -o /tmp/xray.zip \
      "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/Xray-linux-${xray_arch}.zip" \
 && unzip -q /tmp/xray.zip -d /usr/local/bin xray geoip.dat geosite.dat \
 && chmod +x /usr/local/bin/xray \
 && mkdir -p /usr/local/share/xray \
 && mv /usr/local/bin/geoip.dat /usr/local/bin/geosite.dat /usr/local/share/xray/ \
 && rm -f /tmp/xray.zip \
 && apk del curl unzip \
 && addgroup -S xray && adduser -S -G xray -H xray \
 && mkdir -p /etc/xray && chown -R xray:xray /etc/xray

WORKDIR /opt/dfxray
COPY agent.py entrypoint.sh /opt/dfxray/
RUN chmod +x /opt/dfxray/entrypoint.sh /opt/dfxray/agent.py

ENV XRAY_LOCATION_ASSET=/usr/local/share/xray

VOLUME ["/etc/xray"]
EXPOSE 443 8443

HEALTHCHECK --interval=45s --timeout=5s --start-period=20s --retries=3 \
  CMD pidof xray > /dev/null || exit 1

ENTRYPOINT ["/opt/dfxray/entrypoint.sh"]
