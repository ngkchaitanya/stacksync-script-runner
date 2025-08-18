# syntax=docker/dockerfile:1

########################################
# Stage 1: build nsjail from source
########################################
FROM debian:bookworm-slim AS nsjail-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    git make g++ pkg-config autoconf bison flex \
    libprotobuf-dev protobuf-compiler \
    libnl-route-3-dev libcap-dev libseccomp-dev ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN git clone --depth=1 https://github.com/google/nsjail.git /src/nsjail
WORKDIR /src/nsjail
RUN make -j"$(nproc)"

########################################
# Stage 2: runtime image
########################################
FROM python:3.11-slim AS runtime

# runtime libs needed by the nsjail binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    libprotobuf32 libnl-route-3-200 libcap2 libseccomp2 procps ca-certificates \
    dos2unix \
 && rm -rf /var/lib/apt/lists/*

# bring in the built nsjail
COPY --from=nsjail-build /src/nsjail/nsjail /usr/local/bin/nsjail

WORKDIR /app

# app files and requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy source and configs
COPY app ./app
COPY nsjail.cfg ./nsjail.cfg
COPY nsjail-light.cfg ./nsjail-light.cfg

# normalize config files for parser safety
RUN dos2unix /app/nsjail*.cfg && \
    awk 'NR==1{sub(/^\xef\xbb\xbf/,"")}1' /app/nsjail-light.cfg > /app/.tmp && mv /app/.tmp /app/nsjail-light.cfg && \
    awk 'NR==1{sub(/^\xef\xbb\xbf/,"")}1' /app/nsjail.cfg > /app/.tmp && mv /app/.tmp /app/nsjail.cfg

# default envs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    USE_NSJAIL=1 \
    NSJAIL_CFG=/app/nsjail-light.cfg

EXPOSE 8080

CMD ["sh","-c","gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT:-8080} app.main:app"]
