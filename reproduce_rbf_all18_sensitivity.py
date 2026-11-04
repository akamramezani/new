#!/usr/bin/env python3
"""Independent reproduction audit for the 18-vs-13 RBF sensitivity analysis.

Run from the repository root:
    pip install numpy scikit-learn
    python reproduce_rbf_all18_sensitivity.py

Reconstructs all 18 predictors, refits every outer-fold model, repeats inner
hyperparameter selection, and verifies saved OOF predictions, metrics, zone
bootstrap intervals, and overall bootstrap interval.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.kernel_ridge import KernelRidge
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from scoring import load_presentation, score_findings

ROOT = Path(__file__).resolve().parent
PRESENTATION = ROOT / "presentation_scaly.json"
DATA = ROOT / "targeted_interaction_results_expanded.json"
REFERENCE = ROOT / "rbf_expanded_nested_cv_results_expanded.json"
RESULT = ROOT / "rbf_all18_predictor_sensitivity.json"

ALPHAS = [1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 0.01, 0.1]
GAMMAS = [0.0001, 0.0003, 0.001, 0.003, 0.01, 0.03, 0.1]
CURRENT_13 = ["ast", "ldrug", "lp", "mf", "num", "pr", "prp",
              "pso", "reac", "scle", "seb", "syph", "tin"]
ZONES = ["abdo", "ankle", "antecub", "axilla", "back", "buttock",
         "calf", "chest", "conj", "ear", "elbow", "face", "foot",
         "forearm", "genital", "groin", "hand", "knee", "nail", "neck",
         "oral", "palm", "perianal", "poplit", "scalp", "shin",
         "shoulder", "sole", "thigh", "umbil", "web", "wrist"]
N_BOOT = 20000
SEED = 20261106
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def estimator(alpha, gamma):
    return Pipeline([
        ("standardize", StandardScaler()),
        ("rbf_krr", KernelRidge(alpha=float(alpha), kernel="rbf",
                                gamma=float(gamma))),
    ])


def score_grid(X, Y, group):
    splitter = GroupKFold(n_splits=4)
    best_score, best_alpha, best_gamma = np.inf, None, None
    count = 0
    for alpha in ALPHAS:
        for gamma in GAMMAS:
            fold_scores = []
            for fit_idx, val_idx in splitter.split(X, Y, group):
                check(set(group[fit_idx]).isdisjoint(set(group[val_idx])),
                      "Inner CV group leakage detected.")
                model = estimator(alpha, gamma)
                model.fit(X[fit_idx], Y[fit_idx])
                fold_scores.append(mean_absolute_error(
                    Y[val_idx], model.predict(X[val_idx])))
            avg = float(np.mean(fold_scores))
            count += 1
            if avg < best_score:
                best_score, best_alpha, best_gamma = avg, alpha, gamma
    return best_alpha, best_gamma, best_score, count


def clipped_metrics(y, pred):
    error = np.clip(pred, 0, 1) - y
    return {"mae": float(np.mean(np.abs(error))),
            "rmse": float(np.sqrt(np.mean(error ** 2)))}


def compare_array(name, actual, expected, atol=1e-12):
    actual = np.asarray(actual, dtype=float)
    expected = np.asarray(expected, dtype=float)
    if actual.shape != expected.shape:
        failures.append(f"{name}: shape {actual.shape} != {expected.shape}")
        return
    diff = float(np.max(np.abs(actual - expected)))
    if not np.allclose(actual, expected, rtol=0, atol=atol):
        failures.append(f"{name}: max absolute difference {diff:.3g}")
    print(f"{name}: shape={actual.shape}, max_abs_diff={diff:.3g}")


def main():
    for path in (PRESENTATION, DATA, REFERENCE, RESULT):
        check(path.is_file(), f"Missing file: {path.name}")
    if failures:
        raise SystemExit("\n".join(failures))

    presentation = load_presentation(str(PRESENTATION))
    records = json.loads(DATA.read_text(encoding="utf-8"))
    ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
    saved = json.loads(RESULT.read_text(encoding="utf-8"))

    check(digest(DATA) == saved["dataset_sha256"] == ref["dataset_sha256"],
          "Dataset SHA-256 mismatch.")
    check(digest(PRESENTATION) == saved["presentation_sha256"],
          "Presentation SHA-256 mismatch.")
    dx_ids = [item["id"] for item in presentation["dx"]]
    check(len(dx_ids) == 18 and len(set(dx_ids)) == 18,
          "Expected 18 unique diagnosis IDs.")
    check(set(CURRENT_13).issubset(dx_ids), "13-feature set mismatch.")
    check(set(dx_ids) - set(CURRENT_13) ==
          {"bowen", "dles", "plc", "ivul", "eryth"},
          "Five additional diagnosis IDs mismatch.")

    x_rows, y_rows, groups = [], [], []
    reconstruction_error = 0.0
    for row_no, record in enumerate(records):
        ranked = score_findings(presentation, record["answers"])["ranked"]
        probability = {item["id"]: float(item["probability"]) for item in ranked}
        x_rows.append([probability[k] for k in dx_ids])
        rebuilt_13 = np.asarray([probability[k] for k in CURRENT_13])
        stored_13 = np.asarray(record["predictors"], dtype=float)
        if stored_13.shape != (13,):
            failures.append(f"Record {row_no}: expected 13 stored predictors.")
        else:
            reconstruction_error = max(
                reconstruction_error,
                float(np.max(np.abs(rebuilt_13 - stored_13))))
        y_rows.append([float(record["zones"][z]) for z in ZONES])
        groups.append(str(record["background_id"]))

    X = np.asarray(x_rows, dtype=float)
    Y = np.asarray(y_rows, dtype=float)
    groups = np.asarray(groups)
    check(X.shape == (1044, 18) and Y.shape == (1044, 32),
          f"Unexpected matrix shapes: {X.shape}, {Y.shape}")
    check(reconstruction_error <= 1e-10,
          f"13-predictor reconstruction difference={reconstruction_error}")
    unique_groups = np.unique(groups)
    check(len(unique_groups) == 261, "Expected 261 background clusters.")
    check(all(np.sum(groups == g) == 4 for g in unique_groups),
          "Not all backgrounds contain exactly four factorial rows.")

    saved_assignments = ref["record_fold_assignments"]
    check(len(saved_assignments) == len(records),
          "Reference fold assignment length mismatch.")
    P18 = np.full(Y.shape, np.nan)
    fold_details = []
    outer = GroupKFold(n_splits=5)
    for fold_no, (train_idx, test_idx) in enumerate(
            outer.split(X, Y, groups), start=1):
        check(set(groups[train_idx]).isdisjoint(set(groups[test_idx])),
              f"Outer fold {fold_no}: group leakage.")
        for idx in test_idx:
            item = saved_assignments[int(idx)]
            check(item["record_index"] == int(idx)
                  and item["background_id"] == groups[idx]
                  and item["outer_fold"] == fold_no,
                  f"Outer-fold assignment mismatch at row {idx}.")
        alpha, gamma, inner_mae, n_grid = score_grid(
            X[train_idx], Y[train_idx], groups[train_idx])
        model = estimator(alpha, gamma)
        model.fit(X[train_idx], Y[train_idx])
        P18[test_idx] = model.predict(X[test_idx])
        fold_details.append({
            "fold": fold_no, "alpha": float(alpha), "gamma": float(gamma),
            "inner_mae": float(inner_mae), "grid_count": n_grid,
            "metrics": clipped_metrics(Y[test_idx], P18[test_idx]),
        })
        print(f"Fold {fold_no}: alpha={alpha:g}, gamma={gamma:g}, "
              f"MAE={fold_details[-1]['metrics']['mae']:.10f}")

    check(np.isfinite(P18).all(), "Non-finite or missing OOF predictions.")
    compare_array("18-feature raw OOF predictions",
                  P18, saved["predictions_18_raw"])
    compare_array("18-feature clipped OOF predictions",
                  np.clip(P18, 0, 1), saved["predictions_18_clipped"])

    P13 = np.clip(np.asarray(ref["predictions"], dtype=float), 0, 1)
    P18c = np.clip(P18, 0, 1)
    metrics13 = clipped_metrics(Y, P13)
    metrics18 = clipped_metrics(Y, P18c)
    compare_array("13-feature metrics",
                  [metrics13["mae"], metrics13["rmse"]],
                  [saved["13_feature_reference_metrics"]["mae"],
                   saved["13_feature_reference_metrics"]["rmse"]])
    compare_array("18-feature metrics",
                  [metrics18["mae"], metrics18["rmse"]],
                  [saved["18_feature_nested_cv_metrics"]["mae"],
                   saved["18_feature_nested_cv_metrics"]["rmse"]])

    rng = np.random.default_rng(SEED)
    cluster_rows = {g: np.flatnonzero(groups == g) for g in unique_groups}
    deltas = np.empty(N_BOOT)
    zone_deltas = np.empty((N_BOOT, len(ZONES)))
    for b in range(N_BOOT):
        sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        indices = np.concatenate([cluster_rows[g] for g in sampled])
        e13 = np.abs(Y[indices] - P13[indices])
        e18 = np.abs(Y[indices] - P18c[indices])
        deltas[b] = np.mean(e13) - np.mean(e18)
        zone_deltas[b] = np.mean(e13 - e18, axis=0)

    point = metrics13["mae"] - metrics18["mae"]
    interval = np.quantile(deltas, [0.025, 0.975])
    compare_array("Overall MAE reduction and bootstrap CI",
                  [point, *interval],
                  [saved["mae_reduction_13_minus_18"],
                   *saved["mae_reduction_95pct_cluster_bootstrap_ci"]])
    probability = float(np.mean(deltas > 0))
    compare_array("Bootstrap probability",
                  [probability],
                  [saved["bootstrap_probability_18_feature_model_better"]])

    zone_failures = []
    for j, zone in enumerate(ZONES):
        result = saved["zone_results"][zone]
        point_zone = float(np.mean(np.abs(Y[:, j] - P13[:, j]))
                           - np.mean(np.abs(Y[:, j] - P18c[:, j])))
        ci_zone = np.quantile(zone_deltas[:, j], [0.025, 0.975])
        compare_array(f"Zone {zone}",
                      [point_zone, *ci_zone],
                      [result["mae_reduction_13_minus_18"],
                       *result["bootstrap_95pct_ci"]])
        if ci_zone[0] > 0:
            zone_failures.append(zone + ": advantage")
        elif ci_zone[1] < 0:
            zone_failures.append(zone + ": disadvantage")
        else:
            zone_failures.append(zone + ": inconclusive")

    print("\nZone CI classifications:")
    for label in ("advantage", "disadvantage", "inconclusive"):
        names = [z.split(":")[0] for z in zone_failures if z.endswith(label)]
        print(f"  {label}: {len(names)} {names}")
    print("\nPredictor reconstruction max abs difference:", reconstruction_error)
    print("18-feature raw prediction range:",
          float(np.min(P18)), "to", float(np.max(P18)))
    print("Raw predictions outside [0,1]:",
          int(np.sum((P18 < 0) | (P18 > 1))))
    print("\nFold selection reproduced:",
          all(a["alpha"] == b["alpha"] and a["gamma"] == b["gamma"]
              for a, b in zip(fold_details, saved["fold_results"])))
    print("Failures:", failures)
    if failures:
        raise SystemExit(1)
    print("PASS: all 18-feature OOF predictions, metrics, and bootstrap "
          "results independently reproduced.")


if __name__ == "__main__":
    main()
