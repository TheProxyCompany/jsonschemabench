#!/bin/bash
# entrypoint.sh
set -e # Exit immediately if a command exits with a non-zero status.

# Explicitly add the venv bin directory to the PATH
export PATH="/app/.venv/bin:$PATH"

mkdir -p /app/data

# Execute the command passed to 'docker run' (which defaults to the CMD if none is passed)
exec "$@"
