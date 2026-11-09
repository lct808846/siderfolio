# Pin the resulting local image SHA256 in server configuration before enabling execution.
FROM python:3.12-slim-bookworm
LABEL org.astroagent.plot-protocol="2"
RUN pip install --no-cache-dir numpy==2.2.6 matplotlib==3.10.3
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk fonts-wqy-zenhei && rm -rf /var/lib/apt/lists/*
COPY plot_worker.py /opt/plot_worker.py
COPY matplotlibrc /opt/matplotlibrc
USER 65532:65532
WORKDIR /output
