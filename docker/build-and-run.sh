#!/bin/bash
set -e

if [ ! -d "tmp" ]; then
    echo "--- Creating temporary directory"
    mkdir -p "tmp"
    echo "--- Temporary directory created"
fi

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
fi

# Check if we're on macOS (which doesn't use the docker group mechanism)
if ! [[ "$(uname)" == "Darwin" ]]; then
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

# Check SSH Agent availability
SSH_ENABLED=false

if [ -z "$SSH_AUTH_SOCK" ]; then
    eval $(ssh-agent -s)
    echo "SSH agent started. Please ensure your GitHub SSH key is loaded (e.g., using 'ssh-add ~/.ssh/your_key')."
    SSH_ENABLED=true
else
    echo "SSH Agent active at $SSH_AUTH_SOCK. Ensure the correct key for GitHub is loaded."
    SSH_ENABLED=true
fi
echo "--- SSH Agent check complete"

# --- Build the Docker image ---
echo "--- Building Docker image"
DOCKER_BUILDKIT=1 \
docker build \
    --build-arg INSTALL_DEV_BRANCH=$SSH_ENABLED \
    --ssh default \
    --build-arg CACHEBUST=$(date +%s) \
    -t maskbench-env:private-latest \
    -f docker/Dockerfile .
echo "--- Docker image build complete"


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

HOST_DATA_PATH="$PWD/data"
CONTAINER_DATA_PATH="/app/data"

# Ensure the data path exists on the VM before mounting
if [ ! -d "$HOST_DATA_PATH" ]; then
    echo "!!! ERROR: Host data path '$HOST_DATA_PATH' not found on VM. Cannot mount volume. !!!"
    echo "Please ensure the benchmark data is present at this location: $HOST_DATA_PATH"
    exit 1
fi

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

echo "--- Running benchmark with XGR engine ---"
docker run -it --rm \
   -v "$HOST_DATA_PATH:$CONTAINER_DATA_PATH" \
   -v "$PWD/tmp:/app/tmp" \
   maskbench-env:private-latest \
   python -m src.maskbench.scripts.run_maskbench \
     --num-threads "$THREADS" \
     --chunk-size "$CHUNK_SIZE" \
     --output "tmp/$COMPARISON_DIR/xgr-results" \
     --xgr $FILES_TO_PROCESS
echo "--- XGR engine benchmark completed ---"

echo "--- Running benchmark with XGR-CPP engine ---"
docker run -it --rm \
   -v "$HOST_DATA_PATH:$CONTAINER_DATA_PATH" \
   -v "$PWD/tmp:/app/tmp" \
   maskbench-env:private-latest \
   python -m src.maskbench.scripts.run_maskbench \
     --num-threads "$THREADS" \
     --chunk-size "$CHUNK_SIZE" \
     --output "tmp/$COMPARISON_DIR/xgr-cpp-results" \
     --xgr-cpp $FILES_TO_PROCESS
echo "--- XGR-CPP engine benchmark completed ---"

echo "--- Running benchmark with XGR-Compliant engine ---"
docker run -it --rm \
   -v "$HOST_DATA_PATH:$CONTAINER_DATA_PATH" \
   -v "$PWD/tmp:/app/tmp" \
   maskbench-env:private-latest \
   python -m src.maskbench.scripts.run_maskbench \
     --num-threads "$THREADS" \
     --chunk-size "$CHUNK_SIZE" \
     --output "tmp/$COMPARISON_DIR/xgr-compliant-results" \
     --xgr-compliant $FILES_TO_PROCESS
echo "--- XGR-Compliant engine benchmark completed ---"

echo "--- Running benchmark with Outlines engine ---"
docker run -it --rm \
   -v "$HOST_DATA_PATH:$CONTAINER_DATA_PATH" \
   -v "$PWD/tmp:/app/tmp" \
   maskbench-env:private-latest \
   python -m src.maskbench.scripts.run_maskbench \
     --num-threads "$THREADS" \
     --chunk-size "$CHUNK_SIZE" \
     --output "tmp/$COMPARISON_DIR/outlines-results" \
     --outlines $FILES_TO_PROCESS
