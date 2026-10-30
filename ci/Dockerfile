# CI image for tools/pcb: the exact tool versions pcb is tested against (pcb doctor checks them at run time).
# Built by .github/workflows/pcb-ci-image.yml and published as ghcr.io/<owner>/claude-pcb/pcb-ci:<IMAGE_VERSION>.
# Bump IMAGE_VERSION (and the tag in pcb-test.yml) whenever this file changes.
FROM ubuntu:24.04

ARG IMAGE_VERSION=3
# KiCad 10 from the KiCad project's PPA (Ubuntu 24.04 ships 7.0.11). The PPA keeps only its newest build, so when
# it moves on this pin fails to install: bump it here and KICAD_VERSION in src/doctor.rs together, and re-run the suite.
ARG KICAD_VERSION=10.0.8~ubuntu24.04.1
ARG KICAD_PPA_FINGERPRINT=FDA854F61C4D0D9572BB95E5245D5502FAD7A805
ARG FREEROUTING_VERSION=2.5.0
ARG FREEROUTING_SHA256=f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7
ARG RUST_VERSION=1.97.0

ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8

# the PPA's signing key is kept beside this file and checked against the fingerprint Launchpad publishes
COPY kicad-10-ppa.asc /tmp/kicad-10-ppa.asc
RUN apt-get update \
 && apt-get install -y --no-install-recommends gnupg ca-certificates \
 && test "$(gpg --show-keys --with-colons /tmp/kicad-10-ppa.asc | awk -F: '/^fpr/ {print $10; exit}')" = "${KICAD_PPA_FINGERPRINT}" \
 && mkdir -p /etc/apt/keyrings && gpg --dearmor < /tmp/kicad-10-ppa.asc > /etc/apt/keyrings/kicad-10.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/kicad-10.gpg] https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu noble main" > /etc/apt/sources.list.d/kicad-10.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      kicad=${KICAD_VERSION} \
      python3 python3-pip python3-shapely \
      openjdk-25-jre-headless \
      curl ca-certificates git build-essential pkg-config \
 && rm -rf /var/lib/apt/lists/*

# jsonschema 4.18 or later (noble ships 4.10, which lacks the registry the contract checker uses; review 5, 1)
RUN pip3 install --break-system-packages "jsonschema>=4.18,<5" "referencing>=0.31" \
 && python3 -c "import pcbnew, shapely, jsonschema, referencing; assert pcbnew.Version().startswith('10.'); jsonschema.Draft202012Validator({}, registry=referencing.Registry())"

# Freerouting (headless since 2.x, so no display server), checked against the upstream release's SHA-256
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
