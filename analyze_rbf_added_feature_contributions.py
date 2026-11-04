#!/usr/bin/env python3
"""Conditional contribution of each of the five added diagnosis predictors.

For each added predictor, compare the full 18-feature RBF model against a
17-feature model with only that predictor removed. Every model is independently
tuned within the same nested, background-grouped CV design.

The paired background-cluster bootstrap uses the same resampled clusters for
all five contrasts. Bonferroni 99% percentile intervals control family-wise
coverage across the five exploratory feature-removal comparisons.

Run:
    pip install numpy scikit-learn
    python analyze_rbf_added_feature_contributions.py
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
OUTPUT = ROOT / "rbf_added_feature_contributions.json"

ADDED = ["bowen", "dles", "plc", "ivul", "eryth"]
ALPHAS = [1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 0.01, 0.1]
GAMMAS = [0.0001, 0.0003, 0.001, 0.003, 0.01, 0.03, 0.1]
ZONES = ["abdo", "ankle", "antecub", "axilla", "back", "buttock",
         "calf", "chest", "conj", "ear", "elbow", "face", "foot",
         "forearm", "genital", "groin", "hand", "knee", "nail", "neck",
         "oral", "palm", "perianal", "poplit", "scalp", "shin",
         "shoulder", "sole", "thigh", "umbil", "web", "wrist"]
OUTER = 5
INNER = 4
BOOT = 20000
SEED = 20261107


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_model(alpha, gamma):
    return Pipeline([
        ("scale", StandardScaler()),
        ("model", KernelRidge(alpha=float(alpha), kernel="rbf",
                              gamma=float(gamma))),
    ])


def tune(X, Y, groups):
    splitter = GroupKFold(n_splits=INNER)
    best = (np.inf, None, None)
    for alpha in ALPHAS:
        for gamma in GAMMAS:
            fold_scores = []
            for tr, va in splitter.split(X, Y, groups):
                require(set(groups[tr]).isdisjoint(set(groups[va])),
                        "Inner-CV background leakage.")
                estimator = make_model(alpha, gamma)
                estimator.fit(X[tr], Y[tr])
                fold_scores.append(mean_absolute_error(
                    Y[va], estimator.predict(X[va])))
            candidate = float(np.mean(fold_scores))
            if candidate < best[0]:
                best = (candidate, alpha, gamma)
    return best[1], best[2], best[0]


def clipped_metrics(Y, P):
    error = np.clip(P, 0, 1) - Y
    return {"mae": float(np.mean(np.abs(error))),
            "rmse": float(np.sqrt(np.mean(error ** 2)))}


def nested_oof(X, Y, groups, label):
    predictions = np.full(Y.shape, np.nan)
    folds = []
    splitter = GroupKFold(n_splits=OUTER)
    for fold, (tr, te) in enumerate(splitter.split(X, Y, groups), 1):
        require(set(groups[tr]).isdisjoint(set(groups[te])),
                f"{label}: outer-CV background leakage.")
        alpha, gamma, inner_mae = tune(X[tr], Y[tr], groups[tr])
        estimator = make_model(alpha, gamma)
        estimator.fit(X[tr], Y[tr])
        predictions[te] = estimator.predict(X[te])
        fold_metric = clipped_metrics(Y[te], predictions[te])
        folds.append({
            "fold": fold, "alpha": float(alpha), "gamma": float(gamma),
            "best_inner_mae": float(inner_mae),
            "test_records": int(len(te)), "clipped_metrics": fold_metric,
        })
        print(f"{label} | fold {fold}/{OUTER} | alpha={alpha:g} "
              f"gamma={gamma:g} | MAE={fold_metric['mae']:.8f}")
    require(np.isfinite(predictions).all(), f"{label}: incomplete OOF predictions.")
    return predictions, folds


def main():
    require(PRESENTATION.is_file() and DATA.is_file(),
            "Missing presentation_scaly.json or expanded dataset.")
    presentation = load_presentation(str(PRESENTATION))
    records = json.loads(DATA.read_text(encoding="utf-8"))
    dx_ids = [item["id"] for item in presentation["dx"]]
    require(len(dx_ids) == 18 and len(set(dx_ids)) == 18,
            "Expected 18 unique diagnoses.")
    require(set(ADDED).issubset(dx_ids), "One or more added predictors are absent.")

    X_rows, Y_rows, group_rows = [], [], []
    for record in records:
        ranked = score_findings(presentation, record["answers"])["ranked"]
        probability = {item["id"]: float(item["probability"]) for item in ranked}
        X_rows.append([probability[key] for key in dx_ids])
        Y_rows.append([float(record["zones"][zone]) for zone in ZONES])
        group_rows.append(str(record["background_id"]))
    X = np.asarray(X_rows, dtype=float)
    Y = np.asarray(Y_rows, dtype=float)
    groups = np.asarray(group_rows)
    require(X.shape == (1044, 18) and Y.shape == (1044, 32),
            f"Unexpected data shape: {X.shape}, {Y.shape}")
    unique_groups = np.unique(groups)
    require(len(unique_groups) == 261, "Expected 261 backgrounds.")
    require(all(np.sum(groups == g) == 4 for g in unique_groups),
            "Each background must have four factorial records.")

    # One shared full-model fit and five leave-one-added-feature-out fits.
    full_prediction, full_folds = nested_oof(X, Y, groups, "FULL18")
    model_predictions = {}
    model_folds = {}
    feature_indices = {key: dx_ids.index(key) for key in ADDED}
    for feature in ADDED:
        keep = [i for i, key in enumerate(dx_ids) if key != feature]
        pred, folds = nested_oof(
            X[:, keep], Y, groups, f"DROP_{feature}")
        model_predictions[feature] = pred
        model_folds[feature] = folds

    full_clipped = np.clip(full_prediction, 0, 1)
    full_metrics = clipped_metrics(Y, full_prediction)

    # Joint paired cluster bootstrap: identical sampled backgrounds for all
    # five feature-removal contrasts in each replicate.
    rng = np.random.default_rng(SEED)
    rows_by_group = {g: np.flatnonzero(groups == g) for g in unique_groups}
    boot = np.empty((BOOT, len(ADDED)))
    for b in range(BOOT):
        sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        idx = np.concatenate([rows_by_group[g] for g in sampled])
        full_error = np.abs(Y[idx] - full_clipped[idx])
        for j, feature in enumerate(ADDED):
            dropped_error = np.abs(
                Y[idx] - np.clip(model_predictions[feature][idx], 0, 1))
            boot[b, j] = np.mean(dropped_error) - np.mean(full_error)

    results = {}
    for j, feature in enumerate(ADDED):
        dropped_metrics = clipped_metrics(Y, model_predictions[feature])
        point = dropped_metrics["mae"] - full_metrics["mae"]
        # Bonferroni family-wise 95% coverage across five contrasts:
        # each individual percentile interval is 99%.
        ci = np.quantile(boot[:, j], [0.005, 0.995]).tolist()
        results[feature] = {
            "interpretation": "Positive value means removing this feature worsens MAE; the feature contributes unique predictive information conditional on the other 17 features and this modeling pipeline.",
            "drop_feature_metrics": dropped_metrics,
            "full_18_feature_metrics": full_metrics,
            "mae_increase_when_removed": float(point),
            "bonferroni_99pct_cluster_bootstrap_ci": ci,
            "bootstrap_probability_removal_worsens_mae": float(
                np.mean(boot[:, j] > 0)),
            "folds": model_folds[feature],
        }

    output = {
        "analysis": "conditional_leave_one_added_predictor_out_nested_grouped_cv",
        "dataset_sha256": sha256(DATA),
        "presentation_sha256": sha256(PRESENTATION),
        "records": int(len(records)),
        "backgrounds": int(len(unique_groups)),
        "factorial_records_per_background": 4,
        "zones": ZONES,
        "diagnosis_feature_order": dx_ids,
        "five_added_predictors": ADDED,
        "outer_splits": OUTER,
        "inner_splits": INNER,
        "alpha_grid": ALPHAS,
        "gamma_grid": GAMMAS,
        "bootstrap_replicates": BOOT,
        "bootstrap_seed": SEED,
        "resampling_unit": "background_id; all four factorial records sampled together",
        "interval_method": "99% percentile intervals for each of five contrasts; Bonferroni family-wise 95% coverage",
        "full_18_feature_metrics": full_metrics,
        "full_18_feature_folds": full_folds,
        "feature_removal_results": results,
        "interpretation_caution": "Conditional predictive contribution in this generated dataset only; not causal importance, clinical validity, or proof of independent biological information.",
        "full_18_predictions_raw": full_prediction.tolist(),
        "drop_feature_predictions_raw": {
            feature: pred.tolist()
            for feature, pred in model_predictions.items()
        },
    }
    OUTPUT.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("\nFull 18-feature metrics:", full_metrics)
    print("\nConditional feature-removal results:")
    for feature, result in results.items():
        print(feature, "MAE increase when removed=",
              result["mae_increase_when_removed"],
              "Bonferroni 99% CI=",
              result["bonferroni_99pct_cluster_bootstrap_ci"],
              "P(removal worsens MAE)=",
              result["bootstrap_probability_removal_worsens_mae"])
    print("\nSaved:", OUTPUT.resolve())


if __name__ == "__main__":
    main()
