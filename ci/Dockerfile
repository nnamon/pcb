# CI image for tools/pcb: the exact tool versions pcb is tested against (pcb doctor checks them at run time).
# Built by .github/workflows/pcb-ci-image.yml and published as ghcr.io/<owner>/claude-pcb/pcb-ci:<IMAGE_VERSION>.
# Bump IMAGE_VERSION (and the tag in pcb-test.yml) whenever this file changes.
FROM ubuntu:24.04

ARG IMAGE_VERSION=1
ARG KICAD_VERSION=7.0.11+dfsg-1build4
ARG FREEROUTING_VERSION=1.9.0
ARG FREEROUTING_SHA256=9084a4888937a7f31f857ecc12aa7a37407f51160e4d2892dff9c9bb47ae3102
ARG RUST_VERSION=1.97.0

ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      kicad=${KICAD_VERSION} \
      python3 python3-pip python3-shapely python3-jsonschema python3-referencing \
      openjdk-21-jre-headless xvfb xauth \
      curl ca-certificates git build-essential pkg-config \
 && rm -rf /var/lib/apt/lists/*

# Freerouting, checked against the upstream release's SHA-256
RUN mkdir -p /opt/freerouting \
 && curl -fsSL -o /opt/freerouting/freerouting-${FREEROUTING_VERSION}.jar \
      https://github.com/freerouting/freerouting/releases/download/v${FREEROUTING_VERSION}/freerouting-${FREEROUTING_VERSION}.jar \
 && echo "${FREEROUTING_SHA256}  /opt/freerouting/freerouting-${FREEROUTING_VERSION}.jar" | sha256sum -c -
ENV PCB_FREEROUTING_JAR=/opt/freerouting/freerouting-${FREEROUTING_VERSION}.jar

# Rust, pinned
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain ${RUST_VERSION} \
 && rustc --version

LABEL org.opencontainers.image.description="pcb CI: KiCad ${KICAD_VERSION}, Freerouting ${FREEROUTING_VERSION}, Rust ${RUST_VERSION}" \
      pcb.ci.image-version="${IMAGE_VERSION}"
