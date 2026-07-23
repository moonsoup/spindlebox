# slamface_spindlebox — deterministic hardening harness. NO AI, NO credentials.
FROM python:3.11-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates build-essential jq \
    && rm -rf /var/lib/apt/lists/*

# Rust toolchain: `cargo check` on generated skeleton crates
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

# Go + Node/tsc: corpus-tier toolchains (indexing itself never needs them,
# but later tiers compile-smoke generated/target code)
RUN curl -sSL https://go.dev/dl/go1.24.5.linux-amd64.tar.gz | tar -C /usr/local -xz
ENV PATH="/usr/local/go/bin:${PATH}"
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g typescript && rm -rf /var/lib/apt/lists/*

# JDK (headless): `javac` on generated Java skeletons (javac_check stage)
RUN apt-get update && apt-get install -y --no-install-recommends \
      default-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY spindlebox/ spindlebox/
RUN pip install --no-cache-dir -e .
COPY tests/ tests/
COPY slamface/__init__.py slamface/__init__.py
COPY slamface/harness/ slamface/harness/

VOLUME /state
ENV SLAMFACE_STATE=/state SLAMFACE_APP_ROOT=/app
CMD ["python", "-m", "slamface.harness.runner"]
