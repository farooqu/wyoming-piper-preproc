FROM python:3.13-alpine

WORKDIR /app

# Only one runtime dep
RUN pip install --no-cache-dir wyoming==1.9.0

COPY wyoming_piper_preproc/ /app/wyoming_piper_preproc/

# Data dir is the mount point for pronunciation CSVs. Container also
# ships a default piper overlay in case nothing is mounted.
RUN mkdir -p /data
COPY data/pronunciations-piper.csv /data/pronunciations-piper.csv

ENV LISTEN_HOST=0.0.0.0 \
    LISTEN_PORT=10210 \
    UPSTREAM_HOST=127.0.0.1 \
    UPSTREAM_PORT=10200 \
    PRONUNCIATIONS=/data/pronunciations.csv:/data/pronunciations-piper.csv \
    LOG_LEVEL=INFO

EXPOSE 10210

ENTRYPOINT ["python", "-m", "wyoming_piper_preproc"]
