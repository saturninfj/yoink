#!/usr/bin/env bash
# Phase 0 — IDM recon setup script (Pandai PC Fedora)
# Run via SSH: ssh pandai-pc 'bash -s' < scripts/recon/setup-pandai.sh
set -euo pipefail

echo "=== Installing Wine + mitmproxy + Wireshark on Pandai PC ==="

# Enable RPM Fusion (Wine dependency)
sudo dnf install -y \
  https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
  https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm \
  || echo "RPM Fusion might already be enabled"

# Core tools
sudo dnf install -y wine wine-mono wine-gecko wireshark mitmproxy

# Python deps (mitmproxy addon scripts)
pip install --user mitmproxy2har

echo "=== Wine setup ==="
# Initialize Wine prefix (silent)
WINEPREFIX="$HOME/.wine" WINEARCH=win64 winecfg </dev/null 2>&1 | tail -5

echo "=== Download IDM installer ==="
IDM_DIR="$HOME/idm-recon"
mkdir -p "$IDM_DIR"
cd "$IDM_DIR"

if [ ! -f idman642.exe ]; then
  curl -L -o idman642.exe \
    "https://www.internetdownloadmanager.com/idman642.exe"
fi

ls -la "$IDM_DIR"

echo ""
echo "=== Next steps ==="
echo "1. Install IDM via Wine:"
echo "   WINEPREFIX=\$HOME/.wine wine idman642.exe"
echo "2. Run mitmproxy:"
echo "   mitmproxy --listen-port 8082"
echo "3. Import mitmproxy CA into Wine cert store (see docs/IDM-BEHAVIOR.md)"
echo "4. Configure IDM proxy: 127.0.0.1:8082"
