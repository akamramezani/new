
import csv
import json
import random
import time
from pathlib import Path

import validate_scoring as base


# ============================================================
# CONFIGURATION
# ============================================================

SEED = 20261103
RANDOM_CASES = 120
DELAY_SECONDS = 1.5

OUTPUT_DIR = Path("multigroup_output")
OUTPUT_DIR.mkdir(exist_ok=True)

JSON_FILE = OUTPUT_DIR / "multigroup_results.json"
CSV_FILE = OUTPUT_DIR / "multigroup_results.csv"

CORRELATED_GROUPS = [
    (0, 1),
    (10, 11),
    (19, 20),
    (16, 25),
    (13, 29),
    (17, 18),
    (7, 8, 9),
]


# ============================================================
# CASE GENERATION
# ============================================================

def make_key(index):
    return f"{base.PRESENTATION_ID}|{index}"


def make_multigroup_cases():

    rng = random.Random(SEED)

    cases = []
    seen = set()

    # --------------------------------------------------------
    # 1. All groups answered Yes
    # --------------------------------------------------------

    answers = {
        make_key(index): "y"
        for group in CORRELATED_GROUPS
        for index in group
    }

    cases.append(("all_groups_all_yes", answers))
    seen.add(tuple(sorted(answers.items())))

    # --------------------------------------------------------
    # 2. All groups answered No
    # --------------------------------------------------------

    answers = {
        make_key(index): "n"
        for group in CORRELATED_GROUPS
        for index in group
    }

    cases.append(("all_groups_all_no", answers))
    seen.add(tuple(sorted(answers.items())))

    # --------------------------------------------------------
    # 3. Alternating answers across all groups
    # --------------------------------------------------------

    indices = sorted({
        index
        for group in CORRELATED_GROUPS
        for index in group
    })

    answers = {
        make_key(index): ("y" if position % 2 == 0 else "n")
        for position, index in enumerate(indices)
    }

    cases.append(("all_groups_alternating", answers))
    seen.add(tuple(sorted(answers.items())))

    # --------------------------------------------------------
    # 4. Random combinations of 2–4 correlated groups
    # --------------------------------------------------------

    attempts = 0
    generated = 0

    while generated < RANDOM_CASES and attempts < RANDOM_CASES * 20:

        attempts += 1

        number_of_groups = rng.randint(2, 4)

        selected_groups = rng.sample(
            CORRELATED_GROUPS,
            number_of_groups
        )

        selected_indices = sorted({
            index
            for group in selected_groups
            for index in group
        })

        answers = {
            make_key(index): rng.choice(["y", "n"])
            for index in selected_indices
        }

        signature = tuple(sorted(answers.items()))

        if signature in seen:
            continue

        seen.add(signature)

        generated += 1

        cases.append((
            f"multigroup_random_{generated:03d}",
            answers
        ))

    if generated < RANDOM_CASES:
        print(
            f"Warning: generated only {generated} "
            f"unique randomized cases."
        )

    return cases


# ============================================================
# MAIN VALIDATION
# ============================================================

def main():

    print("=" * 65)
    print("MEDCONSULTS — MULTI-GROUP INTERACTION VALIDATION")
    print("=" * 65)

    cases = make_multigroup_cases()

    print(f"\nTotal test cases: {len(cases)}")
    print(f"Correlated groups: {len(CORRELATED_GROUPS)}")

    print("\nStarting API comparisons...\n")

    results = []

    passed = 0
    failed = 0
    errors = 0

    start_time = time.time()

    for number, (case_name, answers) in enumerate(cases, start=1):

        try:

            result = base.compare_case(
                case_name,
                answers,
                base.fetch_presentation()
                if False else presentation
            )

            results.append(result)

            status = str(
                result.get("status", "UNKNOWN")
            ).upper()

            if status == "PASS":
                passed += 1

            elif status == "FAIL":
                failed += 1

            else:
                errors += 1

            print(
                f"[{number:03d}/{len(cases):03d}] "
                f"{case_name:<35} {status}"
            )

        except Exception as exc:

            errors += 1

            results.append({
                "case": case_name,
                "status": "ERROR",
                "error": repr(exc),
                "answers": answers,
            })

            print(
                f"[{number:03d}/{len(cases):03d}] "
                f"{case_name:<35} ERROR: {exc}"
            )

        if number < len(cases):
            time.sleep(DELAY_SECONDS)

    elapsed = time.time() - start_time

    # --------------------------------------------------------
    # SAVE JSON
    # --------------------------------------------------------

    metadata = {
        "seed": SEED,
        "correlated_groups": CORRELATED_GROUPS,
        "total_cases": len(cases),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 2),
    }

    with open(JSON_FILE, "w", encoding="utf-8") as file:

        json.dump(
            {
                "metadata": metadata,
                "results": results,
            },
            file,
            indent=2,
            ensure_ascii=False,
            default=str,
        )

    # --------------------------------------------------------
    # SAVE CSV
    # --------------------------------------------------------

    if results:

        fieldnames = sorted({
            key
            for result in results
            for key in result
        })

        with open(
            CSV_FILE,
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames,
                extrasaction="ignore"
            )

            writer.writeheader()

            for result in results:

                row = {}

                for key, value in result.items():

                    if isinstance(value, (dict, list)):
                        row[key] = json.dumps(
                            value,
                            ensure_ascii=False,
                            default=str
                        )
                    else:
                        row[key] = value

                writer.writerow(row)

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print("\n" + "=" * 65)
    print("MULTI-GROUP VALIDATION SUMMARY")
    print("=" * 65)

    print(f"Total cases:       {len(cases)}")
    print(f"PASS:              {passed}")
    print(f"FAIL:              {failed}")
    print(f"ERROR:             {errors}")

    print(
        f"Pass rate:         "
        f"{passed / len(cases) * 100:.2f}%"
    )

    print(f"Runtime:           {elapsed / 60:.2f} minutes")

    print(f"\nJSON: {JSON_FILE.resolve()}")
    print(f"CSV:  {CSV_FILE.resolve()}")

    if failed == 0 and errors == 0:
        print("\nALL MULTI-GROUP TESTS PASSED.")
    else:
        print("\nDISCREPANCIES DETECTED.")

    print("=" * 65)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    presentation = base.fetch_presentation()

    main()