echo "--- Outlines engine benchmark completed ---"

echo "--- Running benchmark with LlamaCPP engine ---"
docker run -it --rm \
   -v "$HOST_DATA_PATH:$CONTAINER_DATA_PATH" \
   -v "$PWD/tmp:/app/tmp" \
   maskbench-env:private-latest \
   python -m src.maskbench.scripts.run_maskbench \
     --num-threads "$THREADS" \
     --chunk-size "$CHUNK_SIZE" \
     --output "tmp/$COMPARISON_DIR/llamacpp-results" \
     --llamacpp $FILES_TO_PROCESS
echo "--- LlamaCPP engine benchmark completed ---"

echo "--- Generating comparison charts and results ---"
# Create a persistent results directory
RESULTS_DIR="benchmark_results-$(date +%s)"
mkdir -p "$RESULTS_DIR"
mkdir -p "$RESULTS_DIR/plots"

# Generate comparison results with matplotlib backend that works in Docker
docker run -it --rm \
   -v "$PWD/tmp:/app/tmp" \
   -v "$PWD/$RESULTS_DIR/plots:/app/plots" \
   -e MPLBACKEND=Agg \
   maskbench-env:private-latest \
   python -m src.maskbench.scripts.maskbench_results \
     tmp/$COMPARISON_DIR/pse-results \
     tmp/$COMPARISON_DIR/llg-results \
     tmp/$COMPARISON_DIR/xgr-results \
     tmp/$COMPARISON_DIR/xgr-cpp-results \
     tmp/$COMPARISON_DIR/xgr-compliant-results \
     tmp/$COMPARISON_DIR/outlines-results \
     tmp/$COMPARISON_DIR/llamacpp-results

# Copy results to the persistent location
cp "tmp/$COMPARISON_DIR/pse-results/stats.txt" "$RESULTS_DIR/pse-stats.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/llg-results/stats.txt" "$RESULTS_DIR/llg-stats.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/pse-results/entries.txt" "$RESULTS_DIR/pse-entries.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/llg-results/entries.txt" "$RESULTS_DIR/llg-entries.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/xgr-results/entries.txt" "$RESULTS_DIR/xgr-entries.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/xgr-cpp-results/entries.txt" "$RESULTS_DIR/xgr-cpp-entries.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/xgr-compliant-results/entries.txt" "$RESULTS_DIR/xgr-compliant-entries.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/outlines-results/entries.txt" "$RESULTS_DIR/outlines-entries.json" 2>/dev/null || true
cp "tmp/$COMPARISON_DIR/llamacpp-results/entries.txt" "$RESULTS_DIR/llamacpp-entries.json" 2>/dev/null || true

echo "Comparison results and charts are available in the '$RESULTS_DIR' directory"

# Determine the current user and hostname for informational purposes
REMOTE_USER=$(whoami)
# Attempt to ascertain the public IP address; default to hostname if unobtainable.
REMOTE_ADDRESS=$(curl -s ifconfig.me)
if [ -z "$REMOTE_ADDRESS" ]; then
    REMOTE_ADDRESS=$(hostname)
fi

# Construct the absolute path to the results directory on this machine
RESULTS_FULL_PATH="$PWD/$RESULTS_DIR"

# Formulate a template secure copy command using the determined address.
SCP_TEMPLATE="scp -r \"${REMOTE_USER}@${REMOTE_ADDRESS}:${RESULTS_FULL_PATH}\" ."

echo ""
echo "----------------------------------------------------------------------"
echo "Benchmark complete."
echo ""
echo "If these results need to be transferred to your local machine,"
echo "execute a command similar to the following from your local terminal."
echo ""
echo "  ${SCP_TEMPLATE}"
echo ""
echo "----------------------------------------------------------------------"
