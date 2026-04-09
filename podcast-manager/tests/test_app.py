"""Tests for podcast-manager Flask app."""
import json
import xml.etree.ElementTree as ET
import pytest
from pathlib import Path

SAMPLE_FEED = """\
<?xml version='1.0' encoding='utf-8'?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Episode W15-A</title>
      <pubDate>Mon, 06 Apr 2026 00:00:00 +0000</pubDate>
      <enclosure url="http://nas/episodes/ep-w15-a.m4a" length="1000000" type="audio/mp4"/>
      <guid>http://nas/episodes/ep-w15-a.m4a</guid>
    </item>
    <item>
      <title>Episode W15-B</title>
      <pubDate>Tue, 07 Apr 2026 00:00:00 +0000</pubDate>
      <enclosure url="http://nas/episodes/ep-w15-b.m4a" length="2000000" type="audio/mp4"/>
      <guid>http://nas/episodes/ep-w15-b.m4a</guid>
    </item>
    <item>
      <title>Episode W13</title>
      <pubDate>Mon, 23 Mar 2026 00:00:00 +0000</pubDate>
      <enclosure url="http://nas/episodes/ep-w13.m4a" length="500000" type="audio/mp4"/>
      <guid>http://nas/episodes/ep-w13.m4a</guid>
    </item>
  </channel>
</rss>"""


@pytest.fixture()
def data_dir(tmp_path):
    episodes_dir = tmp_path / "episodes"
    episodes_dir.mkdir()
    (tmp_path / "feed.xml").write_text(SAMPLE_FEED, encoding="utf-8")
    for name in ("ep-w15-a.m4a", "ep-w15-b.m4a", "ep-w13.m4a"):
        (episodes_dir / name).write_bytes(b"fake")
    return tmp_path


