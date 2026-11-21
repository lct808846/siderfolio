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
    && mkdir -p /var/lib/astroagent-executor /var/lib/astroagent-compute \
    && touch /var/lib/astroagent-compute/.volume \
    && chown -R 10001:10001 /var/lib/astroagent-executor /var/lib/astroagent-compute
USER 10001:10001

FROM runtime AS backend
# This stage has no Docker CLI, socket, client certificates or executor ledger.
ENTRYPOINT ["python", "-m", "astroagent.container_entrypoint"]
CMD ["serve"]

FROM runtime AS executor
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
ENTRYPOINT ["python", "-m", "astroagent.plot_executor_server"]

FROM ${PYTHON_IMAGE} AS petar-build
RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ make \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
# PeTar v1.0, SDAR v1.0, FDPS v7.1c. Build the serial, portable CPU executable.
ADD --checksum=sha256:5a5b7d2cfb30cc877b1fc301b5e662a7e310cca0c27e3f2942c86d6850905e3f https://codeload.github.com/lwang-astro/PeTar/tar.gz/fcca98d425cbb8bc9ce409532e31aa72dfd39e28 PeTar.tar.gz
ADD --checksum=sha256:226a2d3d99d9d69841d60e62037386ec2b14b299aa138a2d82d89fd44101f243 https://codeload.github.com/lwang-astro/SDAR/tar.gz/3a66fc20763a463055bea5c1f036162d2e46d735 SDAR.tar.gz
ADD --checksum=sha256:5447a5827f11694aac8c6ef9ee3ace82715f0d20eb376099a4a067650ef51515 https://codeload.github.com/FDPS/FDPS/tar.gz/b3530c636f7b98f2208dc3813349cdd781d93f92 FDPS.tar.gz
RUN mkdir PeTar SDAR FDPS \
    && for source in PeTar SDAR FDPS; do \
        tar -xzf "${source}.tar.gz" -C "$source" --strip-components=1 \
        && install -Dm644 "$source/LICENSE" "/opt/petar/licenses/$source" || exit 1; \
    done
WORKDIR /build/PeTar
RUN CXXFLAGS="-static-libstdc++ -static-libgcc" \
    ./configure --with-arch=generic --with-mpi=no --disable-openmp \
    && make build/petar \
    && install -D -s -m 0755 build/petar /opt/petar/bin/petar \
    && /opt/petar/bin/petar -h >/dev/null

FROM runtime AS compute-worker
USER root
COPY --from=petar-build /opt/petar /opt/petar
COPY containers/application/requirements-compute.lock /tmp/requirements-compute.lock
RUN python -m pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements-compute.lock
USER 10001:10001
ENTRYPOINT ["python", "-m", "astroagent.compute_worker"]
