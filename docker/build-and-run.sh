#!/bin/bash
set -e

echo "--- Checking if tmp directory exists ---"
if [ ! -d "tmp" ]; then
    echo "--- Creating temporary directory ---"
    mkdir -p "tmp"
    echo "--- Temporary directory created ---"
fi

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

# Check if we're on macOS (which doesn't use the docker group mechanism)
if [[ "$(uname)" == "Darwin" ]]; then
    echo "Running on macOS - docker group check not applicable"
else
    # Check group membership again (important after potential installation)
    if ! id -nG $USER | grep -qw "docker"; then
        echo "User $USER is not in the docker group. Adding user to docker group..."
        if command -v usermod &> /dev/null; then
            sudo usermod -aG docker $USER
            echo "User added to docker group. You MUST log out and log back in for group changes to take effect before running this script again."
            exit 1
        else
            echo "Warning: usermod command not found. Cannot add user to docker group automatically."
            echo "You may need to run docker commands with sudo."
        fi
    fi
fi
echo "--- Docker user group check complete ---"

# Check SSH Agent availability
echo "--- Checking SSH Agent status ---"
SSH_ENABLED=false

if [ -z "$SSH_AUTH_SOCK" ]; then
    eval $(ssh-agent -s)
    echo "SSH agent started. Please ensure your GitHub SSH key is loaded (e.g., using 'ssh-add ~/.ssh/your_key')."
    SSH_ENABLED=true
else
    echo "SSH Agent active at $SSH_AUTH_SOCK. Ensure the correct key for GitHub is loaded."
    SSH_ENABLED=true
fi
echo "--- SSH Agent check complete ---"

# --- Build the Docker image ---
echo "--- Building Docker image (maskbench-env:private-latest) ---"
DOCKER_BUILDKIT=1 \
docker build \
    --build-arg INSTALL_DEV_BRANCH=$SSH_ENABLED \
    --ssh default \
    -t maskbench-env:private-latest \
    -f docker/Dockerfile .
echo "--- Docker image build complete ---"


# Display usage
function show_help() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  -t, --threads NUM     Number of threads (default: 16)"
    echo "  -c, --chunk NUM       Chunk size (default: 100)"
    echo "  -d, --dataset PATH    Dataset path relative to data/ (default: Maskbench/)"
    echo "  -e, --engine NAME     Engine to use (default: pse, options: pse, xgr, llg, outlines)"
    echo "  -h, --help            Show this help message"
    echo ""
    echo "Example: $0 -t 8 -c 10 -d Github_easy/ -e pse"
}

# Parse command-line arguments
THREADS=40
CHUNK_SIZE=100  # Use larger chunk size for more efficiency
DATASET="Maskbench/" # Default to whole benchmark directory
ENGINE="pse"

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        -t|--threads)
            THREADS="$2"
            shift 2
            ;;
        -c|--chunk)
            CHUNK_SIZE="$2"
            shift 2
            ;;
        -d|--dataset)
            DATASET="$2"
            shift 2
            ;;
        -e|--engine)
            ENGINE="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Add data/ prefix if not already there
