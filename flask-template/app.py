import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import requests

load_dotenv(override=True)

app = Flask(__name__)

DATE_RANGE_OPTIONS = {
    "1d": {"label": "Past day", "days": 1},
    "7d": {"label": "Past 7 days", "days": 7},
    "14d": {"label": "Past 14 days", "days": 14},
    "30d": {"label": "Past 30 days", "days": 30},
}
DEFAULT_DATE_RANGE = "7d"
TOPIC_FILTERS = {
    "none": {"label": "All topics", "allows_empty_query": False},
    "gaming": {
        "label": "Gaming (global)",
        "topicId": "/m/0bzvm2",
        "allows_empty_query": True,
    },
}
DEFAULT_TOPIC = "none"
VALID_DURATION_FILTERS = {
    "any": "Any length",
    "short": "Under 4 minutes",
    "medium": "4-20 minutes",
    "long": "Over 20 minutes",
}
MAX_ALLOWED_RESULTS = 25
SEARCH_ORDER = "viewCount"
MAX_DISCORD_RESULTS = 5
DATA_DIR = Path(__file__).resolve().parent / "data"
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
SEARCH_QUOTA_COST = 100
STATS_QUOTA_COST = 1
APP_AUTH_TOKEN = os.getenv("APP_AUTH_TOKEN")

DATA_DIR.mkdir(exist_ok=True)


def ensure_authorized():
    """Require the optional app token for mutating/archive endpoints."""
    if not APP_AUTH_TOKEN:
        return
    candidate = (
        request.headers.get("X-App-Token")
        or request.args.get("token")
        or ((request.get_json(silent=True) or {}).get("token"))
    )
    if candidate != APP_AUTH_TOKEN:
        abort(401, description="Invalid or missing app token.")


def _require_api_key() -> str:
    """Fetch the API key or fail fast with a descriptive error."""
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing YOUTUBE_API_KEY environment variable. "
            "Create an API key in Google Cloud Console and export it."
        )
    return api_key


def build_youtube_client():
    return build("youtube", "v3", developerKey=_require_api_key(), cache_discovery=False)


def _normalize_date_range(range_key: str) -> dict:
    return DATE_RANGE_OPTIONS.get(range_key, DATE_RANGE_OPTIONS[DEFAULT_DATE_RANGE])


def _normalize_duration_filter(duration_key: str) -> str:
    return duration_key if duration_key in VALID_DURATION_FILTERS else "any"


def _normalize_topic(topic_key: str) -> dict:
    return TOPIC_FILTERS.get(topic_key, TOPIC_FILTERS[DEFAULT_TOPIC])


def fetch_video_statistics(client, video_ids):
    if not video_ids:
        return {}
    response = (
        client.videos()
        .list(
            part="statistics",
            id=",".join(video_ids),
        )
        .execute()
    )
    stats = {}
    for item in response.get("items", []):
        video_id = item.get("id")
        if not video_id:
            continue
        try:
            stats[video_id] = int(item.get("statistics", {}).get("viewCount", 0))
        except (TypeError, ValueError):
            stats[video_id] = 0
    return stats


def format_discord_message(snapshot: dict) -> str:
    """Build a readable Discord message summarizing the search results."""
    query = snapshot.get("query", "Unknown query")
    date_range = snapshot.get("dateRange", DEFAULT_DATE_RANGE)
    duration = snapshot.get("duration", "any")
    items = snapshot.get("items") or []

    header = (
        "**YouTube Search Snapshot**\n"
        f"• Query: `{query}`\n"
        f"• Range: {date_range} | Duration: {duration} | Results: {len(items)}\n"
    )
    lines = [header]

    for idx, item in enumerate(items[:MAX_DISCORD_RESULTS], start=1):
        title = item.get("title") or "Untitled video"
        url = item.get("url") or "https://youtube.com"
        channel = item.get("channelTitle") or "Unknown channel"
        views = item.get("viewCount") or 0
        lines.append(f"{idx}. [{title}]({url}) — {channel} • {views:,} views")

    if len(items) > MAX_DISCORD_RESULTS:
        remaining = len(items) - MAX_DISCORD_RESULTS
        lines.append(f"...and {remaining} more result(s).")

    return "\n".join(lines)


def post_to_discord(snapshot: dict):
    """Send the formatted snapshot to the configured Discord webhook."""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError(
            "Missing DISCORD_WEBHOOK_URL. Set it in your environment to enable Discord exports."
        )

    payload = {"content": format_discord_message(snapshot)}
    response = requests.post(webhook_url, json=payload, timeout=15)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Discord webhook returned status {response.status_code}: {response.text[:200]}"
        )


def _slugify(label: str) -> str:
    slug = SLUG_PATTERN.sub("-", label.lower()).strip("-")
    return slug or "search"


