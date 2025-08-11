# syntax=docker/dockerfile:1

# build nsjail
FROM debian:bookworm-slim AS nsjail-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    git make g++ pkg-config autoconf bison flex \
    libprotobuf-dev protobuf-compiler \
    libnl-route-3-dev libcap-dev libseccomp-dev ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth=1 https://github.com/google/nsjail.git /src/nsjail
WORKDIR /src/nsjail
RUN make -j"$(nproc)"

# app runtime
FROM python:3.11-slim AS runtime
# runtime libs required by the nsjail binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    libprotobuf32 libnl-route-3-200 libcap2 libseccomp2 procps ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=nsjail-build /src/nsjail/nsjail /usr/local/bin/nsjail

WORKDIR /app
COPY app ./app
COPY nsjail.cfg ./nsjail.cfg
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
EXPOSE 8080
CMD ["sh","-c","gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT:-8080} app.main:app"]
