#!/bin/bash

# Sentinel Startup Script
# Usage: ./run.sh [--camera] [--headless]

START_CAMERA=false
HEADLESS=false

# 1. Parse Arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -c|--camera) START_CAMERA=true ;;
        --headless) HEADLESS=true ;;
        -h|--help) echo "Usage: ./run.sh [-c|--camera] [--headless]"; exit 0 ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# 2. Cleanup Function
cleanup_ports() {
    echo "🧹 Cleaning up ports..."
    fuser -k 8000/tcp 2>/dev/null
    fuser -k 8080/tcp 2>/dev/null
    fuser -k 8081/tcp 2>/dev/null
    sleep 1
}

cleanup() {
    echo ""
    echo "🛑 Shutting down Sentinel..."
    
    # Kill the Camera Node if it's running
    if [ -n "$CAMERA_PID" ]; then
        kill "$CAMERA_PID" 2>/dev/null
    fi
    cleanup_ports
}
trap cleanup EXIT

# Clean ports at start too
cleanup_ports

# 3. Start Camera Node (Optional)
if [ "$START_CAMERA" = true ]; then
    echo "📷 Starting Camera Node (Edge Sensor)..."
    python3 -m camera_node.main &
    CAMERA_PID=$!
    sleep 0.5
fi

# 4. Start Server Node
echo "🖥️  Starting Sentinel Server Node..."
echo "   - WebRTC Signaling on port 8000"

if [ "$HEADLESS" = true ]; then
    echo "   - Running in HEADLESS mode (No Web UI)"
    python3 -m server_node
else
    echo "   - Web UI on port 8080"
    python3 -m server_node
fi
