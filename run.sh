#!/bin/bash
#
# Coinbase Advanced Trading Terminal Launcher
#
# This script loads your API key from .env and runs the application.
# You'll be prompted to enter your API secret securely.
#

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Error: .env file not found!"
    echo "Please create a .env file with your COINBASE_API_KEY"
    echo "You can copy .env.example as a starting point:"
    echo "  cp .env.example .env"
    exit 1
fi

# Load environment variables from .env
echo "Loading API credentials from .env..."
set -a
source .env
set +a

# Check if API key is set
if [ -z "$COINBASE_API_KEY" ] || [ "$COINBASE_API_KEY" = "your-api-key-here" ]; then
    echo "Error: COINBASE_API_KEY not set in .env file"
    echo "Please edit .env and add your API key"
    exit 1
fi

# Run the application
echo "Starting Coinbase Advanced Trading Terminal..."
echo ""
python app.py
