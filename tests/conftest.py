import os

import pytest
import requests

API_BASE = os.environ.get("TEST_API_URL", "http://localhost:9821")
MCP_BASE = os.environ.get("TEST_MCP_URL", "http://localhost:9823")
FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "test_fixture.md")


def ollama_available():
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


skip_no_ollama = pytest.mark.skipif(
    not ollama_available(),
    reason="Ollama not available",
)


def upload_fixture(url, path):
    with open(path, "rb") as f:
        r = requests.post(
            f"{url}/api/upload",
            files={"file": ("test_fixture.md", f, "text/markdown")},
            timeout=30,
        )
    r.raise_for_status()
    return r.json()


def delete_entry(url, entry_id):
    r = requests.delete(f"{url}/api/entries/{entry_id}", timeout=10)
    if r.status_code not in (200, 404):
        r.raise_for_status()


@pytest.fixture(scope="module")
def api_url():
    return API_BASE


@pytest.fixture(scope="module")
def mcp_url():
    return MCP_BASE


@pytest.fixture(scope="module")
def uploaded_entry(api_url):
    result = upload_fixture(api_url, FIXTURE_PATH)
    yield result
    delete_entry(api_url, result["entry_id"])
