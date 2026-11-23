# Gnuplot is an independent executable, not a Python plotting adapter.
FROM python@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
LABEL org.astroagent.plot-protocol="2"
RUN apt-get update && apt-get install -y --no-install-recommends gnuplot-nox fonts-dejavu-core fonts-noto-cjk fonts-wqy-zenhei && rm -rf /var/lib/apt/lists/*
COPY plot_worker.py /opt/plot_worker.py
USER 65532:65532
WORKDIR /output
