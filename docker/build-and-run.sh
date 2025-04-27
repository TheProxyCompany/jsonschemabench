#!/bin/bash

# Check if Docker is already installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."

    # Add Docker's official GPG key:
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    # Add the repository to Apt sources:
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update

    # Install Docker packages:
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    sudo usermod -aG docker $USER

    docker --version

    echo "Docker installation complete. You may need to log out and back in for group changes to take effect."
else
    echo "Docker is installed."
fi

# Build the Docker image
DOCKER_BUILDKIT=1 \
docker build \
    --build-arg INSTALL_DEV_BRANCH=true \
    --ssh default \
    -t maskbench-env:private-latest \
    -f docker/Dockerfile .

# Run the Docker container
docker run -it --rm \
    -v ~/Documents/jsonschemabench/data:/app/data \
    maskbench-env:private-latest
