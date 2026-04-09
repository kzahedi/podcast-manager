#!/usr/bin/env bash
# Populate data/ from Obsidian vault for local Docker testing.
# Audio files are NOT copied — empty placeholders are created instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_PODCASTS="$HOME/Obsidian/feed/podcasts"
DATA_DIR="$SCRIPT_DIR/data"

echo "=== Generating feed.xml from Obsidian vault ==="
python3 "$VAULT_PODCASTS/generate-feed.py"
cp "$VAULT_PODCASTS/feed.xml" "$DATA_DIR/feed.xml"
EPISODE_COUNT=$(python3 -c "import xml.etree.ElementTree as ET; print(len(ET.parse('$DATA_DIR/feed.xml').findall('.//item')))")
echo "Copied feed.xml ($EPISODE_COUNT episodes)"

echo ""
echo "=== Creating placeholder episode files ==="
python3 "$SCRIPT_DIR/create-placeholders.py" "$DATA_DIR"

echo ""
echo "=== Setup complete ==="
echo "Next: docker compose up --build"
echo "Open: http://localhost:8841"
