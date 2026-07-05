# Guardian Edge Box runtime image. Build context is the REPO ROOT.
#
# Multi-target by base image (models stay replaceable, hardware stays modular):
#   Jetson (arm64):  --build-arg BASE_IMAGE=nvcr.io/nvidia/l4t-jetpack:r36.4.0
#   Intel N100:      default (python:3.10-slim-bookworm), ONNX Runtime backend
ARG BASE_IMAGE=python:3.10-slim-bookworm
FROM ${BASE_IMAGE}

RUN groupadd -r guardian && useradd -r -g guardian guardian
WORKDIR /srv

# Scaffold phase: dependency installation and the runtime entrypoint land with
# the first pipeline code. Kept minimal so `docker build` already succeeds in CI.
COPY edge/pyproject.toml /srv/edge/pyproject.toml
COPY edge/guardian_edge /srv/edge/guardian_edge

USER guardian

# Will become the edge runtime supervisor once guardian_edge has an entrypoint.
CMD ["python3", "-c", "print('guardian-edge image OK; runtime entrypoint pending')"]
