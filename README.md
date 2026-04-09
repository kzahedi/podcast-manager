# Podcast Manager

A lightweight web interface for managing podcast episodes served from a local NAS or server. Browse episodes by week, delete individual episodes or entire weeks, and download files — all while keeping your RSS feed up to date so Apple Podcasts (or any podcast client) reflects the changes automatically.

## Features

- **Browse by week** — episodes grouped by ISO week with a collapsible Year › Month › Week sidebar
- **Delete an episode** — removes the file and strips it from `feed.xml`
- **Delete a week** — removes all episodes in a week in one click
- **Download episodes** — download `.m4a`/`.mp3` files directly to your computer
- **All-time stats** — tracks every deletion in an append-only log so you always know the historical episode count and storage freed
- **No database** — `feed.xml` is the single source of truth; the deletion log is a plain `.jsonl` file

## Requirements

- Docker + Docker Compose
- A pre-generated `feed.xml` and a directory of episode audio files

## Quick Start

### 1. Prepare your data

```bash
mkdir -p data/episodes
cp /path/to/your/feed.xml data/feed.xml
# Copy your .m4a / .mp3 files into data/episodes/
```

Or use the helper script to test with placeholder files (no audio copied):

```bash
./setup-local-data.sh /path/to/feed.xml
```

### 2. Run

```bash
docker compose up --build
```

Open [http://localhost:8841](http://localhost:8841).

## Data layout

```
data/
├── feed.xml           # RSS feed (read + updated in place)
├── episodes/          # Audio files
│   ├── episode-1.m4a
│   └── ...
└── deletion-log.jsonl # Append-only deletion history (created on first delete)
```

## How it works

- **Deleting an episode or week** removes the file(s) from `episodes/` and rewrites `feed.xml` atomically (write to `.xml.tmp` then rename), so your podcast client sees the change on its next refresh.
- **The deletion log** (`deletion-log.jsonl`) is never modified — one JSON line is appended per deleted episode. All-time stats = current feed count + log count.

## Configuration

| Environment variable | Default | Description |
|----------------------|---------|-------------|
| `DATA_DIR` | `/data` | Path containing `feed.xml` and `episodes/` |

## Docker Compose

```yaml
services:
  podcast-manager:
    build: ./podcast-manager
    ports:
      - "8841:8080"
    volumes:
      - ./data:/data
    environment:
      - DATA_DIR=/data
```

To run alongside an existing nginx podcast feed, add this service to your existing `docker-compose.yml` and point both at the same `data/` volume.

## Deploying to a remote host (e.g. Synology NAS)

The `deploy.sh` script builds the image locally, transfers it via SCP, and restarts the service — no Docker registry required.

### 1. Configure

```bash
cp .env.deploy.example .env.deploy
# Edit .env.deploy with your host, user, and remote path
```

`.env.deploy` is gitignored so credentials never reach the repository.

### 2. Deploy

```bash
./deploy.sh
```

What it does:
1. `docker build` the image locally
2. `docker save` → exports a `.tar`
3. `scp` the tar to the remote host
4. SSH in: `docker load`, delete the tar, `docker compose up -d`

### Build only (no remote step)

```bash
./deploy.sh --build-only
```

Exports `podcast-manager.tar` locally — useful for manual transfer or debugging.

### SSH key setup

The script uses `BatchMode=yes` (no password prompts). Make sure your SSH public key is in `~/.ssh/authorized_keys` on the remote host before running:

```bash
ssh-copy-id -p 22 user@your-nas-host
```

## Development

```bash
cd podcast-manager
pip install -r requirements.txt
pytest tests/ -v
```

## License

MIT
