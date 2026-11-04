#!/usr/bin/env python3
"""Export the production dermatology knowledge base into Android assets.

This runs during development/build preparation only. The resulting Android app
uses local JSON assets and does not call the API at runtime.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://api.medconsults.ai"
PRESENTATIONS = (
    "scaly", "acute", "bulla", "wheal", "purp", "ecz",
    "ann", "pig", "face", "hair", "nod", "hypo",
)
OUTPUT = Path("android/app/src/main/assets/knowledge")


def get_json(url: str):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "MedConsults-Offline-Asset-Exporter/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
    return raw, json.loads(raw.decode("utf-8"))


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": BASE_URL,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "presentations": {},
    }

    # Preserve the bootstrap payload as provenance/context if the endpoint is
    # available; presentation payloads remain the app's authoritative assets.
    try:
        raw, bootstrap = get_json(f"{BASE_URL}/api/knowledge/derm/bootstrap")
        (OUTPUT / "bootstrap.json").write_bytes(raw)
        manifest["bootstrap_sha256"] = hashlib.sha256(raw).hexdigest()
        manifest["bootstrap_keys"] = sorted(bootstrap.keys()) if isinstance(bootstrap, dict) else []
        print("Downloaded bootstrap package.")
    except Exception as exc:
        print(f"WARNING: bootstrap endpoint unavailable: {exc}", file=sys.stderr)

    for presentation_id in PRESENTATIONS:
        url = f"{BASE_URL}/api/knowledge/derm/presentation/{presentation_id}"
        raw, payload = get_json(url)
        if not isinstance(payload, dict):
            raise ValueError(f"{presentation_id}: expected a JSON object")
        if payload.get("id") != presentation_id:
            raise ValueError(
                f"{presentation_id}: response id mismatch ({payload.get('id')!r})"
            )
        for required in ("dx", "find"):
            if not isinstance(payload.get(required), list):
                raise ValueError(f"{presentation_id}: missing required list {required!r}")

        filename = f"presentation_{presentation_id}.json"
        (OUTPUT / filename).write_bytes(raw)
        manifest["presentations"][presentation_id] = {
            "file": filename,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "diagnoses": len(payload["dx"]),
            "findings": len(payload["find"]),
            "tests": len(payload.get("test", [])),
            "context_modifiers": len(payload.get("ctx", [])),
            "urgent_rules": len(payload.get("stop", [])),
        }
        print(
            f"{presentation_id}: {len(payload['dx'])} diagnoses, "
            f"{len(payload['find'])} findings"
        )

    manifest_path = OUTPUT / "knowledge_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Export complete: {len(manifest['presentations'])}/12 presentations.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"EXPORT FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
