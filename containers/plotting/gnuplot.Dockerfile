# Gnuplot is an independent executable, not a Python plotting adapter.
FROM python:3.12-slim-bookworm
LABEL org.astroagent.plot-protocol="2"
RUN apt-get update && apt-get install -y --no-install-recommends gnuplot-nox fonts-dejavu-core fonts-noto-cjk fonts-wqy-zenhei && rm -rf /var/lib/apt/lists/*
COPY plot_worker.py /opt/plot_worker.py
USER 65532:65532
WORKDIR /output