if [[ ! "$DATASET" == data/* ]]; then
    DATASET="data/$DATASET"
fi

# --- Run the Docker container ---
echo "--- Running container interactively ---"
echo $PWD
HOST_DATA_PATH="$PWD/data"
CONTAINER_DATA_PATH="/app/data"

# Ensure the data path exists on the VM before mounting
if [ ! -d "$HOST_DATA_PATH" ]; then
    echo "!!! ERROR: Host data path '$HOST_DATA_PATH' not found on VM. Cannot mount volume. !!!"
    echo "Please ensure the benchmark data is present at this location: $HOST_DATA_PATH"
    exit 1
fi

# Just print a single startup message
echo -n "Starting benchmark with: $ENGINE engine, $THREADS threads, chunk size $CHUNK_SIZE, dataset=$DATASET... "

if [[ "$DATASET" == *.json ]]; then
    # If it's a single JSON file, use it directly
    FILES_TO_PROCESS="$DATASET"
else
    # Simply pass the dataset path to the runner which will handle globbing internally
    if [ -d "$DATASET" ]; then
        echo "Passing directory $DATASET to runner for JSON file processing"
        FILES_TO_PROCESS="$DATASET"
    elif [ -f "$DATASET" ]; then
        echo "Processing single file $DATASET"
        FILES_TO_PROCESS="$DATASET"
    else
        # Try as a glob pattern
        echo "Passing pattern $DATASET to runner"
        FILES_TO_PROCESS="$DATASET"
    fi
fi

# Let the runner handle file counting now, as it will do the globbing
if [[ "$DATASET" == *.json ]]; then
    echo "processing 1 JSON file"
elif [ -d "$DATASET" ]; then
    echo "processing JSON files from directory (count determined by runner)"
else
    echo "processing files matching pattern (count determined by runner)"
fi

# Create output directories for comparison results and plots
COMPARISON_DIR="comparison-$(date +%s)"
mkdir -p "tmp/$COMPARISON_DIR"
mkdir -p "tmp/$COMPARISON_DIR/pse-results"
mkdir -p "tmp/$COMPARISON_DIR/llg-results"
mkdir -p "plots"

# Ensure directory permissions are correct for Docker
chmod -R 777 "tmp/$COMPARISON_DIR"
chmod -R 777 plots

echo "--- Running benchmark with PSE engine ---"
docker run -it --rm \
   -v "$HOST_DATA_PATH:$CONTAINER_DATA_PATH" \
   -v "$PWD/tmp:/app/tmp" \
   maskbench-env:private-latest \
   python -m src.maskbench.scripts.run_maskbench \
     --num-threads "$THREADS" \
     --chunk-size "$CHUNK_SIZE" \
     --output "tmp/$COMPARISON_DIR/pse-results" \
     --pse $FILES_TO_PROCESS

echo "--- PSE engine benchmark completed ---"

echo "--- Running benchmark with LLG engine ---"
docker run -it --rm \
   -v "$HOST_DATA_PATH:$CONTAINER_DATA_PATH" \
   -v "$PWD/tmp:/app/tmp" \
   maskbench-env:private-latest \
   python -m src.maskbench.scripts.run_maskbench \
     --num-threads "$THREADS" \
     --chunk-size "$CHUNK_SIZE" \
     --output "tmp/$COMPARISON_DIR/llg-results" \
     --llg $FILES_TO_PROCESS

echo "--- LLG engine benchmark completed ---"

echo "--- Generating comparison charts and results ---"
# Create a persistent results directory
RESULTS_DIR="benchmark_results-$(date +%s)"
mkdir -p "$RESULTS_DIR"
mkdir -p "$RESULTS_DIR/plots"

# Generate comparison results with matplotlib backend that works in Docker
docker run -it --rm \
   -v "$PWD/tmp:/app/tmp" \
   -v "$PWD/$RESULTS_DIR/plots:/app/plots" \
   -e PYTHONDONTWRITEBYTECODE=1 \
   -e MPLBACKEND=Agg \
   maskbench-env:private-latest \
   python -m src.maskbench.scripts.maskbench_results \
     tmp/$COMPARISON_DIR/pse-results \
     tmp/$COMPARISON_DIR/llg-results

# Copy results to the persistent location
cp "tmp/$COMPARISON_DIR/pse-results/stats.txt" "$RESULTS_DIR/pse-stats.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/llg-results/stats.txt" "$RESULTS_DIR/llg-stats.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/pse-results/entries.txt" "$RESULTS_DIR/pse-entries.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/llg-results/entries.txt" "$RESULTS_DIR/llg-entries.json" 2>/dev/null || true

echo "Comparison results and charts are available in the '$RESULTS_DIR' directory"
echo "--- Container exited ---"
