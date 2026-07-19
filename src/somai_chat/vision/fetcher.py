"""Bounded retrieval of public image URLs for visual analysis."""

from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx


class HttpImageFetcher:
    """Fetch HTTP(S) images without redirects or unbounded buffering."""

    def __init__(self, client: httpx.AsyncClient, max_bytes: int) -> None:
        self._client = client
        self._max_bytes = max_bytes

    @staticmethod
    def _allows_uploaded_loopback(url: str) -> bool:
        parsed = urlsplit(url)
        return (
            parsed.hostname in {"127.0.0.1", "localhost", "0.0.0.0"}
            and parsed.path.startswith("/api/v1/images/img_")
        )

    async def fetch(self, url: str) -> tuple[str, bytes]:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("Invalid image URL")
        try:
            address = ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global and not self._allows_uploaded_loopback(url):
            raise ValueError("Private image URL")
        async with self._client.stream("GET", url, follow_redirects=False) as response:
            media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if response.status_code != 200 or media_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise ValueError("Unsupported image response")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > self._max_bytes:
                    raise ValueError("Image response exceeds limit")
                chunks.append(chunk)
        return media_type, b"".join(chunks)
