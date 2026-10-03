# FaultForge web demo: FastAPI serving the API and the built React UI.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY faultforge/ faultforge/
RUN uv sync --frozen --no-dev --extra contree
COPY examples/ examples/
COPY --from=web /web/dist web/dist
RUN useradd --create-home faultforge && chown -R faultforge /app
USER faultforge
# demo = recorded model responses, no keys needed. live = Nemotron + Token Factory Sandboxes.
ENV FAULTFORGE_MODE=demo PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync uvicorn faultforge.api:create_app --factory --host 0.0.0.0 --port ${PORT}"]
