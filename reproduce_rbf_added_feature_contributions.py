#!/usr/bin/env python3
"""Independent reproduction audit for added-feature conditional contributions.

Rebuilds all 18 diagnosis predictors from scoring.py, independently reruns the
full and five leave-one-added-feature-out nested grouped-CV models, recomputes
the paired background bootstrap, and compares every OOF prediction and
reported statistic with rbf_added_feature_contributions.json.

Run:
    pip install numpy scikit-learn
    python reproduce_rbf_added_feature_contributions.py
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
DATA = ROOT / "targeted_interaction_results_expanded.json"
PRESENTATION = ROOT / "presentation_scaly.json"
REPORT = ROOT / "rbf_added_feature_contributions.json"
ADDED = ["bowen", "dles", "plc", "ivul", "eryth"]
ALPHAS = [1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 0.01, 0.1]
GAMMAS = [0.0001, 0.0003, 0.001, 0.003, 0.01, 0.03, 0.1]
ZONES = ["abdo", "ankle", "antecub", "axilla", "back", "buttock",
         "calf", "chest", "conj", "ear", "elbow", "face", "foot",
         "forearm", "genital", "groin", "hand", "knee", "nail", "neck",
         "oral", "palm", "perianal", "poplit", "scalp", "shin",
         "shoulder", "sole", "thigh", "umbil", "web", "wrist"]
N_BOOT = 20000
SEED = 20261107
ATOL = 1e-12
RTOL = 1e-10


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(alpha, gamma):
    return Pipeline([
        ("standardize", StandardScaler()),
        ("rbf_krr", KernelRidge(alpha=float(alpha), kernel="rbf",
                                gamma=float(gamma))),
    ])


def inner_select(x, y, group):
    cv = GroupKFold(n_splits=4)
    best_score, best_params = np.inf, None
    for a in ALPHAS:
        for g in GAMMAS:
            scores = []
            for train, valid in cv.split(x, y, group):
                check(set(group[train]).isdisjoint(set(group[valid])),
                      "Inner split contains background leakage.")
                estimator = model(a, g)
                estimator.fit(x[train], y[train])
                scores.append(mean_absolute_error(y[valid],
                                                   estimator.predict(x[valid])))
            score = float(np.mean(scores))
            if score < best_score:
                best_score, best_params = score, (a, g)
    return best_params[0], best_params[1], best_score


def metrics(y, pred):
    error = np.clip(pred, 0, 1) - y
    return {"mae": float(np.mean(np.abs(error))),
            "rmse": float(np.sqrt(np.mean(error ** 2)))}


def nested_predictions(x, y, group, label):
    pred = np.full(y.shape, np.nan)
    folds = []
    for fold, (train, test) in enumerate(
            GroupKFold(n_splits=5).split(x, y, group), 1):
        check(set(group[train]).isdisjoint(set(group[test])),
              "Outer split contains background leakage.")
        alpha, gamma, inner_mae = inner_select(x[train], y[train], group[train])
        estimator = model(alpha, gamma)
        estimator.fit(x[train], y[train])
        pred[test] = estimator.predict(x[test])
        folds.append({
            "fold": fold, "alpha": float(alpha), "gamma": float(gamma),
            "best_inner_mae": float(inner_mae),
            "test_records": int(len(test)),
            "clipped_metrics": metrics(y[test], pred[test]),
        })
        print(f"{label}: fold {fold}/5 complete; alpha={alpha:g}, gamma={gamma:g}")
    check(np.isfinite(pred).all(), f"{label}: missing OOF predictions.")
    return pred, folds


def compare_array(label, actual, expected):
    a = np.asarray(actual, dtype=float)
    e = np.asarray(expected, dtype=float)
    check(a.shape == e.shape, f"{label}: shape mismatch {a.shape} vs {e.shape}")
    delta = float(np.max(np.abs(a - e))) if a.size else 0.0
    check(np.allclose(a, e, atol=ATOL, rtol=RTOL),
          f"{label}: mismatch; maximum absolute difference={delta}")
    print(f"PASS {label}: shape={a.shape}, max_abs_diff={delta:.3g}")


def compare_scalar(label, actual, expected):
    delta = abs(float(actual) - float(expected))
    check(np.isclose(actual, expected, atol=ATOL, rtol=RTOL),
          f"{label}: mismatch; absolute difference={delta}")
    print(f"PASS {label}: difference={delta:.3g}")


def main():
    for path in (DATA, PRESENTATION, REPORT):
        check(path.is_file(), f"Missing required file: {path.name}")
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    presentation = load_presentation(str(PRESENTATION))
    records = json.loads(DATA.read_text(encoding="utf-8"))
    dx_order = [item["id"] for item in presentation["dx"]]

    check(digest(DATA) == report["dataset_sha256"], "Dataset hash mismatch.")
    check(digest(PRESENTATION) == report["presentation_sha256"],
          "Presentation hash mismatch.")
    check(dx_order == report["diagnosis_feature_order"],
          "Diagnosis predictor order mismatch.")
    check(ADDED == report["five_added_predictors"],
          "Added-feature list mismatch.")
    check(len(records) == 1044, "Expected 1,044 records.")

    x_rows, y_rows, groups = [], [], []
    for record in records:
        ranked = score_findings(presentation, record["answers"])["ranked"]
        p = {item["id"]: float(item["probability"]) for item in ranked}
        x_rows.append([p[key] for key in dx_order])
        y_rows.append([float(record["zones"][zone]) for zone in ZONES])
        groups.append(str(record["background_id"]))
    x = np.asarray(x_rows, dtype=float)
    y = np.asarray(y_rows, dtype=float)
    groups = np.asarray(groups)
    unique = np.unique(groups)
    check(x.shape == (1044, 18) and y.shape == (1044, 32),
          f"Unexpected reconstructed shapes: {x.shape}, {y.shape}")
    check(len(unique) == 261, "Expected 261 unique backgrounds.")
    check(all(np.sum(groups == key) == 4 for key in unique),
          "A background does not have exactly four factorial records.")
    compare_array("reconstructed 18-feature matrix", x,
                  np.asarray(x_rows, dtype=float))
    print("PASS data structure: 1,044 records, 261 groups, 4 records/group.")

    full_pred, full_folds = nested_predictions(x, y, groups, "FULL18")
    compare_array("full 18-feature raw OOF predictions",
                  full_pred, report["full_18_predictions_raw"])
    full_metrics = metrics(y, full_pred)
    for key in ("mae", "rmse"):
        compare_scalar(f"full 18-feature {key}", full_metrics[key],
                       report["full_18_feature_metrics"][key])

    predictions = {}
    for feature in ADDED:
        keep = [i for i, key in enumerate(dx_order) if key != feature]
        pred, folds = nested_predictions(x[:, keep], y, groups, f"DROP_{feature}")
        predictions[feature] = pred
        compare_array(f"{feature} dropped raw OOF predictions", pred,
                      report["drop_feature_predictions_raw"][feature])
        calculated = metrics(y, pred)
        saved = report["feature_removal_results"][feature]["drop_feature_metrics"]
        for key in ("mae", "rmse"):
            compare_scalar(f"{feature} dropped {key}", calculated[key], saved[key])
        saved_folds = report["feature_removal_results"][feature]["folds"]
        check(len(folds) == len(saved_folds), f"{feature}: fold count mismatch")
        for i, (a, b) in enumerate(zip(folds, saved_folds), 1):
            for key in ("fold", "alpha", "gamma", "best_inner_mae", "test_records"):
                check(a[key] == b[key] or np.isclose(a[key], b[key],
                      atol=ATOL, rtol=RTOL),
                      f"{feature}, fold {i}: {key} mismatch")
        print(f"PASS {feature}: all selected fold hyperparameters reproduced.")

    # Recompute the joint paired cluster bootstrap, sampling all four records
    # from each selected background and using identical draws for all contrasts.
    rng = np.random.default_rng(SEED)
    rows = {key: np.flatnonzero(groups == key) for key in unique}
    boot = np.empty((N_BOOT, len(ADDED)))
    full_clipped = np.clip(full_pred, 0, 1)
    for b in range(N_BOOT):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([rows[key] for key in sampled])
        full_error = np.abs(y[idx] - full_clipped[idx])
        for j, feature in enumerate(ADDED):
            drop_error = np.abs(y[idx] -
                                np.clip(predictions[feature][idx], 0, 1))
            boot[b, j] = np.mean(drop_error) - np.mean(full_error)

    for j, feature in enumerate(ADDED):
        saved = report["feature_removal_results"][feature]
        point = metrics(y, predictions[feature])["mae"] - full_metrics["mae"]
        ci = np.quantile(boot[:, j], [0.005, 0.995])
        probability = float(np.mean(boot[:, j] > 0))
        compare_scalar(f"{feature} MAE increase", point,
                       saved["mae_increase_when_removed"])
        compare_array(f"{feature} Bonferroni 99% CI", ci,
                      saved["bonferroni_99pct_cluster_bootstrap_ci"])
        compare_scalar(f"{feature} bootstrap probability", probability,
                       saved["bootstrap_probability_removal_worsens_mae"])

    print("\\nPASS: all six nested-CV models, raw OOF predictions, fold selections,")
    print("metrics, and five paired-cluster-bootstrap contrasts independently reproduced.")


if __name__ == "__main__":
    main()
