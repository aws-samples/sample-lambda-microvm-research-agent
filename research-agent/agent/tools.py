"""Agent tools: web browsing and search capabilities."""
import ipaddress
import json
import logging
import os
import socket
from urllib.parse import urlparse

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Blocked IP ranges to prevent SSRF against internal networks
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "[::1]"}  # nosec B104

_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Max content length to prevent memory exhaustion
_MAX_CONTENT_LENGTH = 10_000_000  # 10MB


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private, loopback, or link-local."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return True  # If we can't parse it, block it


def _is_safe_url(url: str) -> bool:
    """Validate URL to prevent SSRF attacks against internal resources.

    Performs both hostname checks and DNS resolution to block
    domains that resolve to internal IPs.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        if not hostname:
            return False
        if hostname in _BLOCKED_HOSTS:
            return False

        # Resolve DNS and check the actual IP
        resolved_ips = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
        for family, type_, proto, canonname, sockaddr in resolved_ips:
            ip_str = sockaddr[0]
            if _is_private_ip(ip_str):
                logger.warning(f"Blocked URL {url}: resolves to private IP {ip_str}")
                return False

        return True
    except (socket.gaierror, OSError) as e:
        logger.warning(f"DNS resolution failed for {url}: {e}")
        return False
    except Exception:
        return False


def browse_url(url: str) -> str:
    """Load a page and extract text content.

    Uses requests + BeautifulSoup for content extraction.
    Validates URL to prevent SSRF attacks.
    """
    if not _is_safe_url(url):
        logger.warning(f"Blocked unsafe URL: {url}")
        return "Error: URL is not allowed (internal/private address or invalid scheme)."

    logger.info(f"Browsing: {url}")
    try:
        response = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "ResearchAgent/1.0"},
        )
        response.raise_for_status()

        if len(response.content) > _MAX_CONTENT_LENGTH:
            return "Error: Response too large."

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:5000]
    except Exception as e:
        logger.error(f"Browse failed: {e}")
        return f"Error browsing {url}: {e}"


def search_web(query: str) -> "list[dict]":
    """Search the web using Amazon Bedrock AgentCore Web Search via MCP.

    Sends a SigV4-signed request to the AgentCore Gateway endpoint.
    Requires AGENTCORE_GATEWAY_URL env var set to your gateway's MCP URL.
    """
    # Input validation
    if not query or not query.strip():
        return [{"error": "Search query cannot be empty"}]
    query = query.strip()[:500]  # Cap query length

    logger.info(f"Searching: {query}")
    try:
        gateway_url = os.environ.get("AGENTCORE_GATEWAY_URL", "")
        if not gateway_url:
            return [{"error": "AGENTCORE_GATEWAY_URL environment variable not set"}]

        # Validate gateway URL points to expected AWS domain
        parsed_gw = urlparse(gateway_url)
        if not parsed_gw.hostname or not parsed_gw.hostname.endswith(
            ".gateway.bedrock-agentcore.amazonaws.com"
        ):
            return [{"error": "Invalid gateway URL — must be an AgentCore endpoint"}]

        session = boto3.Session(region_name=_AWS_REGION)
        credentials = session.get_credentials().get_frozen_credentials()

        # MCP tools/call payload for WebSearchTool
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "WebSearchTool",
                "arguments": {"query": query}
            },
            "id": "1"
        })

        # Sign the request with SigV4
        aws_request = AWSRequest(
            method="POST",
            url=gateway_url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        SigV4Auth(credentials, "bedrock-agentcore", _AWS_REGION).add_auth(aws_request)

        response = requests.post(
            aws_request.url,
            headers=dict(aws_request.headers),
            data=payload,
            timeout=15,
        )
        response.raise_for_status()

        result = response.json()
        content = result.get("result", {}).get("content", [])

        for block in content:
            if block.get("type") == "text":
                data = json.loads(block["text"])
                results = data.get("results", [])
                return [
                    {
                        "title": r.get("title", "")[:200],
                        "url": r.get("url", "")[:500],
                        "snippet": r.get("text", "")[:1000],
                    }
                    for r in results[:5]
                ]
        return []
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return [{"error": str(e)}]


def extract_content(html: str) -> str:
    """Extract readable text from raw HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:5000]
