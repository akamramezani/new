#!/usr/bin/env python3
"""Generate Android scorer golden vectors from the Python reference implementation."""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import scoring  # noqa: E402

PRESENTATION_PATH = ROOT / "android/app/src/main/assets/knowledge/presentation_scaly.json"
OUTPUT_PATH = ROOT / "android/app/src/test/resources/scoring_golden_vectors.json"
SEED = 20261105


def make_cases(count):
    cases = []

    def add(name, answers):
        cases.append({"name": name, "answers": {str(k): v for k, v in sorted(answers.items())}})

    add("baseline", {})
    for index in range(count):
        add(f"single_{index}_yes", {index: "y"})
        add(f"single_{index}_no", {index: "n"})

    groups = [(0, 1), (10, 11), (19, 20), (16, 25), (13, 29), (17, 18)]
    for group_index, (a, b) in enumerate(groups, 1):
        for va in ("y", "n"):
            for vb in ("y", "n"):
                add(f"pair_{group_index}_{va}_{vb}", {a: va, b: vb})

    for mask in range(8):
        add("pr_triple_" + str(mask), {
            index: ("y" if mask & (1 << pos) else "n")
            for pos, index in enumerate((7, 8, 9))
        })

    add("all_yes", {i: "y" for i in range(count)})
    add("all_no", {i: "n" for i in range(count)})
    add("alternating", {i: ("y" if i % 2 == 0 else "n") for i in range(count)})

    rng = random.Random(SEED)
    for number in range(20):
        size = rng.randint(3, min(18, count))
        indices = sorted(rng.sample(range(count), size))
        add(f"random_{number + 1:02d}", {i: rng.choice(("y", "n")) for i in indices})
    return cases


def main():
    presentation = scoring.load_presentation(PRESENTATION_PATH)
    cases = make_cases(len(presentation["find"]))
    vectors = []
    for case in cases:
        answers = {f'{presentation["id"]}|{index}': value
                   for index, value in case["answers"].items()}
        result = scoring.score_findings(presentation, answers)
        vectors.append({
            "name": case["name"],
            "answers": case["answers"],
            "expected": {
                "answered": result["answered"],
                "scored": result["scored_findings"],
                "residual": result["residual"],
                "dropped": sorted(item["i"] for item in result["dropped_findings"]),
                "ranked": [{
                    "id": row["id"],
                    "weight": row["weight"],
                    "probability": row["probability"],
                } for row in result["ranked"]],
            },
        })
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({
        "generator": "scoring.py::score_findings",
        "seed": SEED,
        "case_count": len(vectors),
        "cases": vectors,
    }, indent=2), encoding="utf-8")
    print(f"Generated {len(vectors)} Python-reference vectors: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
