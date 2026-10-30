# CI image for tools/pcb: the exact tool versions pcb is tested against (pcb doctor checks them at run time).
# Built by .github/workflows/pcb-ci-image.yml and published as ghcr.io/<owner>/claude-pcb/pcb-ci:<IMAGE_VERSION>.
# Bump IMAGE_VERSION (and the tag in pcb-test.yml) whenever this file changes; the workflow refuses to overwrite a tag.
# Pinned (review 6, K11): the base image by digest; Ubuntu's archive and the KiCad PPA at one snapshot date (Launchpad
# keeps dated snapshots of PPAs too, so old KiCad builds stay installable); pip packages exactly; Rust by toolchain;
# Freerouting by SHA-256. Not pinned: the rustup installer script (the toolchain it installs is).
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852

ARG IMAGE_VERSION=6
ARG APT_SNAPSHOT=20261030T090000Z
# KiCad 10 from the KiCad project's PPA (Ubuntu 24.04 ships 7.0.11), read at APT_SNAPSHOT. To move to a newer KiCad,
# move APT_SNAPSHOT past its release, bump this and KICAD_VERSION in src/doctor.rs together, and re-run the suite.
ARG KICAD_VERSION=10.0.8~ubuntu24.04.1
ARG KICAD_PPA_FINGERPRINT=FDA854F61C4D0D9572BB95E5245D5502FAD7A805
ARG FREEROUTING_VERSION=2.5.0
ARG FREEROUTING_SHA256=f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7
ARG RUST_VERSION=1.97.0

ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8

# the PPA's signing key is kept beside this file and checked against the fingerprint Launchpad publishes
COPY kicad-10-ppa.asc /tmp/kicad-10-ppa.asc
# The snapshot service is HTTPS only and the base image has no CA certificates, so ca-certificates and gnupg come first
# from the live archive over plain HTTP (signed by Ubuntu's archive key), and are reinstalled from the snapshot below.
# Then every apt command reads the archive and the PPA as they were at APT_SNAPSHOT: set in apt's config, not as a flag
# on update alone, because `apt-get update --snapshot` leaves install reading the live archive (review 7, C3).
RUN apt-get update \
 && apt-get install -y --no-install-recommends gnupg ca-certificates \
 && printf 'APT::Snapshot "%s";\n' "${APT_SNAPSHOT}" > /etc/apt/apt.conf.d/50snapshot \
 && rm -rf /var/lib/apt/lists/* \
 && test "$(gpg --show-keys --with-colons /tmp/kicad-10-ppa.asc | awk -F: '/^fpr/ {print $10; exit}')" = "${KICAD_PPA_FINGERPRINT}" \
 && mkdir -p /etc/apt/keyrings && gpg --dearmor < /tmp/kicad-10-ppa.asc > /etc/apt/keyrings/kicad-10.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/kicad-10.gpg] https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu noble main" > /etc/apt/sources.list.d/kicad-10.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends --allow-downgrades \
      gnupg ca-certificates \
      kicad=${KICAD_VERSION} \
      python3 python3-pip python3-shapely \
      openjdk-25-jre-headless \
      curl git build-essential pkg-config \
 && rm -rf /var/lib/apt/lists/*

# jsonschema 4.18 or later (noble ships 4.10, which lacks the registry the contract checker uses; review 5, 1)
RUN pip3 install --break-system-packages --no-deps jsonschema==4.26.0 referencing==0.37.0 jsonschema-specifications==2025.9.1 rpds-py==2026.9.1 attrs==26.1.0 typing_extensions==4.16.0 \
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
