#!/usr/bin/env python3
"""
sync-played.py — delete NAS episodes that are marked as played in Apple Podcasts.

Reads the local Apple Podcasts SQLite database, cross-references it with the
podcast RSS feed, and calls the podcast manager DELETE API for every episode
that has been played or manually marked as played.

Dry-run by default — pass --yes to actually delete.

Configuration — set via environment variables or a local .env.sync file:

    PODCAST_MANAGER_URL   Base URL of the podcast manager    (required)
                          e.g. http://192.168.1.100:8841
    PODCAST_FEED_URL      URL of the RSS feed                (required)
                          e.g. http://192.168.1.100:8840/feed.xml
    APPLE_PODCASTS_DB     Path to Apple Podcasts SQLite DB   (optional)

Usage:
    ./sync-played.py              # dry-run: show what would be deleted
    ./sync-played.py --yes        # delete played episodes from the NAS
"""
import argparse
import json
import os
import sqlite3
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# ── Default Apple Podcasts DB path ──────────────────────────────────────────
_APPLE_PODCASTS_DB_DEFAULT = (
    Path.home()
    / "Library/Group Containers/243LU875E5.groups.com.apple.podcasts"
    / "Documents/MTLibrary.sqlite"
)


# ── Config loading ───────────────────────────────────────────────────────────

def _load_env_file(path: Path) -> None:
    """Load key=value pairs from a file into os.environ (existing vars win)."""
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"ERROR: {name} is not set.")
        print("Set it in .env.sync or as an environment variable.")
        sys.exit(1)
    return val


# ── Feed parsing ─────────────────────────────────────────────────────────────

def fetch_feed_episodes(feed_url: str) -> dict:
    """Fetch and parse RSS feed. Returns {enclosure_url: filename, ...}."""
    try:
        with urllib.request.urlopen(feed_url, timeout=10) as resp:
            data = resp.read()
    except Exception as e:
        print(f"ERROR: Could not fetch feed from {feed_url}: {e}")
        sys.exit(1)

    try:
        tree = ET.fromstring(data)
    except ET.ParseError as e:
        print(f"ERROR: Could not parse feed XML: {e}")
        sys.exit(1)

    episodes = {}  # enclosure_url → filename
    for item in tree.findall(".//item"):
        enc = item.find("enclosure")
        if enc is None:
            continue
        url = enc.get("url", "").strip()
        if url:
            filename = url.split("/")[-1]
            episodes[url] = filename
    return episodes


# ── Apple Podcasts DB ────────────────────────────────────────────────────────

def fetch_played_episodes(db_path: Path) -> list[dict]:
    """Return episodes marked as played in Apple Podcasts.

    Each entry: {"title": str, "enclosure_url": str}
    """
    if not db_path.exists():
        print(f"ERROR: Apple Podcasts database not found at:\n  {db_path}")
        print("Override with APPLE_PODCASTS_DB=/path/to/MTLibrary.sqlite")
        sys.exit(1)

    # Open read-only via URI to avoid locking the file
    uri = db_path.as_uri() + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as e:
        print(f"ERROR: Could not open Apple Podcasts database: {e}")
        sys.exit(1)

    try:
        rows = con.execute(
            """
            SELECT ZTITLE, ZENCLOSUREURL
            FROM   ZMTEPISODE
            WHERE  (ZHASBEENPLAYED = 1 OR ZMARKASPLAYED = 1)
              AND  ZENCLOSUREURL IS NOT NULL
            """
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"ERROR: Could not query Apple Podcasts database: {e}")
        print("The database schema may have changed — check column names in ZMTEPISODE.")
        sys.exit(1)
    finally:
        con.close()

    return [{"title": row[0] or "", "enclosure_url": row[1]} for row in rows]


# ── Matching ─────────────────────────────────────────────────────────────────

def match_played_to_feed(played: list[dict], feed: dict) -> list[dict]:
    """Return feed episodes that appear in the played list.

    Matching strategy:
    1. Exact enclosure URL match (most reliable)
    2. Filename match (handles host/port differences)
    """
    # Build filename → enclosure_url index for fallback matching
    filename_index = {url.split("/")[-1]: url for url in feed}

    matched = []
    seen_filenames = set()

    for ep in played:
        url = ep["enclosure_url"]
        filename = url.split("/")[-1]

        # 1. Exact URL match
        if url in feed:
            if filename not in seen_filenames:
                matched.append({"title": ep["title"], "filename": feed[url]})
                seen_filenames.add(filename)
            continue

        # 2. Filename match (different host/port)
        if filename in filename_index:
            feed_url = filename_index[filename]
            if filename not in seen_filenames:
                matched.append({"title": ep["title"], "filename": feed[feed_url]})
                seen_filenames.add(filename)

    return matched


# ── API calls ────────────────────────────────────────────────────────────────

def delete_episode(manager_url: str, filename: str) -> bool:
    url = f"{manager_url.rstrip('/')}/episode/{filename}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} deleting {filename}")
        return False
    except Exception as e:
        print(f"  Error deleting {filename}: {e}")
        return False


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Delete NAS episodes that are marked as played in Apple Podcasts."
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Actually delete episodes (default is dry-run)"
    )
    args = parser.parse_args()

    # Load config
    script_dir = Path(__file__).parent
    _load_env_file(script_dir / ".env.sync")

    manager_url = _require_env("PODCAST_MANAGER_URL")
    feed_url = _require_env("PODCAST_FEED_URL")
    db_path = Path(os.environ.get("APPLE_PODCASTS_DB", "") or _APPLE_PODCASTS_DB_DEFAULT)

    print(f"Feed:    {feed_url}")
    print(f"Manager: {manager_url}")
    print(f"DB:      {db_path}")
    print()

    # Fetch data
    print("Fetching feed episodes...")
    feed_episodes = fetch_feed_episodes(feed_url)
    print(f"  {len(feed_episodes)} episodes in feed")

    print("Reading Apple Podcasts played history...")
    played = fetch_played_episodes(db_path)
    print(f"  {len(played)} played episodes in Apple Podcasts")

    # Match
    to_delete = match_played_to_feed(played, feed_episodes)
    print()

    if not to_delete:
        print("Nothing to delete — no played episodes found in the current feed.")
        return

    print(f"{'DRY RUN — ' if not args.yes else ''}Episodes to delete ({len(to_delete)}):")
    for ep in to_delete:
        print(f"  {ep['filename']}")
        if ep["title"]:
            print(f"    {ep['title']}")

    if not args.yes:
        print()
        print("Run with --yes to delete these episodes from the NAS.")
        return

    # Delete
    print()
    ok, fail = 0, 0
    for ep in to_delete:
        print(f"  Deleting {ep['filename']}...", end=" ", flush=True)
        if delete_episode(manager_url, ep["filename"]):
            print("ok")
            ok += 1
        else:
            print("FAILED")
            fail += 1

    print()
    print(f"Done: {ok} deleted, {fail} failed.")


if __name__ == "__main__":
    main()
