"""Podcast Manager — episode browser and delete interface."""
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, abort, send_from_directory, request

app = Flask(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
FEED_XML = DATA_DIR / "feed.xml"
EPISODES_DIR = DATA_DIR / "episodes"


def _deletion_log_path() -> Path:
    return DATA_DIR / "deletion-log.jsonl"


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------

def _iso_week(pub_date_str: str) -> tuple:
    """Parse pubDate string → (iso_week_label, year, week_num).

    Returns ('unknown', 0, 0) on failure.
    """
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            dt = datetime.strptime(pub_date_str.strip(), fmt)
            iso = dt.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}", iso[0], iso[1]
        except ValueError:
            continue
    return "unknown", 0, 0


def _week_metadata(year: int, week_num: int) -> dict:
    """Return display metadata for an ISO week."""
    if year == 0:
        return {"start_date": "?", "month_name": "Unknown", "month_key": "unknown"}
    monday = datetime.fromisocalendar(year, week_num, 1)
    return {
        "start_date": monday.strftime("%b %-d"),
        "month_name": monday.strftime("%B"),
        "month_key": monday.strftime("%Y-%m"),
    }


def parse_feed() -> dict:
    """Return episodes grouped by ISO week, with display metadata.

    Returns {} if feed.xml is missing or unparseable.
    Schema:
        { "2026-W15": {
            "iso_week": "2026-W15",
            "week_year": 2026,
            "week_num": 15,
            "start_date": "Apr 7",
            "month_name": "April",
            "month_key": "2026-04",
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

        file_path = EPISODES_DIR / filename
        file_size = file_path.stat().st_size if file_path.exists() else int(enclosure.get("length", 0))

        iso_week, week_year, week_num = _iso_week(pub_date_str)

        if iso_week not in weeks:
            meta = _week_metadata(week_year, week_num)
            weeks[iso_week] = {
                "iso_week": iso_week,
                "week_year": week_year,
                "week_num": week_num,
                "start_date": meta["start_date"],
                "month_name": meta["month_name"],
                "month_key": meta["month_key"],
                "total_size": 0,
                "episodes": [],
            }

        weeks[iso_week]["episodes"].append({
            "title": title,
            "filename": filename,
            "pub_date": pub_date_str,
            "file_size": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 1),
            "iso_week": iso_week,
        })
        weeks[iso_week]["total_size"] += file_size

    return weeks


# ---------------------------------------------------------------------------
# Deletion log
# ---------------------------------------------------------------------------

def _append_deletion_log(episodes: list) -> None:
    """Append one JSON line per episode to the deletion log."""
    now = datetime.now(timezone.utc).isoformat()
    log = _deletion_log_path()
    with open(log, "a", encoding="utf-8") as f:
        for ep in episodes:
            f.write(json.dumps({
                "filename": ep["filename"],
                "title": ep["title"],
                "week": ep["iso_week"],
                "deleted_at": now,
                "file_size": ep["file_size"],
            }) + "\n")


def load_deletion_stats() -> dict:
    """Return {count, total_size} from the deletion log."""
    log = _deletion_log_path()
    if not log.exists():
        return {"count": 0, "total_size": 0}
    count, total_size = 0, 0
    with open(log, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entry = json.loads(line)
                count += 1
                total_size += entry.get("file_size", 0)
    return {"count": count, "total_size": total_size}


# ---------------------------------------------------------------------------
# Feed mutation
# ---------------------------------------------------------------------------

def _update_feed_xml(remove_filenames: set) -> None:
    """Remove <item> entries and write feed.xml back atomically."""
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
        if enc is not None and enc.get("url", "").split("/")[-1] in remove_filenames:
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
    deletion_stats = load_deletion_stats()
    total_episodes = sum(len(w["episodes"]) for w in sorted_weeks)
    total_size = sum(w["total_size"] for w in sorted_weeks)
    return render_template(
        "index.html",
        weeks=sorted_weeks,
        total_weeks=len(sorted_weeks),
        total_episodes=total_episodes,
        total_size_gb=round(total_size / (1024 ** 3), 2),
        deleted_count=deletion_stats["count"],
        deleted_size_gb=round(deletion_stats["total_size"] / (1024 ** 3), 2),
        all_time_count=total_episodes + deletion_stats["count"],
    )


@app.route("/episode/<filename>", methods=["DELETE"])
def delete_episode(filename: str):
    if "/" in filename or ".." in filename:
        abort(400)

    weeks_map = parse_feed()
    episode_info = next(
        (ep for w in weeks_map.values() for ep in w["episodes"] if ep["filename"] == filename),
        None,
    )

    file_path = EPISODES_DIR / filename
    if file_path.exists():
        file_path.unlink()
    _update_feed_xml({filename})

    if episode_info:
        _append_deletion_log([episode_info])

    return jsonify({"ok": True, "message": f"Deleted {filename}"})


@app.route("/week/<iso_week>", methods=["DELETE"])
def delete_week(iso_week: str):
    if not re.match(r"^\d{4}-W\d{2}$", iso_week):
        abort(400)
    weeks_map = parse_feed()
    week_data = weeks_map.get(iso_week)
    if not week_data:
        abort(404)

    episodes = week_data["episodes"]
    filenames = {ep["filename"] for ep in episodes}
    for filename in filenames:
        f = EPISODES_DIR / filename
        if f.exists():
            f.unlink()
    _update_feed_xml(filenames)
    _append_deletion_log(episodes)

    return jsonify({"ok": True, "message": f"Deleted {len(filenames)} episodes from {iso_week}"})


@app.route("/episodes", methods=["DELETE"])
def delete_episodes():
    data = request.get_json(silent=True) or {}
    filenames = data.get("filenames", [])
    if not filenames or not isinstance(filenames, list):
        abort(400)
    for filename in filenames:
        if not isinstance(filename, str) or "/" in filename or ".." in filename:
            abort(400)

    weeks_map = parse_feed()
    all_episodes = [ep for w in weeks_map.values() for ep in w["episodes"]]
    episodes_to_log = [ep for ep in all_episodes if ep["filename"] in set(filenames)]

    for filename in filenames:
        f = EPISODES_DIR / filename
        if f.exists():
            f.unlink()
    _update_feed_xml(set(filenames))
    if episodes_to_log:
        _append_deletion_log(episodes_to_log)

    return jsonify({"ok": True, "message": f"Deleted {len(filenames)} episodes"})


@app.route("/download/<filename>")
def download_episode(filename: str):
    if "/" in filename or ".." in filename:
        abort(400)
    return send_from_directory(EPISODES_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
