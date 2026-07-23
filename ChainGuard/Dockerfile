FROM python:3.13-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH
WORKDIR /app
RUN groupadd --system appgroup && useradd --system --gid appgroup --home-dir /app appuser
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt
COPY --chown=appuser:appgroup alembic.ini ./
COPY --chown=appuser:appgroup alembic ./alembic
COPY --chown=appuser:appgroup src ./src
COPY --chown=appuser:appgroup config ./config
COPY --chown=appuser:appgroup data ./data
# calibration_registry 与 imports 都由应用按需创建子目录，但父目录必须先存在且属
# appuser——docker-compose 把命名卷 workspace 挂在 /app/.workspace 上，Docker 用镜像
# 里该路径的属主初始化空卷，这里的 chown 决定了挂卷后容器内是否可写。
RUN mkdir -p /app/.workspace/imports /app/.workspace/calibration_registry && chown -R appuser:appgroup /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
