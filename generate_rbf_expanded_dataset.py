#!/usr/bin/env python3
"""
Expanded RBF zone dataset generator for the scaly presentation.

This script:
- Preserves presentation_scaly.json and scoring.py unchanged.
- Uses all 40 findings, including Finding 21 (index 21).
- Keeps the existing 13/17 factorial design.
- Adds clean factorial, one-finding, correlation-group, and randomized
  interaction backgrounds.
- Uses the existing score_findings() implementation to construct predictors.
- Queries the live API for zone targets and checkpoints every successful call.
- Does not train or tune an RBF model.

Run from the repository root:
    python generate_rbf_expanded_dataset.py --dry-run
    python generate_rbf_expanded_dataset.py

Dependencies:
    pip install numpy requests
"""

import argparse
import hashlib
import json
import random
import time
from datetime import date
from pathlib import Path

import requests

from scoring import load_presentation, score_findings


ROOT = Path(__file__).resolve().parent
PRESENTATION_PATH = ROOT / "presentation_scaly.json"
EXISTING_TRAINING_PATH = ROOT / "targeted_interaction_results.json"
OUTPUT_DIR = ROOT / "zone_validation_output"
CHECKPOINT_PATH = OUTPUT_DIR / "rbf_expanded_dataset_checkpoint.json"
OUTPUT_PATH = OUTPUT_DIR / "targeted_interaction_results_expanded.json"

API_URL = "https://api.medconsults.ai/api/knowledge/derm/assess"
PRESENTATION_ID = "scaly"

SEED = 20261104
RANDOM_BACKGROUND_COUNT = 160
RANDOM_ANSWER_MIN = 5
RANDOM_ANSWER_MAX = 12

FACTORIAL_A = 13
FACTORIAL_B = 17
FACTORIAL_COMBINATIONS = {
    "YY": ("y", "y"),
    "YN": ("y", "n"),
    "NY": ("n", "y"),
    "NN": ("n", "n"),
}

SELECTED_NAMES = [
    "ast", "ldrug", "lp", "mf", "num", "pr",
    "prp", "pso", "reac", "scle", "seb", "syph", "tin",
]

ZONE_NAMES = [
    "abdo", "ankle", "antecub", "axilla", "back",
    "buttock", "calf", "chest", "conj", "ear",
    "elbow", "face", "foot", "forearm", "genital",
    "groin", "hand", "knee", "nail", "neck",
    "oral", "palm", "perianal", "poplit", "scalp",
    "shin", "shoulder", "sole", "thigh", "umbil",
    "web", "wrist",
]

REQUEST_INTERVAL_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 45
MAX_RETRIES = 8
BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 900

# The existing correlation groups are used only for test-design coverage.
# They are NOT changed by this script.
CORRELATION_GROUPS = [
    (0, 1),
    (10, 11),
    (19, 20),
    (16, 25),
    (13, 29),
    (17, 18),
    (7, 8, 9),
]


def answer_key(index):
    return f"{PRESENTATION_ID}|{index}"


def normalize_background(answers):
    """Exclude factorial findings so all four combinations share one hash."""
    normalized = {}
    for key, value in answers.items():
        try:
            index = int(str(key).split("|")[-1])
        except (TypeError, ValueError):
            continue
        if index in (FACTORIAL_A, FACTORIAL_B):
            continue
        if value in ("y", "n"):
            normalized[index] = value
    return normalized


