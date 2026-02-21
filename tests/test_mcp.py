import json

import pytest
import requests

from conftest import MCP_BASE, skip_no_ollama


class MCPTestClient:
    """Minimal MCP streamable-http client for testing."""

    def __init__(self, base_url):
        self.endpoint = f"{base_url}/mcp"
        self.session_id = None
        self._id = 0

    def _next_id(self):
        self._id += 1
        return self._id

    def _post(self, payload):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        r = requests.post(self.endpoint, json=payload, headers=headers, timeout=30)
        r.raise_for_status()

        if "Mcp-Session-Id" in r.headers:
            self.session_id = r.headers["Mcp-Session-Id"]

        content_type = r.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    if "result" in data or "error" in data:
                        return data
            raise ValueError("No JSON-RPC result in SSE stream")
        return r.json()

    def initialize(self):
        return self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        })

    def send_initialized(self):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        requests.post(
            self.endpoint,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=headers,
            timeout=10,
        )

    def list_tools(self):
        return self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        })

    def call_tool(self, name, arguments=None):
        return self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })


@pytest.fixture(scope="module")
def mcp(mcp_url):
    client = MCPTestClient(mcp_url)
    result = client.initialize()
    assert "result" in result
    client.send_initialized()
    return client


def _tool_text(response):
    """Extract text content from an MCP tools/call response."""
    content = response["result"]["content"]
    return json.loads(content[0]["text"])


# --- Protocol ---


def test_mcp_initialize(mcp_url):
    client = MCPTestClient(mcp_url)
    result = client.initialize()
    assert "result" in result
    assert "serverInfo" in result["result"]
    assert "protocolVersion" in result["result"]


def test_mcp_list_tools(mcp):
    result = mcp.list_tools()
    tools = result["result"]["tools"]
    names = {t["name"] for t in tools}
    expected = {
        "list_entries",
        "get_entry",
        "get_page",
        "get_pages",
        "search_content",
        "semantic_search",
    }
    assert expected == names


# --- Tools ---


def test_mcp_list_entries(mcp, uploaded_entry):
    result = mcp.call_tool("list_entries", {"title": "Integration Test Book"})
    data = _tool_text(result)
    assert "entries" in data
    assert "total" in data
    ids = [e["id"] for e in data["entries"]]
    assert uploaded_entry["entry_id"] in ids


def test_mcp_get_entry(mcp, uploaded_entry):
    result = mcp.call_tool("get_entry", {"entry_id": uploaded_entry["entry_id"]})
    data = _tool_text(result)
    meta = data["metadata"]
    assert meta["title"] == "Integration Test Book"
    assert meta["author"] == "Test Author"
    assert "chapters" in data


def test_mcp_get_entry_not_found(mcp):
    result = mcp.call_tool("get_entry", {"entry_id": "0000000000000000"})
    data = _tool_text(result)
    assert "error" in data


def test_mcp_get_page(mcp, uploaded_entry):
    result = mcp.call_tool(
        "get_page",
        {"entry_id": uploaded_entry["entry_id"], "section": "summary", "page": 1},
    )
    data = _tool_text(result)
    assert data["page_number"] == 1
    assert len(data["content"]) > 0


def test_mcp_get_pages(mcp, uploaded_entry):
    result = mcp.call_tool(
        "get_pages",
        {
            "entry_id": uploaded_entry["entry_id"],
            "section": "fulltext",
            "from_page": 1,
            "to_page": 2,
        },
    )
    data = _tool_text(result)
    assert "pages" in data
    assert len(data["pages"]) >= 1


def test_mcp_search_content(mcp, uploaded_entry):
    result = mcp.call_tool(
        "search_content", {"query": "quantum xylophone orchestration"}
    )
    data = _tool_text(result)
    assert data["total_results"] >= 1
    ids = [r["entry_id"] for r in data["results"]]
    assert uploaded_entry["entry_id"] in ids


@skip_no_ollama
def test_mcp_semantic_search(mcp, uploaded_entry):
    result = mcp.call_tool(
        "semantic_search", {"query": "music and technology", "limit": 5}
    )
    data = _tool_text(result)
    assert isinstance(data["results"], list)
    assert isinstance(data["total_results"], int)
