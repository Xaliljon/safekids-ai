# Guardian AI backend image. Build context is the REPO ROOT (see docker/compose.yaml)
# because the backend depends on the guardian_common workspace package.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /src
COPY pyproject.toml uv.lock* ./
COPY packages/python/guardian_common/ packages/python/guardian_common/
COPY ai/pyproject.toml ai/pyproject.toml
COPY edge/pyproject.toml edge/pyproject.toml
COPY backend/ backend/
# Workspace members must exist for resolution; only backend is installed into the venv.
RUN mkdir -p ai/guardian_ai edge/guardian_edge \
    && touch ai/guardian_ai/__init__.py edge/guardian_edge/__init__.py \
    && uv sync --frozen --no-dev --package guardian-backend

FROM python:3.12-slim-bookworm

# Run as non-root (security by default).
RUN groupadd -r guardian && useradd -r -g guardian guardian
WORKDIR /srv
COPY --from=builder /src/.venv /srv/.venv
COPY --from=builder /src/backend /srv/backend
ENV PATH="/srv/.venv/bin:$PATH"
USER guardian
EXPOSE 8000

# Placeholder until the API layer exists (scaffold phase — no application logic yet).
# Will become: CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
CMD ["python", "-c", "print('guardian-backend image OK; application entrypoint pending')"]
