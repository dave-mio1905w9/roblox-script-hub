import json
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    import httpx
except ImportError as _exc:
    sys.exit(f"missing dependency '{_exc.name}'. run: pip install -r requirements.txt")

API_BASE = "https://apis.roblox.com/cloud/v2"

class RbxError(Exception):
    pass

class RbxClient:
    def __init__(self, token: str):
        self.token = token
        self._client = httpx.Client(timeout=30)

    def _request(self, path: str) -> dict:
        url = f"{API_BASE}{path}"
        headers = {
            "x-api-key": self.token,
            "Content-Type": "application/json",
        }
        # FIXME: Roblox sometimes returns 429 with no Retry-After; back off blindly
        for attempt in range(3):
            r = self._client.get(url, headers=headers)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RbxError(f"rate limited on {path}")

    def _get_universe_id(self, place_id: str) -> str:
        # Roblox exposes universe id via the legacy web api
        r = self._client.get(
            f"https://apis.roblox.com/universes/v1/places/{place_id}/universe",
            headers={"x-api-key": self.token},
        )
        r.raise_for_status()
        data = r.json()
        return str(data["universeId"])

    def fetch_scripts(self, place_id: str) -> list:
        # Open Cloud v2: list place contents via the universe endpoint.
        # We need the universe id first, then enumerate script assets.
        # Roblox returns script metadata without source; source comes
        # from a secondary fetch per script.
        universe_id = self._get_universe_id(place_id)
        universe_url = f"/universes/{universe_id}/places/{place_id}"
        try:
            place_info = self._request(universe_url)
        except RbxError:
            # Fallback: try direct place endpoint
            place_info = self._request(f"/places/{place_id}")

        scripts = []
        # TODO: paginate when Roblox adds nextPageToken support for scripts
        assets = place_info.get("scripts", []) or place_info.get("assets", [])
        for meta in assets:
            script_id = meta.get("scriptId") or meta.get("assetId")
            if not script_id:
                continue
            source = self._fetch_source(script_id)
            scripts.append({
                "scriptId": script_id,
                "name": meta.get("name", "untitled"),
                "scriptType": meta.get("scriptType", "Script"),
                "source": source,
            })
        return scripts

    def _fetch_source(self, script_id: str) -> str:
        # Internal endpoint for Luau source; requires the place-scoped key.
        url = f"{API_BASE}/assets/{script_id}/content"
        headers = {"x-api-key": self.token}
        try:
            r = self._client.get(url, headers=headers)
            r.raise_for_status()
            return r.text
        except httpx.HTTPStatusError as e:
            # print(f"status {e.response.status_code}: {e.response.text[:200]}")  # debug
            return ""
