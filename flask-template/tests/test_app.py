import app as app_module
import pytest
from app import app as flask_app


@pytest.fixture
def client():
    with flask_app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def reset_auth_token(monkeypatch):
    monkeypatch.setattr(app_module, "APP_AUTH_TOKEN", None)


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    return tmp_path


def test_home(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Search query" in response.data


def test_api_search_requires_query(client):
    response = client.post("/api/search", json={"query": "", "topic": "none"})
    assert response.status_code == 400
    assert b"Query is required" in response.data
    

def test_api_search_allows_topic_without_query(client, monkeypatch):
    stub_response = [{"videoId": "gaming"}]

    def fake_search(query, range_key, duration="any", max_results=12, topic_key="none"):
        assert query == ""
        assert topic_key == "gaming"
        return stub_response, 55

    monkeypatch.setattr("app.search_youtube", fake_search)
    response = client.post("/api/search", json={"query": "", "topic": "gaming"})
    assert response.status_code == 200
    assert response.get_json()["items"] == stub_response


def test_api_search_returns_mocked_results(client, monkeypatch):
    stub_response = [{"videoId": "abc123"}]

    def fake_search(query, range_key, duration="any", max_results=12, topic_key="none"):
        assert query == "python"
        assert range_key == "7d"
        assert topic_key == "none"
        return stub_response, 42

    monkeypatch.setattr("app.search_youtube", fake_search)

    response = client.post("/api/search", json={"query": "python"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["items"] == stub_response
    assert payload["quotaUsed"] == 42


def test_notify_requires_results(client):
    response = client.post("/api/notify", json={"query": "python", "items": []})
    assert response.status_code == 400
    assert b"required" in response.data


def test_notify_invokes_discord_hook(client, monkeypatch):
    captured = {}

    def fake_post(snapshot):
        captured["snapshot"] = snapshot

    monkeypatch.setattr("app.post_to_discord", fake_post)

    payload = {
        "query": "python",
        "topic": "none",
        "items": [
            {"title": "Video 1", "url": "https://youtu.be/1", "channelTitle": "Channel", "viewCount": 10}
        ],
    }
    response = client.post("/api/notify", json=payload)
    assert response.status_code == 200
    assert captured["snapshot"]["query"] == "python"


def test_save_snapshot_requires_results(client):
    response = client.post("/api/save", json={"query": "python", "items": []})
    assert response.status_code == 400
    assert b"required" in response.data


def test_save_snapshot_calls_writer(client, monkeypatch, tmp_path):
    created = tmp_path / "file.txt"

    def fake_write(snapshot, export_format="text"):
        created.write_text(export_format)
        return created

    monkeypatch.setattr("app.write_snapshot_to_file", fake_write)

    payload = {
        "query": "python",
        "topic": "none",
        "items": [
            {"title": "Video 1", "url": "https://youtu.be/1", "channelTitle": "Channel", "viewCount": 10}
        ],
    }
    response = client.post("/api/save", json={**payload, "format": "json"})
    assert response.status_code == 200
    assert response.get_json()["file"] == created.name


def test_clear_archive_deletes_files(client, monkeypatch):
    monkeypatch.setattr("app.clear_data_directory", lambda: 3)
    response = client.post("/api/archive/clear")
    assert response.status_code == 200
    assert response.get_json()["deleted"] == 3


def test_snapshot_listing(client, data_dir):
    (data_dir / "one.txt").write_text("a")
    (data_dir / "two.json").write_text("b")
    response = client.get("/api/snapshots")
    assert response.status_code == 200
    items = response.get_json()["items"]
    assert len(items) == 2
    assert {item["name"] for item in items} == {"one.txt", "two.json"}


def test_download_snapshot(client, data_dir):
    file_path = data_dir / "demo.txt"
    file_path.write_text("content")
    response = client.get("/archive/demo.txt")
    assert response.status_code == 200
    assert response.data == b"content"


def test_auth_token_required(client, monkeypatch):
    monkeypatch.setattr(app_module, "APP_AUTH_TOKEN", "secret")
    response = client.post("/api/save", json={"query": "x", "items": [{"videoId": "1"}]})
    assert response.status_code == 401
    response = client.post(
        "/api/save",
        json={"query": "x", "items": [{"videoId": "1"}]},
        headers={"X-App-Token": "secret"},
    )
    assert response.status_code != 401
