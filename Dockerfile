# syntax=docker/dockerfile:1.6
# ─────────────────────────────────────────────────────────────
# Homer — production image
# ─────────────────────────────────────────────────────────────

ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim-bookworm AS base

# Переменные окружения
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

# Системные зависимости для драйверов и утилит
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        tini \
        bsd-mailx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ─────────── Зависимости (кэшируемый слой) ───────────
FROM base AS deps
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
 && pip install -r requirements.txt

# ─────────── Runtime ───────────
FROM base AS runtime

# Копируем site-packages из deps-слоя
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Копируем исходники
COPY homer ./homer
COPY lib ./lib
COPY email ./email
COPY commands ./commands
COPY config.example.yml ./config.example.yml
COPY pyproject.toml README.md LICENSE ./

# Маркер типизации
RUN touch lib/py.typed

# Пользователь
RUN useradd -r -u 1001 -s /usr/sbin/nologin homer \
 && mkdir -p /app/logs /app/var \
 && chown -R homer:homer /app \
 && chmod +x /app/homer

USER homer

# tini как init для корректной обработки сигналов
ENTRYPOINT ["/usr/bin/tini", "--"]

# По умолчанию — показать команды
CMD ["./homer"]

# Проверка, что homer исполняется
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/app/homer", "queue:status"] || exit 0
