#!/usr/bin/env python3
"""Paired background-cluster bootstrap for expanded zone-model OOF errors.

This is a post-hoc uncertainty analysis of the already generated outer-fold
out-of-fold predictions. It does not retrain models and does not replace
nested CV. Resampling unit is background_id, preserving all four factorial
records from each background together.

Run:
    pip install numpy
    python analyze_rbf_cluster_uncertainty.py
"""

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "targeted_interaction_results_expanded.json"
COMPARISON_FILE = ROOT / "zone_model_comparison_results.json"
OUTPUT_FILE = ROOT / "rbf_cluster_bootstrap_uncertainty.json"

BOOTSTRAPS = 20000
SEED = 20261105
COMPARATORS = ["extra_trees", "random_forest"]
RBF_MODEL = "rbf_clipped"
ZONES = [
    "abdo", "ankle", "antecub", "axilla", "back", "buttock",
    "calf", "chest", "conj", "ear", "elbow", "face", "foot",
    "forearm", "genital", "groin", "hand", "knee", "nail",
    "neck", "oral", "palm", "perianal", "poplit", "scalp",
    "shin", "shoulder", "sole", "thigh", "umbil", "web", "wrist",
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def ci(values):
    return [float(x) for x in np.quantile(values, [0.025, 0.975])]


def summarize_paired(group_errors, comparator, rbf, rng):
    # Positive values mean the comparator has more error than RBF.
    paired = group_errors[comparator] - group_errors[rbf]
    n = len(paired)
    draws = rng.integers(0, n, size=(BOOTSTRAPS, n))
    diff_boot = paired[draws].mean(axis=1)
    rbf_boot = group_errors[rbf][draws].mean(axis=1)
    comparator_boot = group_errors[comparator][draws].mean(axis=1)
    relative_boot = 100.0 * diff_boot / comparator_boot

    return {
        "rbf_background_cluster_mae": float(group_errors[rbf].mean()),
        "comparator_background_cluster_mae": float(group_errors[comparator].mean()),
        "absolute_mae_reduction": float(paired.mean()),
        "absolute_mae_reduction_95pct_ci": ci(diff_boot),
        "relative_mae_reduction_percent": float(
            100.0 * paired.mean() / group_errors[comparator].mean()
        ),
        "relative_mae_reduction_percent_95pct_ci": ci(relative_boot),
        "bootstrap_replicates": BOOTSTRAPS,
        "resampling_unit": "background_id (all four factorial records kept together)",
        "bootstrap_probability_reduction_positive": float(np.mean(diff_boot > 0)),
    }


def main():
    require(DATA_FILE.is_file(), f"Missing {DATA_FILE}")
    require(COMPARISON_FILE.is_file(), f"Missing {COMPARISON_FILE}")
    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    result = json.loads(COMPARISON_FILE.read_text(encoding="utf-8"))

    y = np.asarray([[r["zones"][z] for z in ZONES] for r in records], dtype=float)
    groups = np.asarray([r["background_id"] for r in records])
    require(y.shape == (1044, 32), f"Unexpected target shape {y.shape}")
    require(len(np.unique(groups)) == 261, "Expected 261 unique backgrounds.")
    require(result["records"] == len(records), "Record count mismatch.")
    require(result["zones"] == ZONES, "Zone ordering mismatch.")

    predictions = {
        name: np.asarray(result["predictions"][name], dtype=float)
        for name in [RBF_MODEL] + COMPARATORS
    }
    for name, pred in predictions.items():
        require(pred.shape == y.shape, f"{name}: prediction shape mismatch.")
        require(np.all(np.isfinite(pred)), f"{name}: non-finite predictions.")

    background_ids = list(dict.fromkeys(groups.tolist()))
    group_error = {
        name: np.zeros(len(background_ids), dtype=float)
        for name in predictions
    }
    zone_group_error = {
        name: np.zeros((len(background_ids), len(ZONES)), dtype=float)
        for name in predictions
    }

    for gi, background_id in enumerate(background_ids):
        idx = np.where(groups == background_id)[0]
        require(len(idx) == 4, f"{background_id}: expected four records.")
        for name, pred in predictions.items():
            abs_error = np.abs(pred[idx] - y[idx])
            group_error[name][gi] = float(abs_error.mean())
            zone_group_error[name][gi, :] = abs_error.mean(axis=0)

    rng = np.random.default_rng(SEED)
    overall = {
        comparator: summarize_paired(group_error, comparator, RBF_MODEL, rng)
        for comparator in COMPARATORS
    }

    zone_results = {}
    for comparator in COMPARATORS:
        zone_results[comparator] = {}
        for j, zone in enumerate(ZONES):
            paired = (
                zone_group_error[comparator][:, j]
                - zone_group_error[RBF_MODEL][:, j]
            )
            n = len(paired)
            draws = rng.integers(0, n, size=(BOOTSTRAPS, n))
            boot = paired[draws].mean(axis=1)
            zone_results[comparator][zone] = {
                "mean_mae_reduction": float(paired.mean()),
                "mean_mae_reduction_95pct_ci": ci(boot),
                "bootstrap_probability_reduction_positive": float(
                    np.mean(boot > 0)
                ),
            }

    audit = {
        "analysis": "paired_background_cluster_bootstrap_of_outer_oof_predictions",
        "interpretation": (
            "Positive MAE reduction means clipped RBF has lower absolute error. "
            "Intervals quantify background-sampling uncertainty conditional on "
            "the saved outer-fold predictions; they do not include full model-"
            "retraining uncertainty and do not establish clinical validity."
        ),
        "records": int(len(records)),
        "backgrounds": int(len(background_ids)),
        "records_per_background": 4,
        "zones": len(ZONES),
        "bootstrap_replicates": BOOTSTRAPS,
        "random_seed": SEED,
        "primary_rbf_model": RBF_MODEL,
        "overall_paired_comparisons": overall,
        "zone_specific_paired_comparisons": zone_results,
    }
    OUTPUT_FILE.write_text(json.dumps(audit, indent=2), encoding="utf-8")

    print("Paired background-cluster bootstrap complete.")
    for comparator, stats in overall.items():
        print(
            f"{RBF_MODEL} vs {comparator}: MAE reduction "
            f"{stats['relative_mae_reduction_percent']:.2f}% "
            f"(95% CI "
            f"{stats['relative_mae_reduction_percent_95pct_ci'][0]:.2f} to "
            f"{stats['relative_mae_reduction_percent_95pct_ci'][1]:.2f}%)"
        )
    print("Report:", OUTPUT_FILE.resolve())


if __name__ == "__main__":
    main()
