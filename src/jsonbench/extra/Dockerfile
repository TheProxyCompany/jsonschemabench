# Stage 1: Builder stage
ARG BASE_IMAGE="nvidia/cuda:12.2.2-devel-ubuntu22.04"
FROM ${BASE_IMAGE} as builder

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    gcc \
    git \
    git-lfs \
    wget

# Stage for conda environment setup
FROM builder as conda-setup

# Install Miniforge
RUN wget -O /tmp/Miniforge3.sh "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh" && \
    bash /tmp/Miniforge3.sh -b -p "/opt/conda" && rm /tmp/Miniforge3.sh
RUN . /opt/conda/etc/profile.d/conda.sh
# Make conda install writable
RUN chmod -R 777 /opt/conda

# Copy environment files
COPY requirements.txt /tmp/requirements.txt
COPY extra/environment.yaml /tmp/environment.yml

# Create conda environment and install requirements
RUN /opt/conda/bin/mamba env create -f /tmp/environment.yml -n default && \
    /opt/conda/bin/mamba clean -y --all && \
    rm /tmp/environment.yml

# Install Python requirements
RUN . /opt/conda/etc/profile.d/conda.sh && \
    conda activate default && \
    mamba clean -y --all && \
    pip install -r /tmp/requirements.txt --no-cache-dir && \
    pip install openai google-generativeai && \
    CMAKE_ARGS="-DGGML_CUDA=on" pip install git+https://github.com/abetlen/llama-cpp-python.git && \
    pip install git+https://github.com/guidance-ai/guidance.git@514a5eb16b9d29ad824d9357732ba66e5e767642 && \
    pip install git+https://github.com/dottxt-ai/outlines.git git+https://github.com/mlc-ai/xgrammar.git && \
    rm /tmp/requirements.txt && \
    chmod -R 777 /opt/conda/envs/default

# Final stage
FROM ${BASE_IMAGE}

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    git \
    gosu \
    git-lfs \
    htop \
    libgl1 \
    libglib2.0-0 \
    ncdu \
    tree \
    openssh-client \
    openssh-server \
    psmisc \
    rsync \
    screen \
    sudo \
    tmux \
    unzip \
    vim \
    ldap-utils \
    nvtop \
    wget && \
    wget -q https://github.com/justjanne/powerline-go/releases/download/v1.24/powerline-go-linux-"$(dpkg --print-architecture)" -O /usr/local/bin/powerline-shell && \
    chmod a+x /usr/local/bin/powerline-shell && \
    rm -rf /var/lib/apt/lists/*

# Copy conda environment from conda-setup stage
COPY --from=conda-setup /opt/conda /opt/conda

# Setup SSH
RUN ssh-keygen -A
EXPOSE 22

# Copy configuration files
COPY extra/.bashrc /tmp/.bashrc

# Install ngrok
RUN curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
    | tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
    && echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
    | tee /etc/apt/sources.list.d/ngrok.list \
    && apt-get update \
    && apt-get install -y ngrok \
    && rm -rf /var/lib/apt/lists/*

COPY extra/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
