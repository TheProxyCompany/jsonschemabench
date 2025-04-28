#!/bin/bash
set -e # Exit immediately if a command exits with a non-zero status.

echo "--- Ensuring Docker is installed and user is in docker group ---"
# Check if Docker is already installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    # (Keep Docker installation steps as before)
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    echo "Adding user $USER to docker group..."
    sudo usermod -aG docker $USER
    echo "Docker installation complete. You MUST log out and log back in for group changes to take effect before running this script again."
    exit 1 # Force exit so user logs out/in
else
    echo "Docker is installed."
fi

# Check group membership again (important after potential installation)
if ! groups $USER | grep &>/dev/null '\bdocker\b'; then
    echo "User $USER is not in the docker group. Please log out and log back in, then re-run this script."
    exit 1
fi
echo "--- Docker user group check complete ---"

# Check SSH Agent availability
echo "--- Checking SSH Agent status ---"
if [ -z "$SSH_AUTH_SOCK" ]; then
    eval $(ssh-agent -s)
    echo "SSH agent started. Please ensure your GitHub SSH key is loaded (e.g., using 'ssh-add ~/.ssh/your_key')."
else
    echo "SSH Agent active at $SSH_AUTH_SOCK. Ensure the correct key for GitHub is loaded."
fi
echo "--- SSH Agent check complete ---"

# --- Build the Docker image ---
echo "--- Building Docker image (maskbench-env:private-latest) ---"
# Ensure BuildKit is used and forward SSH agent
DOCKER_BUILDKIT=1 \
docker build \
    --build-arg INSTALL_DEV_BRANCH=true `# Pass arg to Dockerfile` \
    --ssh default `# Use the SSH agent socket defined by SSH_AUTH_SOCK` \
    -t maskbench-env:private-latest \
    -f docker/Dockerfile . `# Specify Dockerfile location relative to repo root`
echo "--- Docker image build complete ---"


# --- Run the Docker container (example) ---
echo "--- Running container interactively ---"
# Adjust the host data path on the VM
HOST_DATA_PATH="/home/azureuser/jsonschemabench/data" # Example path on VM
CONTAINER_DATA_PATH="/app/src/maskbench/data"
# Create results directory on VM if it doesn't exist
mkdir -p "$(pwd)/results_docker"
HOST_RESULTS_PATH="$(pwd)/results_docker" # Save results to host VM
CONTAINER_TMP_PATH="/app/tmp"

# Ensure the data path exists on the VM before mounting
if [ ! -d "$HOST_DATA_PATH" ]; then
    echo "!!! ERROR: Host data path '$HOST_DATA_PATH' not found on VM. Cannot mount volume. !!!"
    echo "Please ensure the benchmark data is present at this location: $HOST_DATA_PATH"
    exit 1
fi

docker run -it --rm \
   -v "$HOST_DATA_PATH:$CONTAINER_DATA_PATH" \
   -v "$HOST_RESULTS_PATH:$CONTAINER_TMP_PATH" \
   maskbench-env:private-latest

echo "--- Container exited ---"
