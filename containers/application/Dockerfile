# Every base reference must be a repository@sha256 digest from the explicit preparation step.
ARG PYTHON_IMAGE
ARG DOCKER_CLI_IMAGE
FROM ${DOCKER_CLI_IMAGE} AS docker-cli
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HOME=/tmp XDG_CACHE_HOME=/tmp/cache HF_HOME=/tmp/huggingface \
    TORCH_HOME=/tmp/torch HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    MPLCONFIGDIR=/tmp/matplotlib MPLBACKEND=Agg WEB_CONCURRENCY=1 UVICORN_WORKERS=1 \
    PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
WORKDIR /app
COPY containers/application/requirements-runtime.lock /tmp/requirements-runtime.lock
RUN python -m pip install --no-deps --extra-index-url https://download.pytorch.org/whl/cpu -r /tmp/requirements-runtime.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-deps --no-build-isolation . \
    && python -m pip check \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin astroagent \
    && mkdir -p /var/lib/astroagent-executor \
    && chown 10001:10001 /var/lib/astroagent-executor
USER 10001:10001

FROM runtime AS backend
# This stage has no Docker CLI, socket, client certificates or executor ledger.
ENTRYPOINT ["python", "-m", "astroagent.container_entrypoint"]
CMD ["serve"]

FROM runtime AS executor
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
ENTRYPOINT ["python", "-m", "astroagent.plot_executor_server"]
