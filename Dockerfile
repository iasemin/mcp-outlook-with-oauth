FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.10 /uv /usr/local/bin/uv
WORKDIR /app
COPY LICENSE ./LICENSE
ENV UV_COMPILE_BYTECODE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-cache && useradd --uid 10001 --create-home mcp
USER 10001
EXPOSE 8766
HEALTHCHECK --interval=15s --timeout=3s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8766/healthz', timeout=2)"]
CMD ["/app/.venv/bin/python", "-m", "outlook_mcp"]
