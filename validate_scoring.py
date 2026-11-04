
#!/usr/bin/env python3

import csv
import json
import random
import time

from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import scoring


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://api.medconsults.ai"
PRESENTATION_ID = "scaly"

DELAY_SECONDS = 1.5
TIMEOUT_SECONDS = 45

PROBABILITY_TOLERANCE = 1e-8
RESIDUAL_TOLERANCE = 1e-10

OUTPUT_DIR = Path("scoring_validation_output")

RANDOM_SEED = 20261103


# ============================================================
# API REQUEST
# ============================================================

def request_json(url, payload=None):

    headers = {
        "Accept": "application/json",
        "User-Agent": "MedConsults-scoring-validator/1.0",
    }

    data = None

    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    request = Request(
        url,
        data=data,
        headers=headers,
        method="POST" if data is not None else "GET",
    )

    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:

        return json.loads(
            response.read().decode("utf-8")
        )


def fetch_presentation():

    url = (
        f"{BASE_URL}/api/knowledge/derm/presentation/"
        f"{PRESENTATION_ID}"
    )

    print("Fetching presentation configuration...")

    data = request_json(url)

    path = OUTPUT_DIR / f"presentation_{PRESENTATION_ID}.json"

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return scoring.load_presentation(path)


def assess_api(answers):

    payload = {
        "ctx": {
            "presId": PRESENTATION_ID,
            "today": date.today().isoformat(),
            "state": {
                "find": dict(answers),
            },
        },
    }

    return request_json(
        f"{BASE_URL}/api/knowledge/derm/assess",
        payload,
    )


# ============================================================
# TEST CASE GENERATION
# ============================================================

def make_cases(number_of_findings):

    cases = []

    def add(name, answers):

        cases.append({
            "name": name,
            "answers": dict(answers),
        })

    # --------------------------------------------------------
    # 1. Baseline
    # --------------------------------------------------------

    add("baseline", {})

    # --------------------------------------------------------
    # 2. Every finding independently: Yes and No
    # --------------------------------------------------------

    for i in range(number_of_findings):

        add(
            f"single_{i}_yes",
            {f"{PRESENTATION_ID}|{i}": "y"},
        )

        add(
            f"single_{i}_no",
            {f"{PRESENTATION_ID}|{i}": "n"},
        )

    # --------------------------------------------------------
    # 3. Exhaustive two-finding correlation groups
    # --------------------------------------------------------

    pair_groups = [
        (0, 1),
        (10, 11),
        (19, 20),
        (16, 25),
        (13, 29),
        (17, 18),
    ]

    for group_number, (a, b) in enumerate(pair_groups, 1):

        for va in ("y", "n"):

            for vb in ("y", "n"):

                add(
                    f"pair_{group_number}_{a}{va}_{b}{vb}",
                    {
                        f"{PRESENTATION_ID}|{a}": va,
                        f"{PRESENTATION_ID}|{b}": vb,
                    },
                )

    # --------------------------------------------------------
    # 4. Exhaustive three-finding correlation group
    # --------------------------------------------------------

    triple = (7, 8, 9)

    for combination in range(8):

        answers = {}

        for position, index in enumerate(triple):

            value = (
                "y"
                if combination & (1 << position)
                else "n"
            )

            answers[f"{PRESENTATION_ID}|{index}"] = value

        add(
            f"triple_pr_morph_{combination:03d}",
            answers,
        )

    # --------------------------------------------------------
    # 5. Full-answer states
    # --------------------------------------------------------

    add(
        "all_yes",
        {
            f"{PRESENTATION_ID}|{i}": "y"
            for i in range(number_of_findings)
        },
    )

    add(
        "all_no",
        {
            f"{PRESENTATION_ID}|{i}": "n"
            for i in range(number_of_findings)
        },
    )

    add(
        "alternating",
        {
            f"{PRESENTATION_ID}|{i}": (
                "y" if i % 2 == 0 else "n"
            )
            for i in range(number_of_findings)
        },
    )

    # --------------------------------------------------------
    # 6. Reproducible random combinations
    # --------------------------------------------------------

    rng = random.Random(RANDOM_SEED)

    for case_number in range(12):

        count = rng.randint(3, min(15, number_of_findings))

        selected = sorted(
            rng.sample(
                range(number_of_findings),
                count,
            )
        )

        answers = {}

        for index in selected:

            answers[f"{PRESENTATION_ID}|{index}"] = (
                rng.choice(("y", "n"))
            )

        add(
            f"random_{case_number + 1:02d}",
            answers,
        )

    return cases


