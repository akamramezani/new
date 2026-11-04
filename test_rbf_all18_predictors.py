#!/usr/bin/env python3
"""Nested grouped-CV test of all 18 diagnosis probabilities vs the current 13.

This is an input-feature ablation/sensitivity analysis. It does not establish
clinical validity and does not assume the API's internal zone algorithm.
Run from the repository root:
    pip install numpy scikit-learn
    python test_rbf_all18_predictors.py
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
PRESENTATION_FILE = ROOT / "presentation_scaly.json"
DATA_FILE = ROOT / "targeted_interaction_results_expanded.json"
REFERENCE_FILE = ROOT / "rbf_expanded_nested_cv_results_expanded.json"
OUTPUT_FILE = ROOT / "rbf_all18_predictor_sensitivity.json"

OUTER_SPLITS = 5
INNER_SPLITS = 4
ALPHAS = [1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 0.01, 0.1]
GAMMAS = [0.0001, 0.0003, 0.001, 0.003, 0.01, 0.03, 0.1]
CURRENT_13 = ["ast", "ldrug", "lp", "mf", "num", "pr", "prp",
              "pso", "reac", "scle", "seb", "syph", "tin"]
ZONES = ["abdo", "ankle", "antecub", "axilla", "back", "buttock",
         "calf", "chest", "conj", "ear", "elbow", "face", "foot",
         "forearm", "genital", "groin", "hand", "knee", "nail", "neck",
         "oral", "palm", "perianal", "poplit", "scalp", "shin",
         "shoulder", "sole", "thigh", "umbil", "web", "wrist"]
BOOTSTRAPS = 20000
BOOTSTRAP_SEED = 20261106


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def model(alpha, gamma):
    return Pipeline([
        ("scale", StandardScaler()),
        ("model", KernelRidge(alpha=float(alpha), kernel="rbf",
                              gamma=float(gamma))),
    ])


def tune(X, Y, groups):
    cv = GroupKFold(n_splits=INNER_SPLITS)
    best = (np.inf, None, None)
    evaluations = 0
    for alpha in ALPHAS:
        for gamma in GAMMAS:
            scores = []
            for tr, va in cv.split(X, Y, groups):
                require(not set(groups[tr]).intersection(groups[va]),
                        "Background leakage in inner CV.")
                m = model(alpha, gamma)
                m.fit(X[tr], Y[tr])
                scores.append(float(mean_absolute_error(Y[va], m.predict(X[va]))))
            score = float(np.mean(scores))
            evaluations += 1
            if score < best[0]:
                best = (score, alpha, gamma)
    return best[1], best[2], best[0], evaluations


def metrics(Y, P):
    e = np.clip(P, 0, 1) - Y
    return {"mae": float(np.mean(np.abs(e))),
            "rmse": float(np.sqrt(np.mean(e ** 2)))}


def main():
    for p in (PRESENTATION_FILE, DATA_FILE, REFERENCE_FILE):
        require(p.is_file(), f"Missing required file: {p}")
    presentation = load_presentation(str(PRESENTATION_FILE))
    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    ref = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
    require(sha256(DATA_FILE) == ref["dataset_sha256"],
            "Dataset SHA-256 differs from saved reference.")
    require(len(presentation["dx"]) == 18,
            f"Expected 18 diagnoses, got {len(presentation['dx'])}.")
    all_ids = [d["id"] for d in presentation["dx"]]
    require(len(set(all_ids)) == 18, "Diagnosis IDs are not unique.")
    omitted = [x for x in all_ids if x not in CURRENT_13]
    require(len(omitted) == 5 and set(CURRENT_13).issubset(all_ids),
            f"Unexpected diagnosis feature set: {all_ids}")

    X18, Y, groups = [], [], []
    reconstruction_max_diff = 0.0
    for i, rec in enumerate(records):
        scored = score_findings(presentation, rec["answers"])
        probs = {r["id"]: float(r["probability"]) for r in scored["ranked"]}
        x = np.asarray([probs[k] for k in all_ids], dtype=float)
        x13 = np.asarray([probs[k] for k in CURRENT_13], dtype=float)
        stored = np.asarray(rec["predictors"], dtype=float)
        require(stored.shape == (13,), f"Record {i}: bad stored predictor shape.")
        reconstruction_max_diff = max(
            reconstruction_max_diff, float(np.max(np.abs(x13 - stored))))
        X18.append(x)
        Y.append([float(rec["zones"][z]) for z in ZONES])
        groups.append(str(rec["background_id"]))
    X18, Y, groups = np.asarray(X18), np.asarray(Y), np.asarray(groups)
    require(reconstruction_max_diff <= 1e-10,
            f"13-feature reconstruction mismatch: {reconstruction_max_diff}")
    require(X18.shape == (1044, 18) and Y.shape == (1044, 32),
            f"Unexpected matrix shapes: {X18.shape}, {Y.shape}")
    require(len(np.unique(groups)) == 261, "Expected 261 backgrounds.")
    require(all(np.sum(groups == g) == 4 for g in np.unique(groups)),
            "Every background must have four factorial records.")

    saved_assignments = ref["record_fold_assignments"]
    require(len(saved_assignments) == len(records), "Fold assignment count mismatch.")
    P18 = np.full_like(Y, np.nan)
    fold_reports = []
    cv = GroupKFold(n_splits=OUTER_SPLITS)
    for fold, (tr, te) in enumerate(cv.split(X18, Y, groups), start=1):
        for idx in te:
            a = saved_assignments[int(idx)]
            require(a["record_index"] == int(idx)
                    and a["background_id"] == groups[idx]
                    and a["outer_fold"] == fold,
                    f"Saved outer-fold assignment mismatch at record {idx}.")
        alpha, gamma, inner_mae, n_eval = tune(X18[tr], Y[tr], groups[tr])
        m = model(alpha, gamma)
        m.fit(X18[tr], Y[tr])
        P18[te] = m.predict(X18[te])
        fold_reports.append({
            "fold": fold, "train_records": len(tr), "test_records": len(te),
            "alpha": float(alpha), "gamma": float(gamma),
            "best_inner_mae": inner_mae, "grid_combinations": n_eval,
            "clipped_outer_metrics": metrics(Y[te], P18[te]),
        })
        print(f"Fold {fold}/5 | alpha={alpha:g} gamma={gamma:g} | "
              f"clipped MAE={metrics(Y[te], P18[te])['mae']:.8f}")

    require(np.all(np.isfinite(P18)), "Missing 18-feature OOF predictions.")
    P13 = np.asarray(ref["predictions"], dtype=float)
    require(P13.shape == Y.shape, "Reference 13-feature predictions shape mismatch.")
    P13 = np.clip(P13, 0, 1)
    P18c = np.clip(P18, 0, 1)

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    unique_groups = np.unique(groups)
    by_group = {g: np.where(groups == g)[0] for g in unique_groups}
    boot_delta = np.empty(BOOTSTRAPS)
    boot_zone_delta = np.empty((BOOTSTRAPS, len(ZONES)))
    for b in range(BOOTSTRAPS):
        sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        idx = np.concatenate([by_group[g] for g in sampled])
        err13 = np.abs(Y[idx] - P13[idx])
        err18 = np.abs(Y[idx] - P18c[idx])
        boot_delta[b] = np.mean(err13) - np.mean(err18)
        boot_zone_delta[b] = np.mean(err13 - err18, axis=0)

    point_delta = metrics(Y, P13)["mae"] - metrics(Y, P18c)["mae"]
    ci = np.quantile(boot_delta, [0.025, 0.975]).tolist()
    zone_results = {}
    for j, z in enumerate(ZONES):
        vals = boot_zone_delta[:, j]
        zone_results[z] = {
            "mae_reduction_13_minus_18": float(np.mean(np.abs(Y[:, j] - P13[:, j]))
                                                - np.mean(np.abs(Y[:, j] - P18c[:, j]))),
            "bootstrap_95pct_ci": np.quantile(vals, [0.025, 0.975]).tolist(),
            "bootstrap_probability_18_better": float(np.mean(vals > 0)),
        }

    output = {
        "analysis": "18_vs_13_diagnosis_probability_features_nested_grouped_cv",
        "interpretation": "Positive MAE reduction means 18-feature RBF has lower clipped OOF MAE. Paired background bootstrap conditions on saved OOF predictions and does not establish clinical validity.",
        "dataset_sha256": sha256(DATA_FILE),
        "presentation_sha256": sha256(PRESENTATION_FILE),
        "records": len(records), "backgrounds": len(unique_groups),
        "factorial_records_per_background": 4, "zones": len(ZONES),
        "current_13_features": CURRENT_13,
        "all_18_features_in_presentation_order": all_ids,
        "five_additional_features": omitted,
        "predictor_reconstruction_max_abs_difference": reconstruction_max_diff,
        "outer_splits": OUTER_SPLITS, "inner_splits": INNER_SPLITS,
        "alpha_grid": ALPHAS, "gamma_grid": GAMMAS,
        "13_feature_reference_metrics": metrics(Y, P13),
        "18_feature_nested_cv_metrics": metrics(Y, P18c),
        "mae_reduction_13_minus_18": float(point_delta),
        "mae_reduction_95pct_cluster_bootstrap_ci": ci,
        "bootstrap_probability_18_feature_model_better": float(np.mean(boot_delta > 0)),
        "bootstrap_replicates": BOOTSTRAPS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "resampling_unit": "background_id; all four factorial rows kept together",
        "fold_results": fold_reports,
        "zone_results": zone_results,
        "predictions_18_raw": P18.tolist(),
        "predictions_18_clipped": P18c.tolist(),
    }
    OUTPUT_FILE.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("\n13-feature clipped metrics:", output["13_feature_reference_metrics"])
    print("18-feature clipped metrics:", output["18_feature_nested_cv_metrics"])
    print("MAE reduction (13 minus 18):", point_delta, "95% CI:", ci)
    print("Bootstrap probability 18-feature model is better:",
          output["bootstrap_probability_18_feature_model_better"])
    print("Saved:", OUTPUT_FILE.resolve())


if __name__ == "__main__":
    main()
