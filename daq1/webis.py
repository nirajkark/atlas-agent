"""Minimal read-only client for Webis (IS over HTTP).

URL scheme (same as ATLAS.js loadInfo):
    /info/current/<partition>/is/<server>/<server>.<object>?format=json

Webis returns an IS object as a JSON array:
    [ "<server>.<object>", "<IS type>", "<DD/MM/YY HH:MM:SS.us>", {attr}, {attr}, ... ]
where each attr is {"name", "descr", "type", "range", "value"}.

Rule: never invent values. Any failure raises WebisError; nothing is defaulted.
"""

import os
from urllib.parse import quote

import httpx

WEBIS_URL = os.environ.get("WEBIS_URL", "http://127.0.0.1:8080")


class WebisError(Exception):
    """Webis could not deliver the requested data. `code` is machine-readable."""

    def __init__(self, code: str, description: str, url: str):
        super().__init__(f"{code}: {description} ({url})")
        self.code = code
        self.description = description
        self.url = url


def object_url(partition: str, server: str, obj: str) -> str:
    # quote() keeps ':' and '.' readable but escapes spaces etc.
    path = f"/info/current/{partition}/is/{server}/{server}.{obj}"
    return WEBIS_URL + quote(path, safe="/:.-_")


def parse_object(raw: list) -> dict:
    """Turn Webis's array format into a dict. Attributes are read by NAME."""
    if not isinstance(raw, list) or len(raw) < 3:
        raise ValueError(f"unexpected Webis object format: {str(raw)[:200]}")
    name, is_type, updated, *attrs = raw
    return {
        "name": name,
        "type": is_type,
        "updated": updated,  # as reported by IS; time zone not specified
        "attributes": {a["name"]: a["value"] for a in attrs},
    }


def get_object(partition: str, server: str, obj: str, timeout: float = 5.0) -> dict:
    """Fetch one IS object. Raises WebisError on any failure."""
    url = object_url(partition, server, obj)
    try:
        r = httpx.get(url, params={"format": "json"}, timeout=timeout)
    except httpx.HTTPError as e:
        raise WebisError("unreachable", f"cannot reach Webis: {e}", url) from e

    if r.status_code != 200:
        # Webis sends {"error": ..., "error_description": ...} on failure (seen: 404 invalid_object)
        try:
            body = r.json()
            raise WebisError(body.get("error", f"http_{r.status_code}"),
                             body.get("error_description", r.text[:200]), url)
        except ValueError:  # body was not JSON
            raise WebisError(f"http_{r.status_code}", r.text[:200], url)

    try:
        result = parse_object(r.json())
    except ValueError as e:
        raise WebisError("bad_response", str(e), url) from e
    result["source"] = url
    return result