@pytest.fixture()
def client(data_dir, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(app_module, "FEED_XML", data_dir / "feed.xml")
    monkeypatch.setattr(app_module, "EPISODES_DIR", data_dir / "episodes")
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


# --- index ---

def test_index_returns_200(client):
    assert client.get("/").status_code == 200


def test_index_shows_week_badges(client):
    body = client.get("/").data
    assert b"W15" in body
    assert b"W13" in body


def test_index_shows_episode_titles(client):
    body = client.get("/").data
    assert b"Episode W15-A" in body
    assert b"Episode W15-B" in body
    assert b"Episode W13" in body


def test_index_shows_month_names_in_sidebar(client):
    body = client.get("/").data
    assert b"April" in body
    assert b"March" in body


def test_index_shows_all_time_stats(client, data_dir, monkeypatch):
    import app as app_module
    # Seed a deletion log entry
    log = data_dir / "deletion-log.jsonl"
    log.write_text(
        json.dumps({"filename": "old.m4a", "title": "Old", "week": "2026-W10",
                    "deleted_at": "2026-03-07T10:00:00+00:00", "file_size": 500000}) + "\n"
    )
    body = client.get("/").data
    # all_time_count = 3 current + 1 deleted = 4
    assert b"4" in body


def test_index_no_feed_xml_returns_empty(data_dir, monkeypatch):
    import app as app_module
    (data_dir / "feed.xml").unlink()
    monkeypatch.setattr(app_module, "FEED_XML", data_dir / "feed.xml")
    monkeypatch.setattr(app_module, "EPISODES_DIR", data_dir / "episodes")
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        body = c.get("/").data
    assert b"No episodes" in body


# --- DELETE /episode/<filename> ---

def test_delete_episode_returns_ok(client):
    r = client.delete("/episode/ep-w15-a.m4a")
    assert r.status_code == 200
    assert json.loads(r.data)["ok"] is True


def test_delete_episode_removes_file(client, data_dir):
    client.delete("/episode/ep-w15-a.m4a")
    assert not (data_dir / "episodes" / "ep-w15-a.m4a").exists()


def test_delete_episode_removes_item_from_feed(client, data_dir):
    client.delete("/episode/ep-w15-a.m4a")
    titles = [i.findtext("title") for i in ET.parse(data_dir / "feed.xml").findall(".//item")]
    assert "Episode W15-A" not in titles
    assert "Episode W15-B" in titles
    assert "Episode W13" in titles


def test_delete_episode_writes_deletion_log(client, data_dir):
    client.delete("/episode/ep-w15-a.m4a")
    log = data_dir / "deletion-log.jsonl"
    assert log.exists()
    entry = json.loads(log.read_text().strip())
    assert entry["filename"] == "ep-w15-a.m4a"
    assert entry["title"] == "Episode W15-A"
    assert entry["week"] == "2026-W15"
    assert "deleted_at" in entry
    assert entry["file_size"] == 4  # len(b"fake")


def test_delete_episode_missing_file_still_updates_feed(client, data_dir):
    (data_dir / "episodes" / "ep-w15-a.m4a").unlink()
    r = client.delete("/episode/ep-w15-a.m4a")
    assert r.status_code == 200
    titles = [i.findtext("title") for i in ET.parse(data_dir / "feed.xml").findall(".//item")]
    assert "Episode W15-A" not in titles


def test_delete_episode_rejects_path_traversal(client):
    # Flask normalizes /episode/../feed.xml → /feed.xml (no matching route → 404)
    # Both 400 and 404 are safe — path traversal is blocked either way
    r = client.delete("/episode/../feed.xml")
    assert r.status_code in (400, 404)


def test_delete_episode_rejects_slash_in_filename(client):
    r = client.delete("/episode/subdir/ep-w15-a.m4a")
    assert r.status_code in (400, 404)


# --- DELETE /week/<iso_week> ---

def test_delete_week_returns_ok(client):
    r = client.delete("/week/2026-W15")
    assert r.status_code == 200
    assert json.loads(r.data)["ok"] is True


def test_delete_week_removes_all_files_in_week(client, data_dir):
    client.delete("/week/2026-W15")
    assert not (data_dir / "episodes" / "ep-w15-a.m4a").exists()
    assert not (data_dir / "episodes" / "ep-w15-b.m4a").exists()
    assert (data_dir / "episodes" / "ep-w13.m4a").exists()


def test_delete_week_removes_only_that_weeks_feed_items(client, data_dir):
    client.delete("/week/2026-W15")
    titles = [i.findtext("title") for i in ET.parse(data_dir / "feed.xml").findall(".//item")]
    assert "Episode W15-A" not in titles
    assert "Episode W15-B" not in titles
    assert "Episode W13" in titles


def test_delete_week_writes_deletion_log(client, data_dir):
    client.delete("/week/2026-W15")
    log = data_dir / "deletion-log.jsonl"
    assert log.exists()
    entries = [json.loads(l) for l in log.read_text().strip().splitlines()]
    assert len(entries) == 2
    filenames = {e["filename"] for e in entries}
    assert filenames == {"ep-w15-a.m4a", "ep-w15-b.m4a"}
    assert all(e["week"] == "2026-W15" for e in entries)


# --- GET /download/<filename> ---

def test_download_episode_returns_file(client, data_dir):
    r = client.get("/download/ep-w15-a.m4a")
    assert r.status_code == 200
    assert r.data == b"fake"
    assert "attachment" in r.headers.get("Content-Disposition", "")


def test_download_episode_rejects_path_traversal(client):
    r = client.get("/download/../feed.xml")
    assert r.status_code in (400, 404)


def test_download_episode_missing_returns_404(client, data_dir):
    (data_dir / "episodes" / "ep-w15-a.m4a").unlink()
    r = client.get("/download/ep-w15-a.m4a")
    assert r.status_code == 404


def test_delete_week_rejects_invalid_format(client):
    r = client.delete("/week/not-a-week")
    assert r.status_code == 400


def test_delete_week_unknown_week_returns_404(client):
    r = client.delete("/week/2026-W99")
    assert r.status_code == 404
