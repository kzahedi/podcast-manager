#!/usr/bin/env python3
"""Create empty placeholder files for each episode in feed.xml."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
    feed_xml = data_dir / "feed.xml"
    episodes_dir = data_dir / "episodes"

    if not feed_xml.exists():
        print(f"ERROR: {feed_xml} not found. Run setup-local-data.sh first.", file=sys.stderr)
        sys.exit(1)

    episodes_dir.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(feed_xml)
    count = 0

    for item in tree.findall(".//item"):
        enc = item.find("enclosure")
        if enc is not None:
            filename = enc.get("url", "").split("/")[-1]
            if filename:
                (episodes_dir / filename).touch()
                print(f"  {filename}")
                count += 1

    print(f"Created {count} placeholder files in {episodes_dir}")


if __name__ == "__main__":
    main()
