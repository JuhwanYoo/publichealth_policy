"""수집기 공용 HTTP 클라이언트 설정."""

from __future__ import annotations

import httpx

USER_AGENT = (
    "Mozilla/5.0 (compatible; policybrief/0.1; +https://github.com/JuhwanYoo/publichealth_policy)"
)

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def get_bytes(url: str, timeout: httpx.Timeout = DEFAULT_TIMEOUT) -> bytes:
    """URL을 받아 바이트로 돌려준다 (인코딩 판단은 호출자/feedparser에 맡김)."""
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content
