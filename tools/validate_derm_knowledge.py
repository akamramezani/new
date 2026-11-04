#!/usr/bin/env python3
"""Validate the bundled dermatology knowledge packages before an Android build."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "android/app/src/main/assets/knowledge"


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def load_json(path: Path, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(errors, f"{path.name}: invalid JSON: {exc}")
        return None


def validate() -> int:
    errors: list[str] = []
    manifest_path = ASSETS / "knowledge_manifest.json"
    bootstrap_path = ASSETS / "bootstrap.json"
    manifest = load_json(manifest_path, errors)
    bootstrap = load_json(bootstrap_path, errors)
    if not isinstance(manifest, dict) or not isinstance(bootstrap, dict):
        print("\n".join(errors))
        return 1

    expected = {item.get("id") for item in bootstrap.get("pres", []) if isinstance(item, dict)}
    entries = manifest.get("presentations", {})
    if not isinstance(entries, dict):
        fail(errors, "Manifest presentations must be an object.")
        entries = {}
    if expected != set(entries):
        fail(errors, f"Bootstrap/manifest presentation mismatch: bootstrap={sorted(expected)}, manifest={sorted(entries)}")

    totals = {key: 0 for key in ("diagnoses", "findings", "tests", "context_modifiers", "urgent_rules")}
    for pid in sorted(expected | set(entries)):
        entry = entries.get(pid, {})
        filename = entry.get("file", f"presentation_{pid}.json") if isinstance(entry, dict) else f"presentation_{pid}.json"
        path = ASSETS / filename
        if not path.is_file():
            fail(errors, f"{pid}: missing asset {filename}")
            continue
        raw = path.read_bytes()
        if isinstance(entry, dict) and entry.get("sha256"):
            digest = hashlib.sha256(raw).hexdigest()
            if digest != entry["sha256"]:
                fail(errors, f"{pid}: SHA256 mismatch")
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            fail(errors, f"{pid}: invalid JSON: {exc}")
            continue
        if not isinstance(data, dict) or data.get("id") != pid:
            fail(errors, f"{pid}: payload ID does not match filename/manifest")
            continue

        arrays = {"dx": "diagnoses", "find": "findings", "test": "tests", "ctx": "context_modifiers", "stop": "urgent_rules"}
        for key, total_key in arrays.items():
            if not isinstance(data.get(key, []), list):
                fail(errors, f"{pid}: {key} must be an array")
                data[key] = []
            totals[total_key] += len(data[key])

        dx = data["dx"]
        find = data["find"]
        dx_ids = [d.get("id") for d in dx if isinstance(d, dict)]
        dx_set = set(dx_ids)
        if len(dx_ids) != len(dx) or any(not isinstance(x, str) or not x for x in dx_ids):
            fail(errors, f"{pid}: every diagnosis needs a non-empty string ID")
        if len(dx_set) != len(dx_ids):
            fail(errors, f"{pid}: duplicate diagnosis IDs")
        for i, d in enumerate(dx):
            if not isinstance(d, dict):
                fail(errors, f"{pid}: diagnosis {i} is not an object")
                continue
            base = d.get("base")
            if not isinstance(base, (int, float)) or not math.isfinite(base) or base <= 0:
                fail(errors, f"{pid}: diagnosis {i} has invalid base weight")

        for i, f in enumerate(find):
            if not isinstance(f, dict) or not isinstance(f.get("l"), str) or not f["l"].strip():
                fail(errors, f"{pid}: finding {i} needs a label")
                continue
            factors = f.get("f", {})
            if not isinstance(factors, dict):
                fail(errors, f"{pid}: finding {i} factors must be an object")
                continue
            for dx_id, pair in factors.items():
                if dx_id not in dx_set:
                    fail(errors, f"{pid}: finding {i} references unknown diagnosis {dx_id}")
                if not isinstance(pair, list) or len(pair) != 2 or any(
                    not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in pair
                ):
                    fail(errors, f"{pid}: finding {i} has invalid yes/no factor for {dx_id}")

        for i, test in enumerate(data["test"]):
            if not isinstance(test, dict) or not isinstance(test.get("l"), str) or not test["l"].strip():
                fail(errors, f"{pid}: test {i} needs a label")
                continue
            target = test.get("tgt")
            if target and target not in dx_set:
                fail(errors, f"{pid}: test {i} references unknown target diagnosis {target}")
            for field in ("se", "sp"):
                value = test.get(field)
                if value is not None and (
                    not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100
                ):
                    fail(errors, f"{pid}: test {i} has invalid {field} percentage")

        for i, context in enumerate(data["ctx"]):
            if not isinstance(context, dict) or not isinstance(context.get("l"), str):
                fail(errors, f"{pid}: context modifier {i} needs a label")
                continue
            age = context.get("age")
            if age is not None and (
                not isinstance(age, list) or len(age) != 2 or
                any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in age) or age[0] > age[1]
            ):
                fail(errors, f"{pid}: context modifier {i} has invalid age range")
            multipliers = context.get("m", {})
            if not isinstance(multipliers, dict):
                fail(errors, f"{pid}: context modifier {i} multipliers must be an object")
                continue
            for dx_id, value in multipliers.items():
                if dx_id not in dx_set:
                    fail(errors, f"{pid}: context modifier {i} references unknown diagnosis {dx_id}")
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    fail(errors, f"{pid}: context modifier {i} has invalid multiplier for {dx_id}")

        for i, rule in enumerate(data["stop"]):
            if not isinstance(rule, dict) or not isinstance(rule.get("l"), str) or not isinstance(rule.get("a"), str):
                fail(errors, f"{pid}: escalation rule {i} needs label and action")

        expected_counts = {
            "diagnoses": len(data["dx"]), "findings": len(data["find"]),
            "tests": len(data["test"]), "context_modifiers": len(data["ctx"]),
            "urgent_rules": len(data["stop"]),
        }
        if isinstance(entry, dict):
            for key, actual in expected_counts.items():
                if entry.get(key) != actual:
                    fail(errors, f"{pid}: manifest {key}={entry.get(key)} but payload has {actual}")
        print(f"OK {pid}: {len(dx)} diagnoses, {len(find)} findings, {len(data['test'])} tests")

    if errors:
        print("\nKNOWLEDGE VALIDATION FAILED:")
        for error in errors:
            print(" - " + error)
        return 1

    print("\nValidated 12 presentation packages.")
    print("Totals: " + ", ".join(f"{key}={value}" for key, value in totals.items()))
    return 0


if __name__ == "__main__":
    sys.exit(validate())