def background_hash(answers):
    canonical = json.dumps(
        sorted(normalize_background(answers).items()),
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_existing_hashes():
    if not EXISTING_TRAINING_PATH.exists():
        return set()

    with EXISTING_TRAINING_PATH.open("r", encoding="utf-8") as handle:
        records = json.load(handle)

    if not isinstance(records, list):
        raise ValueError("Existing training file must contain a JSON list.")

    return {
        background_hash(record.get("answers", {}))
        for record in records
    }


def add_background(collection, seen, answers, source_case):
    """Add one unique non-factorial background."""
    clean = {
        int(index): value
        for index, value in answers.items()
        if value in ("y", "n")
        and int(index) not in (FACTORIAL_A, FACTORIAL_B)
    }

    digest = background_hash({
        answer_key(i): value for i, value in clean.items()
    })

    if digest in seen:
        return False

    seen.add(digest)
    collection.append({
        "background_id": f"expanded_{len(collection) + 1:04d}",
        "source_case": source_case,
        "answers": {
            answer_key(i): clean[i]
            for i in sorted(clean)
        },
        "background_hash": digest,
    })
    return True


def generate_group_cases(collection, seen):
    """Enumerate all answer patterns within each existing correlation group."""
    for group_number, group in enumerate(CORRELATION_GROUPS, start=1):
        number_of_patterns = 2 ** len(group)

        for mask in range(number_of_patterns):
            answers = {}
            for position, index in enumerate(group):
                answers[index] = (
                    "y" if (mask >> position) & 1 else "n"
                )

            add_background(
                collection,
                seen,
                answers,
                f"correlation_group_{group_number}_pattern_{mask:02d}",
            )


def generate_backgrounds(finding_count, existing_hashes):
    if finding_count != 40:
        raise ValueError(
            f"Expected 40 findings in presentation_scaly.json; got {finding_count}."
        )

    rng = random.Random(SEED)
    collection = []
    seen = set(existing_hashes)

    eligible = [
        i for i in range(finding_count)
        if i not in (FACTORIAL_A, FACTORIAL_B)
    ]

    # 1. Clean factorial background: no other findings are answered.
    add_background(
        collection, seen, {},
        "clean_factorial_anchor",
    )

    # 2. One-finding backgrounds: both Yes and No for every non-factorial
    #    finding. This includes Finding 21 (index 21).
    for index in eligible:
        for value in ("y", "n"):
            add_background(
                collection,
                seen,
                {index: value},
                f"single_finding_{index}_{value}",
            )

    # 3. Exhaustive patterns within each existing correlation group.
    #    These test the current correlation selection behavior without
    #    changing any correlation rule.
    generate_group_cases(collection, seen)

    # 4. Randomized sparse interaction backgrounds, with approximate
    #    balance of Yes/No answers for each finding.
    yes_count = {i: 0 for i in eligible}
    no_count = {i: 0 for i in eligible}
    accepted = 0
    attempts = 0
    max_attempts = RANDOM_BACKGROUND_COUNT * 100

    while accepted < RANDOM_BACKGROUND_COUNT and attempts < max_attempts:
        attempts += 1
        n_answered = rng.randint(
            RANDOM_ANSWER_MIN,
            RANDOM_ANSWER_MAX,
        )

        # Prefer less frequently sampled findings to improve coverage.
        ordered = sorted(
            eligible,
            key=lambda i: (
                yes_count[i] + no_count[i],
                abs(yes_count[i] - no_count[i]),
                rng.random(),
            ),
        )

        pool_size = min(len(ordered), max(n_answered * 2, n_answered))
        selected = rng.sample(ordered[:pool_size], n_answered)

        answers = {}
        for index in selected:
            if yes_count[index] < no_count[index]:
                value = "y"
            elif no_count[index] < yes_count[index]:
                value = "n"
            else:
                value = rng.choice(("y", "n"))

            # Small random perturbation avoids deterministic answer balance.
            if rng.random() < 0.10:
                value = "n" if value == "y" else "y"

            answers[index] = value

        before = len(collection)
        added = add_background(
            collection,
            seen,
            answers,
            f"random_interaction_{accepted + 1:03d}",
        )

        if added:
            accepted += 1
            for index, value in answers.items():
                if value == "y":
                    yes_count[index] += 1
                else:
                    no_count[index] += 1

    if accepted != RANDOM_BACKGROUND_COUNT:
        raise RuntimeError(
            f"Generated only {accepted}/{RANDOM_BACKGROUND_COUNT} "
            "random backgrounds."
        )

    return collection


def make_full_answers(background_answers, combination):
    answers = dict(background_answers)
    value_a, value_b = FACTORIAL_COMBINATIONS[combination]
    answers[answer_key(FACTORIAL_A)] = value_a
    answers[answer_key(FACTORIAL_B)] = value_b
    return answers


def reconstruct_predictors(presentation, answers):
    result = score_findings(presentation, answers)

    probability_map = {
        row["id"]: float(row["probability"])
        for row in result["ranked"]
    }

    missing = [
        diagnosis for diagnosis in SELECTED_NAMES
        if diagnosis not in probability_map
    ]
    if missing:
        raise ValueError(
            f"Missing selected diagnosis predictors: {missing}"
        )

    predictors = [probability_map[name] for name in SELECTED_NAMES]

    if any(not (value == value and abs(value) != float("inf"))
           for value in predictors):
        raise ValueError("Non-finite predictor encountered.")

    return predictors, result


def extract_api_zones(payload):
    zones = payload.get("zones")
    if not isinstance(zones, dict):
        raise ValueError(
            "API response does not contain a top-level zones dictionary."
        )

    missing = [zone for zone in ZONE_NAMES if zone not in zones]
    if missing:
        raise ValueError(f"API response is missing zones: {missing}")

    values = {zone: float(zones[zone]) for zone in ZONE_NAMES}
    if any(not (value == value and abs(value) != float("inf"))
           for value in values.values()):
        raise ValueError("API returned non-finite zone values.")

    return values


def query_api(session, answers):
    payload = {
        "ctx": {
            "presId": PRESENTATION_ID,
            "today": date.today().isoformat(),
            "state": {"find": dict(answers)},
        }
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = session.post(
                API_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = min(
                BASE_BACKOFF_SECONDS * (2 ** attempt),
                MAX_BACKOFF_SECONDS,
            )
            print(f"Connection error; retrying in {wait}s.")
            time.sleep(wait)
            continue

        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_RETRIES - 1:
                response.raise_for_status()

            retry_after = response.headers.get("Retry-After")
            try:
                server_wait = float(retry_after)
            except (TypeError, ValueError):
                server_wait = 0

            wait = max(
                server_wait,
                min(
                    BASE_BACKOFF_SECONDS * (2 ** attempt),
                    MAX_BACKOFF_SECONDS,
                ),
            )
            print(
                f"HTTP {response.status_code}; retrying in {wait:.0f}s."
            )
            time.sleep(wait)
            continue

        response.raise_for_status()
        return response.json()

    raise RuntimeError("API request failed after all retry attempts.")


def save_checkpoint(backgrounds, records):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "design_version": "rbf_expanded_all40_v1",
        "seed": SEED,
        "random_background_count": RANDOM_BACKGROUND_COUNT,
        "factorial_findings": [FACTORIAL_A, FACTORIAL_B],
        "background_definitions": backgrounds,
        "records": records,
    }

    temporary = CHECKPOINT_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(CHECKPOINT_PATH)


def load_checkpoint():
    if not CHECKPOINT_PATH.exists():
        return None

    payload = json.loads(
        CHECKPOINT_PATH.read_text(encoding="utf-8")
    )

    expected = {
        "design_version": "rbf_expanded_all40_v1",
        "seed": SEED,
        "random_background_count": RANDOM_BACKGROUND_COUNT,
        "factorial_findings": [FACTORIAL_A, FACTORIAL_B],
    }

    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(
                f"Checkpoint mismatch for {key}; do not reuse it."
            )

    return payload


def validate_design(backgrounds, finding_count):
    if not backgrounds:
        raise ValueError("No backgrounds generated.")

    seen = set()
    for background in backgrounds:
        answers = background["answers"]
        digest = background_hash(answers)

        if digest in seen:
            raise ValueError("Duplicate background hash in generated design.")
        seen.add(digest)

        for key, value in answers.items():
            index = int(key.split("|")[-1])
            if not 0 <= index < finding_count:
                raise ValueError(f"Invalid finding index: {index}")
            if index in (FACTORIAL_A, FACTORIAL_B):
                raise ValueError(
                    "Factorial findings must not be embedded in backgrounds."
                )
            if value not in ("y", "n"):
                raise ValueError(f"Invalid answer value: {value}")

    # Confirm every non-factorial finding appears in both answer states
    # in the one-finding anchor cases.
    for index in range(finding_count):
        if index in (FACTORIAL_A, FACTORIAL_B):
            continue
        for value in ("y", "n"):
            expected = f"single_finding_{index}_{value}"
            if not any(b["source_case"] == expected for b in backgrounds):
                raise ValueError(f"Missing anchor case: {expected}")

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and validate the design without calling the API.",
    )
    parser.add_argument(
        "--request-limit",
        type=int,
        default=None,
        help="Optional cap on new API requests for a staged pilot.",
    )
    args = parser.parse_args()

    if not PRESENTATION_PATH.exists():
        raise FileNotFoundError(PRESENTATION_PATH)

    presentation = load_presentation(str(PRESENTATION_PATH))
    if presentation.get("id") != PRESENTATION_ID:
        raise ValueError("Unexpected presentation ID.")

    finding_count = len(presentation["find"])
    existing_hashes = load_existing_hashes()

    checkpoint = load_checkpoint()
    if checkpoint:
        backgrounds = checkpoint["background_definitions"]
        records = checkpoint["records"]
        print(
            f"Resuming checkpoint: {len(backgrounds)} backgrounds, "
            f"{len(records)} completed observations."
        )
    else:
        backgrounds = generate_backgrounds(
            finding_count,
            existing_hashes,
        )
        validate_design(backgrounds, finding_count)
        records = []
        save_checkpoint(backgrounds, records)

    validate_design(backgrounds, finding_count)

    expected_observations = len(backgrounds) * len(FACTORIAL_COMBINATIONS)
    completed = {
        (row["background_id"], row["combination"])
        for row in records
    }

    print("=" * 72)
    print("EXPANDED SCALY RBF DATASET")
    print("=" * 72)
    print("Findings:", finding_count)
    print("Backgrounds:", len(backgrounds))
    print("Factorial combinations per background:", 4)
    print("Expected API observations:", expected_observations)
    print("Completed observations:", len(completed))
    print("Remaining observations:", expected_observations - len(completed))
    print("Existing training hashes excluded:", len(existing_hashes))
    print("Finding 21 included in single-finding anchors: yes")
    print("Correlation groups changed: no")
    print("Finding 21 added to a correlation group: no")

    if args.dry_run:
        print("\nDRY RUN: no API calls were made.")
        return

    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
    })

    new_requests = 0

    for background in backgrounds:
        for combination in FACTORIAL_COMBINATIONS:
            key = (background["background_id"], combination)
            if key in completed:
                continue

            if (
                args.request_limit is not None
                and new_requests >= args.request_limit
            ):
                print("Request limit reached; checkpoint is saved.")
                return

            answers = make_full_answers(
                background["answers"],
                combination,
            )

            api_payload = query_api(session, answers)
            zones = extract_api_zones(api_payload)
            predictors, scoring_result = reconstruct_predictors(
                presentation,
                answers,
            )

            retained = [
                item["index"]
                for item in scoring_result["findings"]
            ]
            dropped = [
                item["i"]
                for item in scoring_result["dropped_findings"]
            ]

            record = {
                "background_id": background["background_id"],
                "source_case": background["source_case"],
                "background_hash": background["background_hash"],
                "combination": combination,
                "answers": answers,
                "predictors": predictors,
                "retained_findings": retained,
                "dropped_findings": dropped,
                "zones": zones,
                "back": zones["back"],
            }

            records.append(record)
            completed.add(key)
            new_requests += 1

            # Save immediately after every successful API response.
            save_checkpoint(backgrounds, records)

            print(
                f"[{len(completed):04d}/{expected_observations:04d}] "
                f"{background['background_id']} {combination} "
                f"retained={len(retained)} dropped={len(dropped)}"
            )

            time.sleep(REQUEST_INTERVAL_SECONDS)

    # Write a flat list compatible with the existing training-record format.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nDataset generation complete.")
    print("Records:", len(records))
    print("Output:", OUTPUT_PATH)
    print("Checkpoint:", CHECKPOINT_PATH)
    print(
        "\nDo not replace the existing training file. "
        "Keep this expanded dataset separate until grouped validation "
        "and data-quality checks are complete."
    )


if __name__ == "__main__":
    main()
