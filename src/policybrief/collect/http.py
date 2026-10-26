"""수집기 공용 HTTP 클라이언트 설정."""

from __future__ import annotations

import time

import httpx

USER_AGENT = (
    "Mozilla/5.0 (compatible; policybrief/0.1; +https://github.com/JuhwanYoo/publichealth_policy)"
)

DEFAULT_TIMEOUT = httpx.Timeout(25.0, connect=15.0)
RETRIES = 3

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
}


def get_bytes(url: str, timeout: httpx.Timeout = DEFAULT_TIMEOUT) -> bytes:
    """URL을 받아 바이트로 돌려준다 (인코딩 판단은 호출자/feedparser에 맡김).

    일부 공공기관 사이트는 간헐적으로 연결을 끊거나 응답이 늦으므로 전송 오류와 5xx는 몇 번 재시도한다.
    """
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=_HEADERS) as client:
                resp = client.get(url)
                if resp.status_code >= 500 and attempt < RETRIES - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.content
        except (httpx.TransportError,) as exc:   # timeout, 연결 끊김 등
            last = exc
            time.sleep(2 * (attempt + 1))
    assert last is not None
    raise last