# ============================================================
# COMPARISON HELPERS
# ============================================================

def compare_case(name, answers, presentation):

    result = {
        "name": name,
        "answers": answers,
        "status": "pending",
        "mismatches": [],
    }

    try:

        api_response = assess_api(answers)

        api_rank = api_response.get("rank") or {}

        api_rows = api_rank.get("rows") or []

        if not api_rows:
            raise ValueError("API returned no ranking rows.")

        local = scoring.score_findings(
            presentation,
            answers,
        )

        api_probabilities = {
            row["id"]: float(row["p"])
            for row in api_rows
        }

        local_probabilities = {
            row["id"]: float(row["probability"])
            for row in local["ranked"]
        }

        # ----------------------------------------------------
        # Diagnosis coverage
        # ----------------------------------------------------

        api_ids = set(api_probabilities)
        local_ids = set(local_probabilities)

        if api_ids != local_ids:

            result["mismatches"].append(
                "Diagnosis ID sets differ."
            )

        # ----------------------------------------------------
        # Individual diagnosis probabilities
        # ----------------------------------------------------

        probability_differences = {}

        for diagnosis_id in sorted(api_ids | local_ids):

            if (
                diagnosis_id not in api_probabilities
                or diagnosis_id not in local_probabilities
            ):
                continue

            difference = (
                local_probabilities[diagnosis_id]
                - api_probabilities[diagnosis_id]
            )

            probability_differences[diagnosis_id] = difference

            if abs(difference) > PROBABILITY_TOLERANCE:

                result["mismatches"].append(
                    f"Probability mismatch: {diagnosis_id}"
                )

        # ----------------------------------------------------
        # Residual probability
        # ----------------------------------------------------

        api_residual = float(api_rank["residual"])

        local_residual = float(local["residual"])

        residual_difference = (
            local_residual - api_residual
        )

        if abs(residual_difference) > RESIDUAL_TOLERANCE:

            result["mismatches"].append(
                "Residual probability mismatch."
            )

        # ----------------------------------------------------
        # Answered count
        # ----------------------------------------------------

        api_answered = api_rank.get("answered")

        local_answered = local["answered"]

        if api_answered != local_answered:

            result["mismatches"].append(
                "Answered finding count mismatch."
            )

        # ----------------------------------------------------
        # Dropped findings
        # ----------------------------------------------------

        api_dropped = api_rank.get("dropped") or []

        local_dropped = local["dropped_findings"]

        api_dropped_indices = sorted(
            item["i"] for item in api_dropped
        )

        local_dropped_indices = sorted(
            item["i"] for item in local_dropped
        )

        if api_dropped_indices != local_dropped_indices:

            result["mismatches"].append(
                "Dropped finding indices differ."
            )

        # ----------------------------------------------------
        # Effective scored count
        # ----------------------------------------------------

        api_scored = (
            api_answered - len(api_dropped)
            if api_answered is not None
            else None
        )

        local_scored = local["scored_findings"]

        if api_scored != local_scored:

            result["mismatches"].append(
                "Effective scored finding count mismatch."
            )

        # ----------------------------------------------------
        # Complete diagnosis ranking
        # ----------------------------------------------------

        api_ranking = [
            row["id"] for row in api_rows
        ]

        local_ranking = [
            row["id"] for row in local["ranked"]
        ]

        if api_ranking != local_ranking:

            result["mismatches"].append(
                "Diagnosis ranking order differs."
            )

        # ----------------------------------------------------
        # Store results
        # ----------------------------------------------------

        result.update({

            "status": (
                "PASS"
                if not result["mismatches"]
                else "FAIL"
            ),

            "api_answered": api_answered,
            "local_answered": local_answered,

            "api_scored": api_scored,
            "local_scored": local_scored,

            "api_dropped": api_dropped_indices,
            "local_dropped": local_dropped_indices,

            "api_residual": api_residual,
            "local_residual": local_residual,

            "residual_difference": residual_difference,

            "api_probability_sum": sum(
                api_probabilities.values()
            ),

            "local_probability_sum": local["probability_sum"],

            "max_probability_difference": max(
                (
                    abs(value)
                    for value in probability_differences.values()
                ),
                default=0.0,
            ),

            "probability_differences": probability_differences,

            "api_ranking": api_ranking,
            "local_ranking": local_ranking,

        })

    except Exception as exc:

        result["status"] = "ERROR"
        result["error"] = repr(exc)

    return result


