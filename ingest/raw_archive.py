"""Raw archive layout: raw/<source>/<yyyy>/<mm>/<dd>/<request_hash>.json.gz.

Each file is a gzipped JSON envelope: request metadata (secrets already stripped by the
caller) plus the exact response body, base64-encoded. The archive is append-only:
files are created exclusively and never overwritten. Re-archiving an identical body
under the same key is a no-op; a different body gets a timestamp-suffixed file.
The date partition is the UTC fetch date.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def request_hash(method: str, url: str, params: dict[str, Any] | None) -> str:
    """Stable key for a request (use the secret-stripped url and params)."""
    canon = json.dumps(
        {"method": method.upper(), "url": url, "params": sorted((params or {}).items())},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canon.encode()).hexdigest()[:32]


def _read_body_sha(path: Path) -> str | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f).get("body_sha256")
    except (OSError, ValueError):
        return None


def write_raw(
    root: Path | str,
    source: str,
    fetched_at: datetime,
    request_meta: dict[str, Any],
    status: int,
    response_headers: dict[str, str],
    body: bytes,
) -> Path:
    """Write one response to the raw archive and return its path. Never overwrites."""
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    if not source or "/" in source or source.startswith("."):
        raise ValueError(f"invalid source name {source!r}")
    fetched_at = fetched_at.astimezone(timezone.utc)
    key = request_hash(request_meta["method"], request_meta["url"], request_meta.get("params"))
    day_dir = Path(root) / "raw" / source / fetched_at.strftime("%Y/%m/%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    body_sha = hashlib.sha256(body).hexdigest()
    envelope = {
        "source": source,
        "fetched_at": fetched_at.isoformat(),
        "request": request_meta,
        "status": status,
        "response_headers": response_headers,
        "body_sha256": body_sha,
        "body_b64": base64.b64encode(body).decode("ascii"),
    }
    payload = gzip.compress(json.dumps(envelope, sort_keys=True).encode("utf-8"))

    path = day_dir / f"{key}.json.gz"
    if path.exists():
        if _read_body_sha(path) == body_sha:
            return path
        path = day_dir / f"{key}-{fetched_at.strftime('%Y%m%dT%H%M%S%fZ')}.json.gz"
    with open(path, "xb") as f:
        f.write(payload)
    return path


def read_raw(path: Path | str) -> dict[str, Any]:
    """Load an archived envelope; body is returned decoded as bytes under 'body'."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        env = json.load(f)
    env["body"] = base64.b64decode(env.pop("body_b64"))
    return env
