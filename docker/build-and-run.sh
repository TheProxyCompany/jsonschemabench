#!/bin/bash

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
