#!/bin/bash
# ./mcp-autotask-search/run.sh
#
# Wrapper script for running Autotask Search MCP Server
# Creates/activates venv and runs the server

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# AIDEV-NOTE: venv-setup; creates venv if missing, installs deps, runs server

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment [MCPS-VENV]"
        exit 1
    fi
fi

# Activate venv
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Error: Failed to activate virtual environment [MCPS-VACT]"
    exit 1
fi

# Install/upgrade dependencies (only if requirements changed)
if [ ! -f ".deps_installed" ] || [ "pyproject.toml" -nt ".deps_installed" ]; then
    echo "Installing dependencies..."
    pip install -e . > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "Error: Failed to install dependencies [MCPS-DEPS]"
        exit 1
    fi
    touch .deps_installed
fi

# Run the MCP server
python -m autotask_search_mcp.server
