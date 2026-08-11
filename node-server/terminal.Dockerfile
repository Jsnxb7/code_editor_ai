FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       bash ca-certificates curl git nodejs npm python3 python3-pip python3-venv python-is-python3 ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 bob \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash bob

USER bob
WORKDIR /workspace
