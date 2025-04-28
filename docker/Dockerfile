# Use Python 3.12 slim image as the base
FROM python:3.12-slim-bookworm AS base

# Set non-interactive frontend for package installations
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        build-essential \
        cmake \
        clang \
        llvm \
        libgomp1 \
        libopenblas-dev \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set the working directory
WORKDIR /app

# --- toolchain & build flags -----------------------------------------------
ENV CC=gcc CXX=g++
# ---------------------------------------------------------------------------

# Create and set the path for the virtual environment using uv
RUN uv venv --python 3.12
ENV PATH="/app/.venv/bin:$PATH"

ARG TARGETARCH
ARG TARGETOS
ENV CMAKE_ARGS=""

RUN if [ "$TARGETARCH" = "arm64" ]; then \
        export CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH=armv8-a"; \
    fi && \
    CMAKE_ARGS="$CMAKE_ARGS" uv pip install --no-cache-dir "llama-cpp-python==0.3.8"


# Copy dependency definition file and install project dependencies
COPY pyproject.toml ./

RUN uv pip install --no-cache-dir -U -e .

ARG CACHEBUST=0
RUN uv cache clean

# Install specific pse-core and pse versions using SSH agent forwarding
ARG INSTALL_DEV_BRANCH="false"

RUN --mount=type=ssh \
    if [ "$INSTALL_DEV_BRANCH" = "true" ]; then \
        echo "Installing pse-core and pse from dev branches (requires SSH access)..." && \
        # Configure SSH access within this step
        mkdir -p ~/.ssh && chmod 700 ~/.ssh && \
        ssh-keyscan github.com >> ~/.ssh/known_hosts && \
        git config --global url."ssh://git@github.com/".insteadOf "https://github.com/" && \
        \
        # Try installing pse-core via SSH. If it fails, log the error.
        # If it succeeds, install the public pse branch afterwards.
        if uv pip install --no-cache-dir "git+ssh://git@github.com/TheProxyCompany/pse_core.git@dev#egg=pse-core"; then \
            echo "Successfully installed pse-core from branch dev." && \
            echo "Installing pse from branch dev..." && \
            uv pip install --no-cache-dir "git+https://github.com/TheProxyCompany/proxy-structuring-engine.git@dev#egg=pse" && \
            echo "Successfully installed pse from branch dev."; \
        else \
            echo "Failed to install pse-core from branch dev (SSH access likely missing/failed)."; \
            exit 1; \
        fi; \
    fi

# Copy the rest of the application code
COPY . .

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

# Default command to start an interactive bash shell
CMD ["/bin/bash"]
