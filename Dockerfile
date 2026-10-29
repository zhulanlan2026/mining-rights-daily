FROM python:3.12-slim-bookworm

RUN pip install --no-cache-dir uv==0.7.13 \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin app

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    LOG_FORMAT=json

COPY --chown=app:app pyproject.toml uv.lock README.md ./
COPY --chown=app:app src ./src
RUN chown app:app /app
USER app
ENV UV_HTTP_TIMEOUT=120
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"
EXPOSE 8001 8002 8003
CMD ["mining-news-mcp"]