def format_snapshot_text(snapshot: dict, saved_at: str) -> str:
    query = snapshot.get("query", "Unknown query")
    date_range = snapshot.get("dateRange", DEFAULT_DATE_RANGE)
    duration = snapshot.get("duration", "any")
    topic = snapshot.get("topic") or DEFAULT_TOPIC
    items = snapshot.get("items") or []

    lines = [
        "YouTube Search Snapshot",
        f"Saved at: {saved_at}",
        f"Query: {query}",
        f"Date range: {date_range}",
        f"Duration filter: {duration}",
        f"Topic filter: {TOPIC_FILTERS.get(topic, {}).get('label', 'All topics')}",
        f"Results captured: {len(items)}",
        "",
    ]

    for idx, item in enumerate(items, start=1):
        lines.append(
            f"{idx}. {item.get('title') or 'Untitled video'} "
            f"({item.get('url') or 'https://youtube.com'})"
        )
        lines.append(
            f"    Channel: {item.get('channelTitle') or 'Unknown'} | "
            f"Published: {item.get('publishedAt') or 'Unknown'} | "
            f"Views: {item.get('viewCount', 0)}"
        )
        if item.get("description"):
            lines.append(f"    Description: {item['description'][:280]}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def write_snapshot_to_file(snapshot: dict, export_format: str = "text") -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    export_format = (export_format or "text").lower()
    timestamp = datetime.now(timezone.utc)
    saved_at_iso = timestamp.replace(microsecond=0).isoformat()
    stamp = timestamp.strftime("%Y%m%d_%H%M%S")
    slug = _slugify(snapshot.get("query") or "search")
    base_name = f"{stamp}_{slug}"

    if export_format == "json":
        filename = f"{base_name}.json"
        payload = {
            "savedAt": saved_at_iso,
            "query": snapshot.get("query"),
            "dateRange": snapshot.get("dateRange"),
            "duration": snapshot.get("duration"),
            "topic": snapshot.get("topic") or DEFAULT_TOPIC,
            "items": snapshot.get("items", []),
        }
        file_path = DATA_DIR / filename
        file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    elif export_format == "csv":
        filename = f"{base_name}.csv"
        fieldnames = [
            "query",
            "dateRange",
            "duration",
            "topic",
            "savedAt",
            "title",
            "url",
            "channelTitle",
            "publishedAt",
            "viewCount",
            "description",
        ]
        file_path = DATA_DIR / filename
        with file_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for item in snapshot.get("items", []):
                writer.writerow(
                    {
                        "query": snapshot.get("query"),
                        "dateRange": snapshot.get("dateRange"),
                        "duration": snapshot.get("duration"),
                        "topic": snapshot.get("topic") or DEFAULT_TOPIC,
                        "savedAt": saved_at_iso,
                        "title": item.get("title"),
                        "url": item.get("url"),
                        "channelTitle": item.get("channelTitle"),
                        "publishedAt": item.get("publishedAt"),
                        "viewCount": item.get("viewCount"),
                        "description": item.get("description"),
                    }
                )
    else:
        filename = f"{base_name}.txt"
        file_path = DATA_DIR / filename
        file_path.write_text(format_snapshot_text(snapshot, saved_at_iso), encoding="utf-8")
    return file_path


def clear_data_directory() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    deleted = 0
    for item in DATA_DIR.iterdir():
        if item.name == ".gitkeep":
            continue
        if item.is_file():
            item.unlink()
            deleted += 1
    return deleted


def list_snapshot_files():
    DATA_DIR.mkdir(exist_ok=True)
    entries = []
    for entry in sorted(DATA_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True):
        if entry.name.startswith("."):
            continue
        if not entry.is_file():
            continue
        stats = entry.stat()
        entries.append(
            {
                "name": entry.name,
                "size": stats.st_size,
                "modified": datetime.fromtimestamp(stats.st_mtime, timezone.utc).isoformat(),
            }
        )
    return entries


def search_youtube(
    query: str,
    range_key: str,
    *,
    duration: str = "any",
    max_results: int = 12,
    topic_key: str = DEFAULT_TOPIC,
):
    topic_config = _normalize_topic(topic_key)
    if not query and not topic_config.get("allows_empty_query"):
        raise ValueError("Query is required.")

    normalized_range = _normalize_date_range(range_key)
    normalized_duration = _normalize_duration_filter(duration)
    days_back = normalized_range["days"]

    published_after = datetime.utcnow() - timedelta(days=days_back)
    published_after_iso = published_after.replace(microsecond=0).isoformat() + "Z"

    capped_results = max(1, min(max_results, MAX_ALLOWED_RESULTS))
    client = build_youtube_client()

    search_kwargs = {
        "part": "snippet",
        "type": "video",
        "order": SEARCH_ORDER,
        "maxResults": capped_results,
        "publishedAfter": published_after_iso,
    }
    if query:
        search_kwargs["q"] = query
    if normalized_duration != "any":
        search_kwargs["videoDuration"] = normalized_duration
    if topic_config.get("topicId"):
        search_kwargs["topicId"] = topic_config["topicId"]

    response = client.search().list(**search_kwargs).execute()
    results = []
    video_ids = []
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId")
        if not video_id:
            continue
        video_ids.append(video_id)
        results.append(
            {
                "videoId": video_id,
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "channelTitle": snippet.get("channelTitle"),
                "publishedAt": snippet.get("publishedAt"),
                "thumbnail": (snippet.get("thumbnails", {}).get("medium") or {}).get("url"),
                "viewCount": 0,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )
    view_counts = fetch_video_statistics(client, video_ids)
    for result in results:
        result["viewCount"] = view_counts.get(result["videoId"], 0)
    results.sort(key=lambda item: item.get("viewCount", 0), reverse=True)
    quota_cost = SEARCH_QUOTA_COST + (STATS_QUOTA_COST if video_ids else 0)
    return results, quota_cost


@app.route("/")
def home():
    return render_template(
        "home.html",
        date_ranges=DATE_RANGE_OPTIONS,
        duration_filters=VALID_DURATION_FILTERS,
        default_range=DEFAULT_DATE_RANGE,
        snapshot_formats={
            "text": "Plain text (.txt)",
            "json": "JSON (.json)",
            "csv": "CSV (.csv)",
        },
        topic_filters=TOPIC_FILTERS,
        default_topic=DEFAULT_TOPIC,
        token_required=bool(APP_AUTH_TOKEN),
    )


@app.post("/api/search")
def api_search():
    payload = request.get_json() or {}
    query = (payload.get("query") or "").strip()
    range_key = payload.get("dateRange") or DEFAULT_DATE_RANGE
    duration = payload.get("duration") or "any"
    requested_limit = payload.get("maxResults") or 12
    topic_key = payload.get("topic") or DEFAULT_TOPIC

    try:
        results, quota_cost = search_youtube(
            query,
            range_key,
            duration=duration,
            max_results=int(requested_limit),
            topic_key=topic_key,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    except HttpError as exc:
        error_message = exc.error_details if hasattr(exc, "error_details") else str(exc)
        return jsonify({"error": f"YouTube API error: {error_message}"}), 502

    return jsonify({"items": results, "quotaUsed": quota_cost})


@app.post("/api/save")
def save_snapshot():
    ensure_authorized()
    snapshot = request.get_json() or {}
    query = (snapshot.get("query") or "").strip()
    items = snapshot.get("items") or []
    export_format = snapshot.get("format") or "text"
    topic_key = snapshot.get("topic") or DEFAULT_TOPIC
    topic_config = _normalize_topic(topic_key)
    snapshot.pop("format", None)
    snapshot.pop("token", None)

    if (not query and not topic_config.get("allows_empty_query")) or not items:
        return (
            jsonify({"error": "A query and at least one result are required to save."}),
            400,
        )

    try:
        saved_file = write_snapshot_to_file(snapshot, export_format=export_format)
    except OSError as exc:
        return jsonify({"error": f"Unable to save snapshot: {exc}"}), 500

    return jsonify({"status": "ok", "file": saved_file.name})


@app.post("/api/notify")
def notify_discord():
    ensure_authorized()
    snapshot = request.get_json() or {}
    snapshot.pop("token", None)
    query = (snapshot.get("query") or "").strip()
    items = snapshot.get("items") or []
    topic_key = snapshot.get("topic") or DEFAULT_TOPIC
    topic_config = _normalize_topic(topic_key)

    if (not query and not topic_config.get("allows_empty_query")) or not items:
        return (
            jsonify({"error": "A query and at least one result are required to share."}),
            400,
        )

    try:
        post_to_discord(snapshot)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"status": "ok"})


@app.post("/api/archive/clear")
def clear_archive():
    ensure_authorized()
    deleted = clear_data_directory()
    return jsonify({"status": "ok", "deleted": deleted})


@app.get("/api/snapshots")
def get_snapshots():
    ensure_authorized()
    files = list_snapshot_files()
    return jsonify({"items": files})


@app.get("/archive/<path:filename>")
def download_snapshot(filename: str):
    ensure_authorized()
    target = (DATA_DIR / filename).resolve()
    try:
        target.relative_to(DATA_DIR.resolve())
    except ValueError:
        abort(404)
    if not target.exists() or not target.is_file():
        abort(404)
    return send_from_directory(DATA_DIR, target.name, as_attachment=True)
