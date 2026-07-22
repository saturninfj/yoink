"""Unit tests for auth.cookies and core.retry."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoink.auth.cookies import (
    Cookie,
    cookies_to_header,
    parse_netscape_cookie_file,
)
from yoink.core.retry import (
    MaxRetriesExceededError,
    RetryPolicy,
    backoff_delay,
    retry_async,
)

# ------------------------- cookies -------------------------


def test_parse_netscape_cookie_file(tmp_path: Path) -> None:
    cookies_txt = tmp_path / "cookies.txt"
    cookies_txt.write_text(
        """# Netscape HTTP Cookie File
.example.com\tTRUE\t/\tFALSE\t9999999999\tsession\tabc123
api.site.com\tFALSE\t/\tTRUE\t9999999999\ttoken\txyz
#HttpOnly_.host.org\tTRUE\t/\tTRUE\t9999999999\thttp_only_cookie\tval
"""
    )
    cookies = parse_netscape_cookie_file(cookies_txt)
    assert len(cookies) == 3

    assert cookies[0].domain == ".example.com"
    assert cookies[0].name == "session"
    assert cookies[0].value == "abc123"
    assert cookies[0].secure is False

    assert cookies[1].domain == "api.site.com"
    assert cookies[1].secure is True

    # HttpOnly prefix stripped.
    assert cookies[2].domain == ".host.org"
    assert cookies[2].name == "http_only_cookie"


def test_cookies_to_header_matches_domain() -> None:
    cookies = [
        # Exact match.
        _cookie("api.example.com", "a", "1"),
        # Dot-domain matches subdomains.
        _cookie(".example.com", "b", "2"),
        # Unrelated domain.
        _cookie("other.com", "c", "3"),
    ]
    header = cookies_to_header(cookies, "api.example.com")
    # Should include a=1 and b=2.
    assert "a=1" in header
    assert "b=2" in header
    assert "c=3" not in header

    header_sub = cookies_to_header(cookies, "sub.example.com")
    # Subdomain only matches the dot-domain cookie.
    assert "a=1" not in header_sub
    assert "b=2" in header_sub


def _cookie(domain: str, name: str, value: str) -> Cookie:
    return Cookie(domain=domain, name=name, value=value)


# ------------------------- retry -------------------------


def test_backoff_delay_grows_then_caps() -> None:
    policy = RetryPolicy(max_retries=10, initial_delay=1.0, max_delay=20.0, jitter=0.0)
    delays = [backoff_delay(i, policy) for i in range(1, 8)]
    # 1, 2, 4, 8, 16, 20, 20 (capped).
    assert delays[0] == 1.0
    assert delays[1] == 2.0
    assert delays[2] == 4.0
    assert delays[3] == 8.0
    assert delays[4] == 16.0
    assert delays[5] == 20.0
    assert delays[6] == 20.0


@pytest.mark.asyncio
async def test_retry_async_succeeds_after_retries() -> None:
    """Succeed after 2 failures, max_retries=5 → no exception raised."""
    counter = {"n": 0}

    async def flaky() -> None:
        counter["n"] += 1
        if counter["n"] < 3:
            raise ValueError("transient")

    policy = RetryPolicy(max_retries=5, initial_delay=0.001, jitter=0.0)
    await retry_async(flaky, policy=policy, retry_on=ValueError)
    assert counter["n"] == 3


@pytest.mark.asyncio
async def test_retry_async_raises_after_max() -> None:
    """Exhaust retries → MaxRetriesExceededError."""

    async def always_fail() -> None:
        raise RuntimeError("boom")

    policy = RetryPolicy(max_retries=2, initial_delay=0.001, jitter=0.0)
    with pytest.raises(MaxRetriesExceededError):
        await retry_async(always_fail, policy=policy, retry_on=RuntimeError)
