"""Podcast Manager — episode browser and delete interface."""
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, abort

app = Flask(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
FEED_XML = DATA_DIR / "feed.xml"
EPISODES_DIR = DATA_DIR / "episodes"


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------

def _iso_week(pub_date_str: str) -> tuple:
    """Parse pubDate string and return (iso_week_label, year, week_num).

    Returns ('unknown', 0, 0) on parse failure.
    """
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(pub_date_str.strip(), fmt)
            iso = dt.isocalendar()
            label = f"{iso[0]}-W{iso[1]:02d}"
            return label, iso[0], iso[1]
        except ValueError:
            continue
    return "unknown", 0, 0


def parse_feed() -> dict:
    """Return episodes grouped by ISO week.

    Returns {} if feed.xml is missing or unparseable.
    Schema:
        { "2026-W15": {
            "iso_week": "2026-W15",
            "week_year": 2026,
            "week_num": 15,
            "total_size": 12345678,
            "episodes": [
                {"title": ..., "filename": ..., "pub_date": ...,
                 "file_size": ..., "file_size_mb": ..., "iso_week": ...},
                ...
            ]
        }, ... }
    """
    if not FEED_XML.exists():
        return {}

    try:
        tree = ET.parse(FEED_XML)
    except ET.ParseError:
        return {}

    weeks: dict = {}

    for item in tree.findall(".//item"):
        title = item.findtext("title") or ""
        pub_date_str = item.findtext("pubDate") or ""
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue

        url = enclosure.get("url", "")
        filename = url.split("/")[-1]
        if not filename:
            continue

        # File size: prefer disk (accurate); fall back to RSS length attribute
        file_path = EPISODES_DIR / filename
        if file_path.exists():
            file_size = file_path.stat().st_size
        else:
            file_size = int(enclosure.get("length", 0))

        iso_week, week_year, week_num = _iso_week(pub_date_str)

        episode = {
            "title": title,
            "filename": filename,
            "pub_date": pub_date_str,
            "file_size": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 1),
            "iso_week": iso_week,
        }

        if iso_week not in weeks:
            weeks[iso_week] = {
                "iso_week": iso_week,
                "week_year": week_year,
                "week_num": week_num,
                "total_size": 0,
                "episodes": [],
            }
        weeks[iso_week]["episodes"].append(episode)
        weeks[iso_week]["total_size"] += file_size

    return weeks


# ---------------------------------------------------------------------------
# Feed mutation
# ---------------------------------------------------------------------------

def _update_feed_xml(remove_filenames: set) -> None:
    """Remove <item> entries for the given filenames from feed.xml.

    Writes atomically (temp file → rename). No-op if feed.xml is missing.
    """
    if not FEED_XML.exists() or not remove_filenames:
        return

    try:
        tree = ET.parse(FEED_XML)
    except ET.ParseError:
        return

    channel = tree.find("channel")
    if channel is None:
        return

    for item in list(channel.findall("item")):
        enc = item.find("enclosure")
        if enc is not None:
            filename = enc.get("url", "").split("/")[-1]
            if filename in remove_filenames:
                channel.remove(item)

    ET.indent(tree, space="  ")
    tmp = FEED_XML.with_suffix(".xml.tmp")
    tree.write(str(tmp), encoding="unicode", xml_declaration=True)
    tmp.rename(FEED_XML)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    weeks_map = parse_feed()
    sorted_weeks = sorted(
        weeks_map.values(),
        key=lambda w: (w["week_year"], w["week_num"]),
        reverse=True,
    )
    total_episodes = sum(len(w["episodes"]) for w in sorted_weeks)
    total_size = sum(w["total_size"] for w in sorted_weeks)
    return render_template(
        "index.html",
        weeks=sorted_weeks,
        total_weeks=len(sorted_weeks),
        total_episodes=total_episodes,
        total_size_gb=round(total_size / (1024 ** 3), 2),
    )


@app.route("/episode/<filename>", methods=["DELETE"])
def delete_episode(filename: str):
    if "/" in filename or ".." in filename:
        abort(400)

    file_path = EPISODES_DIR / filename
    if file_path.exists():
        file_path.unlink()

    _update_feed_xml({filename})
    return jsonify({"ok": True, "message": f"Deleted {filename}"})


@app.route("/week/<iso_week>", methods=["DELETE"])
def delete_week(iso_week: str):
    if not re.match(r"^\d{4}-W\d{2}$", iso_week):
        abort(400)

    weeks_map = parse_feed()
    week_data = weeks_map.get(iso_week)
    if not week_data:
        abort(404)

    filenames = {ep["filename"] for ep in week_data["episodes"]}
    for filename in filenames:
        file_path = EPISODES_DIR / filename
        if file_path.exists():
            file_path.unlink()

    _update_feed_xml(filenames)
    return jsonify({
        "ok": True,
        "message": f"Deleted {len(filenames)} episodes from {iso_week}",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
