import requests

from conftest import (
    API_BASE,
    FIXTURE_PATH,
    delete_entry,
    skip_no_ollama,
    upload_fixture,
)


# --- Health ---


def test_status_endpoint():
    r = requests.get(f"{API_BASE}/api/status", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"
    assert isinstance(data["total_entries"], int)


# --- Upload ---


def test_upload_ok(uploaded_entry):
    assert uploaded_entry["status"] == "ok"
    assert len(uploaded_entry["entry_id"]) == 16
    assert uploaded_entry["title"] == "Integration Test Book"


def test_upload_idempotent(api_url, uploaded_entry):
    second = upload_fixture(api_url, FIXTURE_PATH)
    assert second["entry_id"] == uploaded_entry["entry_id"]


def test_upload_invalid_file(api_url):
    r = requests.post(
        f"{api_url}/api/upload",
        files={"file": ("bad.md", b"no separators here", "text/markdown")},
        timeout=10,
    )
    assert r.status_code == 400
    assert "Invalid library entry" in r.json()["detail"]


# --- List / Filter ---


def test_list_entries(api_url, uploaded_entry):
    r = requests.get(
        f"{api_url}/api/entries",
        params={"title": "Integration Test Book"},
        timeout=10,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    ids = [e["id"] for e in data["entries"]]
    assert uploaded_entry["entry_id"] in ids


def test_list_entries_pagination(api_url, uploaded_entry):
    r = requests.get(f"{api_url}/api/entries", params={"limit": 1}, timeout=10)
    data = r.json()
    assert len(data["entries"]) == 1
    assert data["total"] >= 1


def test_filter_title(api_url, uploaded_entry):
    r = requests.get(
        f"{api_url}/api/entries", params={"title": "Integration Test"}, timeout=10
    )
    ids = [e["id"] for e in r.json()["entries"]]
    assert uploaded_entry["entry_id"] in ids


def test_filter_author(api_url, uploaded_entry):
    r = requests.get(
        f"{api_url}/api/entries", params={"author": "Test Author"}, timeout=10
    )
    ids = [e["id"] for e in r.json()["entries"]]
    assert uploaded_entry["entry_id"] in ids


def test_filter_genre(api_url, uploaded_entry):
    r = requests.get(
        f"{api_url}/api/entries", params={"genre": "Testing"}, timeout=10
    )
    ids = [e["id"] for e in r.json()["entries"]]
    assert uploaded_entry["entry_id"] in ids


def test_filter_tag(api_url, uploaded_entry):
    r = requests.get(
        f"{api_url}/api/entries", params={"tag": "integration"}, timeout=10
    )
    ids = [e["id"] for e in r.json()["entries"]]
    assert uploaded_entry["entry_id"] in ids


def test_filter_year(api_url, uploaded_entry):
    r = requests.get(
        f"{api_url}/api/entries",
        params={"year_min": 2025, "year_max": 2025},
        timeout=10,
    )
    ids = [e["id"] for e in r.json()["entries"]]
    assert uploaded_entry["entry_id"] in ids


def test_filter_no_match(api_url, uploaded_entry):
    r = requests.get(
        f"{api_url}/api/entries",
        params={"title": "NonexistentBookXYZ999"},
        timeout=10,
    )
    data = r.json()
    assert data["entries"] == []
    assert data["total"] == 0


# --- Pages ---


def test_get_page_shortsummary(api_url, uploaded_entry):
    eid = uploaded_entry["entry_id"]
    r = requests.get(
        f"{api_url}/api/entries/{eid}/page",
        params={"section": "shortsummary", "page": 1},
        timeout=10,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["section"] == "shortsummary"
    assert data["page_number"] == 1
    assert data["total_pages"] >= 1
    assert len(data["content"]) > 0


def test_get_page_summary(api_url, uploaded_entry):
    eid = uploaded_entry["entry_id"]
    r = requests.get(
        f"{api_url}/api/entries/{eid}/page",
        params={"section": "summary", "page": 1},
        timeout=10,
    )
    assert r.status_code == 200
    assert len(r.json()["content"]) > 0


def test_get_page_fulltext(api_url, uploaded_entry):
    eid = uploaded_entry["entry_id"]
    r = requests.get(
        f"{api_url}/api/entries/{eid}/page",
        params={"section": "fulltext", "page": 1},
        timeout=10,
    )
    assert r.status_code == 200
    assert len(r.json()["content"]) > 0


def test_get_page_invalid_section(api_url, uploaded_entry):
    eid = uploaded_entry["entry_id"]
    r = requests.get(
        f"{api_url}/api/entries/{eid}/page",
        params={"section": "invalid"},
        timeout=10,
    )
    assert r.status_code == 400


def test_get_page_out_of_range(api_url, uploaded_entry):
    eid = uploaded_entry["entry_id"]
    r = requests.get(
        f"{api_url}/api/entries/{eid}/page",
        params={"section": "shortsummary", "page": 9999},
        timeout=10,
    )
    assert r.status_code == 400


def test_get_page_not_found(api_url):
    r = requests.get(
        f"{api_url}/api/entries/0000000000000000/page",
        params={"section": "summary", "page": 1},
        timeout=10,
    )
    assert r.status_code == 404


# --- Full-Text Search ---


def test_search_finds_entry(api_url, uploaded_entry):
    r = requests.get(
        f"{api_url}/api/search",
        params={"q": "quantum xylophone orchestration"},
        timeout=10,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total_results"] >= 1
    ids = [res["entry_id"] for res in data["results"]]
    assert uploaded_entry["entry_id"] in ids


def test_search_section_filter(api_url, uploaded_entry):
    r = requests.get(
        f"{api_url}/api/search",
        params={"q": "quantum xylophone", "section": "fulltext"},
        timeout=10,
    )
    assert r.status_code == 200
    for res in r.json()["results"]:
        assert res["section"] == "fulltext"


def test_search_no_results(api_url, uploaded_entry):
    r = requests.get(
        f"{api_url}/api/search",
        params={"q": "zzzznonexistentterm99999"},
        timeout=10,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["results"] == []
    assert data["total_results"] == 0


# --- Semantic Search ---


@skip_no_ollama
def test_semantic_search_basic(api_url, uploaded_entry):
    r = requests.post(
        f"{api_url}/api/semantic-search",
        json={"query": "music and technology", "limit": 5},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["results"], list)
    assert isinstance(data["total_results"], int)


# --- Delete ---


def test_delete_entry(api_url):
    result = upload_fixture(api_url, FIXTURE_PATH)
    eid = result["entry_id"]
    r = requests.delete(f"{api_url}/api/entries/{eid}", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    # Verify it's gone.
    r2 = requests.get(
        f"{api_url}/api/entries/{eid}/page",
        params={"section": "summary", "page": 1},
        timeout=10,
    )
    assert r2.status_code == 404


def test_delete_nonexistent(api_url):
    r = requests.delete(f"{api_url}/api/entries/0000000000000000", timeout=10)
    assert r.status_code == 404
