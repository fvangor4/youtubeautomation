# YouTube Data Explorer

This project is a small Flask application that lets you experiment with the YouTube Data API locally. The UI exposes a search box, quick date-range filters, optional duration constraints, and a topic selector, then renders the highest-viewed matching videos (most views → fewest) along with thumbnails, view counts, and metadata. Choose the Gaming topic to scan the entire gaming category (query optional). If you configure a Discord webhook, you can ship the current search snapshot to Discord with a single button. You can also archive each search (text/JSON/CSV) inside the `data/` folder, browse saved files in-app, and empty the folder when you’re done.

## Prerequisites

- Python 3.10+
- A YouTube Data API key (`YOUTUBE_API_KEY`) created in the Google Cloud Console

## Setup

```bash
cd flask-template
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Export your API key (or place it in a `.env` file read by `python-dotenv`):

```bash
export YOUTUBE_API_KEY="your-key-here"
# or put YOUTUBE_API_KEY=... in .env; the server loads it with override=True
```

For Discord sharing, add the webhook URL to your `.env` as well:

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

For optional endpoint protection (required if you intend to expose the app beyond localhost), set an app token:

```bash
export APP_AUTH_TOKEN="choose-a-secret-token"
```

When `APP_AUTH_TOKEN` is set, all save/share/archive/list endpoints expect the same token in the `X-App-Token` header (the UI stores it in local storage for you).

## Running the app

```bash
flask --app app run --debug
```

Open http://127.0.0.1:5000 and run searches. Each request hits the `/api/search` endpoint, which proxies the query to the YouTube Data API with your chosen filters. After a search completes, the status area shows an estimated YouTube quota cost so you can keep an eye on API usage. Your last-used query/filters/topic/token are cached locally so you can resume where you left off. Select the Gaming topic filter whenever you want to explore the entire gaming category without typing a search term.

### Snapshot exports & sharing

- Click **Send to Discord** to POST the results to your configured webhook (top five results are summarized in the message).
- Choose **Snapshot format** (text/JSON/CSV) and hit **Save Snapshot to Data Folder** to persist the full response under `data/` (one timestamped file per search). The “Snapshot Library” panel lists everything in `data/` with download links for quick inspection or upload to downstream agents.
- Click **Empty Data Folder** to delete every snapshot stored under `data/` (helpful before handing the folder to another tool). You can refresh the library list any time to confirm the state on disk.

## Quick smoke test

To confirm your API key works without launching the UI, run:

```bash
python scripts/smoke_youtube.py "openai updates" --date-range 7d --max-results 3
```

You should see a JSON payload containing the matching videos plus the estimated quota cost for that request. If you get an authentication error, double-check the `YOUTUBE_API_KEY` value and its restrictions in Google Cloud Console.

## Docker (recommended for a quick run)

1) Build the image:
```bash
docker build -t youtube-flask .
```

2) Provide your secrets via env file (copy `docker.env.example` to `docker.env` and fill in real values):
```bash
YOUTUBE_API_KEY=your-real-key
# optional
APP_AUTH_TOKEN=choose-a-token
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

3) Run the container (maps app port 5000 to host 8000):
```bash
docker run --rm -p 8000:5000 --env-file docker.env youtube-flask
```
- Visit http://localhost:8000
- To persist saved snapshots locally: add `-v "$(pwd)/data:/app/data"`
- If port 8000 is busy, swap the left side of `-p` (e.g., `-p 5050:5000`).

## Tests

Install the dev dependencies and run pytest:

```bash
pip install -r dev-requirements.txt
pytest
```

## Future ideas

- Cache previous queries locally so they can be re-run with one click
- Persist result sets for lightweight trend analysis
- Export the data (CSV/JSON) for deeper analysis in notebooks or BI tools
