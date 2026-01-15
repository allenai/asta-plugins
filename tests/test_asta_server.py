"""Tests for the asta MCP server connectivity."""

import requests


def test_asta_endpoint_responds():
    """Verify asta MCP endpoint is reachable and responds."""
    response = requests.post(
        "https://asta-tools.apps.allenai.org/mcp/v1",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )
    response.raise_for_status()

    # Parse SSE response
    data = response.text
    assert "tools" in data, f"Expected 'tools' in response, got: {data[:200]}"
    print("✓ Asta MCP endpoint responds correctly")


def test_asta_tool_call():
    """Verify a simple tool call works."""
    response = requests.post(
        "https://asta-tools.apps.allenai.org/mcp/v1",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "get_paper",
                "arguments": {"paper_id": "ARXIV:1706.03762", "fields": "title"},
            },
            "id": 2,
        },
    )
    response.raise_for_status()

    data = response.text
    assert "Attention" in data, f"Expected 'Attention' in response, got: {data[:200]}"
    print("✓ Asta tool call works (fetched 'Attention is All You Need')")


if __name__ == "__main__":
    test_asta_endpoint_responds()
    test_asta_tool_call()
    print("\nAll tests passed!")
