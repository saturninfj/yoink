"""Cookie handling: Netscape cookie file import + in-memory jar."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Cookie:
    """Single HTTP cookie, Netscape-format compatible."""

    domain: str
    name: str
    value: str
    path: str = "/"
    secure: bool = False


def parse_netscape_cookie_file(path: Path) -> list[Cookie]:
    """Parse a Netscape-format cookies.txt file.

    Format spec: https://curl.se/docs/http-cookies.html
    Lines starting with '#' are comments (but '#HttpOnly_' prefix is meaningful).
    """
    if not path.is_file():
        raise FileNotFoundError(f"cookie file not found: {path}")

    cookies: list[Cookie] = []
    min_fields = 7
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue

        # Handle '#HttpOnly_domain' prefix.
        httponly = False
        if line.startswith("#HttpOnly_"):
            httponly = True
            line = line[len("#HttpOnly_") :]

        parts = line.split("\t")
        if len(parts) < min_fields:
            continue

        domain = parts[0]
        domain_flag = parts[1]
        cookie_path = parts[2]
        secure = parts[3].upper() == "TRUE"
        name = parts[5]
        value = parts[6]

        if domain_flag.upper() == "TRUE" and not domain.startswith("."):
            domain = "." + domain

        cookies.append(
            Cookie(
                domain=domain,
                name=name,
                value=value,
                path=cookie_path,
                secure=secure,
            )
        )
        if httponly:
            # HttpOnly is just a flag we ignore for our purposes.
            pass

    return cookies


def cookies_to_header(cookies: list[Cookie], host: str) -> str:
    """Build a Cookie: header for the given host from a list of cookies.

    Includes cookies whose domain matches host (handles leading-dot wildcard).
    """
    matching = [c for c in cookies if _domain_matches(c.domain, host)]
    if not matching:
        return ""
    return "; ".join(f"{c.name}={c.value}" for c in matching)


def _domain_matches(cookie_domain: str, host: str) -> bool:
    """True if cookie_domain matches host per Netscape rules."""
    if cookie_domain.startswith("."):
        return host == cookie_domain[1:] or host.endswith(cookie_domain)
    return host == cookie_domain