# ============================================================
# OUTPUT
# ============================================================

def save_results(results):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    json_path = OUTPUT_DIR / "validation_full.json"

    json_path.write_text(
        json.dumps(
            results,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    csv_path = OUTPUT_DIR / "validation_summary.csv"

    columns = [
        "name",
        "status",
        "api_answered",
        "local_answered",
        "api_scored",
        "local_scored",
        "api_residual",
        "local_residual",
        "residual_difference",
        "max_probability_difference",
        "api_probability_sum",
        "local_probability_sum",
        "mismatches",
        "error",
    ]

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            extrasaction="ignore",
        )

        writer.writeheader()

        for result in results:

            row = dict(result)

            row["mismatches"] = json.dumps(
                row.get("mismatches", [])
            )

            writer.writerow(row)

    return json_path, csv_path


# ============================================================
# MAIN
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    presentation = fetch_presentation()

    findings = presentation["find"]

    print("\nPresentation loaded successfully.")
    print("Presentation ID:", presentation["id"])
    print("Findings:", len(findings))
    print("Diagnoses:", len(presentation["dx"]))

    cases = make_cases(len(findings))

    print("\nTotal planned cases:", len(cases))
    print("Delay between API requests:", DELAY_SECONDS, "seconds")

    print("\nStarting API-versus-local validation...\n")

    results = []

    for number, case in enumerate(cases, 1):

        if number > 1:
            time.sleep(DELAY_SECONDS)

        result = compare_case(
            case["name"],
            case["answers"],
            presentation,
        )

        results.append(result)

        print(
            f"[{number:03d}/{len(cases):03d}] "
            f"{result['status']:5s} | "
            f"{case['name']}"
        )

        if result["mismatches"]:

            for mismatch in result["mismatches"]:
                print("    MISMATCH:", mismatch)

        if result.get("error"):

            print("    ERROR:", result["error"])

        # Save progress after every case.
        save_results(results)

    passed = sum(
        result["status"] == "PASS"
        for result in results
    )

    failed = sum(
        result["status"] == "FAIL"
        for result in results
    )

    errors = sum(
        result["status"] == "ERROR"
        for result in results
    )

    json_path, csv_path = save_results(results)

    print("\n" + "=" * 65)
    print("VALIDATION COMPLETE")
    print("=" * 65)

    print("Total cases:", len(results))
    print("Passed:", passed)
    print("Failed:", failed)
    print("Errors:", errors)

    print("\nFull JSON report:")
    print(json_path.resolve())

    print("\nCSV summary:")
    print(csv_path.resolve())

    if failed or errors:

        print("\nReview failed/error cases before accepting the model.")

    else:

        print("\nAll tested cases match the API.")


if __name__ == "__main__":
    main()
