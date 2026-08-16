# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY email_parser ./email_parser
COPY web ./web
COPY tests ./tests
RUN uv sync --frozen --extra web --extra dev --python /usr/local/bin/python

FROM python:3.12-slim AS runtime
WORKDIR /app
RUN useradd --create-home --uid 1000 appuser
COPY --from=builder /app/.venv /app/.venv
COPY email_parser ./email_parser
COPY web ./web
COPY tests ./tests
COPY docs ./docs
COPY scripts ./scripts
COPY pyproject.toml README.md ./
ENV PATH="/app/.venv/bin:$PATH"
ENV EMAILPARSE_OUTPUT_DIR=/app/output
ENV PYTHONUNBUFFERED=1
RUN mkdir -p /app/output && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
VOLUME /app/output
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
