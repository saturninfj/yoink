"""Resume validator: ensures server-side file hasn't changed since last checkpoint."""

from __future__ import annotations

from dataclasses import dataclass

from yoink.core.http_client import ResponseInfo
from yoink.exceptions import ResumeMismatchError


@dataclass(frozen=True)
class ResumeValidation:
    """Result of comparing persisted metadata vs fresh HEAD."""

    ok: bool
    reason: str = ""


def validate_resume(
    fresh: ResponseInfo,
    stored_etag: str | None,
    stored_last_modified: str | None,
) -> ResumeValidation:
    """Compare fresh HEAD probe against persisted ETag/Last-Modified.

    If server sends ETag, prefer it. Otherwise fall back to Last-Modified.
    If neither persisted nor fresh has identifiers, assume ok (best-effort).
    """
    if fresh.etag and stored_etag:
        if fresh.etag != stored_etag:
            return ResumeValidation(
                ok=False,
                reason=f"ETag changed: {stored_etag!r} → {fresh.etag!r}",
            )
        return ResumeValidation(ok=True, reason="ETag match")

    if fresh.last_modified and stored_last_modified:
        if fresh.last_modified != stored_last_modified:
            return ResumeValidation(
                ok=False,
                reason=(
                    f"Last-Modified changed: {stored_last_modified!r} → {fresh.last_modified!r}"
                ),
            )
        return ResumeValidation(ok=True, reason="Last-Modified match")

    # Neither side has usable identifier. Best-effort resume.
    return ResumeValidation(
        ok=True,
        reason="no server-side identifier, resuming best-effort",
    )


def assert_resumable(
    fresh: ResponseInfo,
    stored_etag: str | None,
    stored_last_modified: str | None,
) -> None:
    """Validate or raise ResumeMismatchError."""
    result = validate_resume(fresh, stored_etag, stored_last_modified)
    if not result.ok:
        raise ResumeMismatchError(result.reason)
