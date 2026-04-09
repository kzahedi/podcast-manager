#!/usr/bin/env bash
# Populate data/ from a local podcast feed for local Docker testing.
# Audio files are NOT copied — empty placeholder files are created instead.
#
# Usage:
#   ./setup-local-data.sh                        # uses FEED_XML env var or prompts
#   FEED_XML=/path/to/feed.xml ./setup-local-data.sh
#   ./setup-local-data.sh /path/to/feed.xml
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"

# Resolve feed.xml source: CLI arg → env var → prompt
if [[ $# -ge 1 ]]; then
    SRC_FEED="$1"
elif [[ -n "${FEED_XML:-}" ]]; then
    SRC_FEED="$FEED_XML"
else
    echo "Where is your feed.xml?"
    echo "  Set FEED_XML=/path/to/feed.xml or pass it as an argument."
    echo ""
    echo "  Example: $0 /path/to/feed.xml"
    exit 1
fi

if [[ ! -f "$SRC_FEED" ]]; then
    echo "ERROR: feed.xml not found at: $SRC_FEED"
    exit 1
fi

echo "=== Copying feed.xml ==="
mkdir -p "$DATA_DIR/episodes"
cp "$SRC_FEED" "$DATA_DIR/feed.xml"
EPISODE_COUNT=$(python3 -c "import xml.etree.ElementTree as ET; print(len(ET.parse('$DATA_DIR/feed.xml').findall('.//item')))")
echo "Copied feed.xml ($EPISODE_COUNT episodes)"

echo ""
echo "=== Creating placeholder episode files ==="
python3 "$SCRIPT_DIR/create-placeholders.py" "$DATA_DIR"

echo ""
echo "=== Setup complete ==="
echo "Next: docker compose up --build"
echo "Open: http://localhost:8841"
