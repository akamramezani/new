#!/usr/bin/env python3
"""Independent reproduction audit for expanded RBF vs tree-model comparison.

Run from the repository root:
    pip install numpy scikit-learn
    python reproduce_zone_model_comparison.py

This re-fits Random Forest and Extra Trees from scratch, including every
inner-CV grid evaluation, then compares all predictions with the saved
comparison artifact. It does not overwrite that artifact.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "targeted_interaction_results_expanded.json"
RBF_FILE = ROOT / "rbf_expanded_nested_cv_results_expanded.json"
REFERENCE_FILE = ROOT / "zone_model_comparison_results.json"
OUTPUT_FILE = ROOT / "zone_model_comparison_reproduction_audit.json"

INNER_SPLITS = 4
RANDOM_STATE = 20261104
N_ESTIMATORS = 300
MAX_FEATURES_GRID = [0.7, 1.0]
MIN_SAMPLES_LEAF_GRID = [1, 2, 4]
ZONES = [
    "abdo", "ankle", "antecub", "axilla", "back", "buttock",
    "calf", "chest", "conj", "ear", "elbow", "face", "foot",
    "forearm", "genital", "groin", "hand", "knee", "nail",
    "neck", "oral", "palm", "perianal", "poplit", "scalp",
    "shin", "shoulder", "sole", "thigh", "umbil", "web", "wrist",
]
MODELS = ["rbf", "rbf_clipped", "random_forest", "extra_trees", "mean_baseline"]
TOL = 1e-10


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def make_tree(model_type, max_features, min_samples_leaf):
    cls = RandomForestRegressor if model_type == "random_forest" else ExtraTreesRegressor
    return cls(
        n_estimators=N_ESTIMATORS,
        max_features=max_features,
        min_samples_leaf=min_samples_leaf,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )


def metrics(y, pred):
    err = np.asarray(pred) - np.asarray(y)
    clipped = np.clip(pred, 0.0, 1.0)
    cerr = clipped - y
    return {
        "raw_mae": float(np.mean(np.abs(err))),
        "raw_rmse": float(np.sqrt(np.mean(err ** 2))),
        "raw_max_abs_error": float(np.max(np.abs(err))),
        "raw_bias": float(np.mean(err)),
        "clipped_mae": float(np.mean(np.abs(cerr))),
        "clipped_rmse": float(np.sqrt(np.mean(cerr ** 2))),
        "predictions_above_one": int(np.sum(np.asarray(pred) > 1)),
        "predictions_below_zero": int(np.sum(np.asarray(pred) < 0)),
        "n_values": int(np.asarray(y).size),
    }


def tune(model_type, x, y, groups):
    cv = GroupKFold(n_splits=INNER_SPLITS)
    search = []
    best_score = np.inf
    best_params = None

    for max_features in MAX_FEATURES_GRID:
        for leaf in MIN_SAMPLES_LEAF_GRID:
            scores = []
            for tr, va in cv.split(x, y, groups):
                require(
                    not set(groups[tr]).intersection(groups[va]),
                    f"{model_type}: inner-fold group leakage",
                )
                model = make_tree(model_type, max_features, leaf)
                model.fit(x[tr], y[tr])
                scores.append(float(np.mean(np.abs(model.predict(x[va]) - y[va]))))

            mean_score = float(np.mean(scores))
            item = {
                "max_features": float(max_features),
                "min_samples_leaf": int(leaf),
                "mean_inner_mae": mean_score,
                "inner_fold_mae": scores,
            }
            search.append(item)
            if mean_score < best_score:
                best_score = mean_score
                best_params = {
                    "max_features": float(max_features),
                    "min_samples_leaf": int(leaf),
                }
    return best_params, best_score, search


def compare_number(name, a, b, failures):
    d = abs(float(a) - float(b))
    if d > TOL:
        failures.append({
            "check": name, "reproduced": float(a),
            "reference": float(b), "absolute_difference": d,
        })
    return d


def main():
    for p in (DATA_FILE, RBF_FILE, REFERENCE_FILE):
        require(p.is_file(), f"Missing required file: {p}")

    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    rbf = json.loads(RBF_FILE.read_text(encoding="utf-8"))
    ref = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))

    require(sha256(DATA_FILE) == rbf["dataset_sha256"],
            "Dataset fingerprint differs from RBF reference.")
    require(sha256(RBF_FILE) == ref["reference_rbf_results_sha256"],
            "RBF result fingerprint differs from comparison reference.")
    require(len(records) == ref["records"] == 1044, "Record count mismatch.")
    require(ref["zones"] == ZONES, "Zone order mismatch.")
    require(ref["grouping_variable"] == "background_id",
            "Unexpected grouping variable.")
    require(ref["random_state"] == RANDOM_STATE, "Random state mismatch.")
    require(ref["n_estimators"] == N_ESTIMATORS, "Estimator count mismatch.")
    require(ref["tree_hyperparameter_grid"]["max_features"] == MAX_FEATURES_GRID,
            "max_features grid mismatch.")
    require(ref["tree_hyperparameter_grid"]["min_samples_leaf"] == MIN_SAMPLES_LEAF_GRID,
            "min_samples_leaf grid mismatch.")

    x = np.asarray([r["predictors"] for r in records], dtype=float)
    y = np.asarray([[r["zones"][z] for z in ZONES] for r in records], dtype=float)
    groups = np.asarray([r["background_id"] for r in records])
    combos = np.asarray([r["combination"] for r in records])
    require(x.shape == (1044, 13) and y.shape == (1044, 32),
            "Unexpected X/Y dimensions.")
    require(np.all(np.isfinite(x)) and np.all(np.isfinite(y)),
            "Non-finite data detected.")
    require(np.array_equal(y, np.asarray(rbf["actual"], dtype=float)),
            "Targets differ from RBF reference.")
    require(np.array_equal(groups, np.asarray(rbf["groups"])),
            "Group ordering differs from RBF reference.")
    require(np.array_equal(combos, np.asarray(rbf["combinations"])),
            "Combination ordering differs from RBF reference.")

    assignments = rbf["record_fold_assignments"]
    fold_ids = np.asarray([a["outer_fold"] for a in assignments], dtype=int)
    require(np.array_equal(
        np.asarray([a["record_index"] for a in assignments]), np.arange(len(records))
    ), "Record-index mapping mismatch.")
    require(np.array_equal(
        np.asarray([a["background_id"] for a in assignments]), groups
    ), "Assignment background IDs mismatch.")
    for group in np.unique(groups):
        require(len(set(fold_ids[groups == group])) == 1,
                f"Background leakage across folds: {group}")

    preds = {
        "rbf": np.asarray(rbf["predictions"], dtype=float),
        "rbf_clipped": np.clip(np.asarray(rbf["predictions"], dtype=float), 0, 1),
        "random_forest": np.full_like(y, np.nan),
        "extra_trees": np.full_like(y, np.nan),
        "mean_baseline": np.full_like(y, np.nan),
    }

    failures = []
    fold_audits = []
    for fold in sorted(np.unique(fold_ids)):
        test = np.where(fold_ids == fold)[0]
        train = np.where(fold_ids != fold)[0]
        train_groups, test_groups = set(groups[train]), set(groups[test])
        require(not train_groups.intersection(test_groups),
                f"Outer fold {fold}: group leakage.")
        saved_fold = next(f for f in ref["fold_results"] if f["fold"] == int(fold))
        require(set(saved_fold["test_background_ids"]) == test_groups,
                f"Outer fold {fold}: test background IDs differ.")
        require(len(train) == saved_fold["train_records"]
                and len(test) == saved_fold["test_records"],
                f"Outer fold {fold}: record counts differ.")

        fold_audit = {"fold": int(fold), "models": {}}
        for model_type in ("random_forest", "extra_trees"):
            params, inner_score, search = tune(
                model_type, x[train], y[train], groups[train]
            )
            saved = saved_fold[model_type]
            require(params == saved["selected_parameters"],
                    f"Fold {fold} {model_type}: selected parameters differ.")
            compare_number(
                f"fold_{fold}_{model_type}_best_inner_mae",
                inner_score, saved["best_inner_mae"], failures
            )
            require(len(search) == len(saved["hyperparameter_search"]) == 6,
                    f"Fold {fold} {model_type}: grid size mismatch.")
            max_grid_diff = 0.0
            for i, (cur, old) in enumerate(zip(search, saved["hyperparameter_search"])):
                require(cur["max_features"] == old["max_features"]
                        and cur["min_samples_leaf"] == old["min_samples_leaf"],
                        f"Fold {fold} {model_type}: grid ordering mismatch.")
                max_grid_diff = max(
                    max_grid_diff,
                    compare_number(
                        f"fold_{fold}_{model_type}_grid_{i}_mean",
                        cur["mean_inner_mae"], old["mean_inner_mae"], failures
                    )
                )
                for j, (a, b) in enumerate(zip(cur["inner_fold_mae"], old["inner_fold_mae"])):
                    compare_number(
                        f"fold_{fold}_{model_type}_grid_{i}_inner_{j}",
                        a, b, failures
                    )

            model = make_tree(
                model_type, params["max_features"], params["min_samples_leaf"]
            )
            model.fit(x[train], y[train])
            p = model.predict(x[test])
            preds[model_type][test] = p
            fm = metrics(y[test], p)
            for key, value in fm.items():
                compare_number(
                    f"fold_{fold}_{model_type}_{key}",
                    value, saved["outer_metrics"][key], failures
                )
            fold_audit["models"][model_type] = {
                "selected_parameters": params,
                "best_inner_mae": inner_score,
                "max_inner_grid_score_difference": max_grid_diff,
                "outer_metrics": fm,
            }

        zone_means = np.mean(y[train], axis=0)
        baseline = np.tile(zone_means, (len(test), 1))
        preds["mean_baseline"][test] = baseline
        bm = metrics(y[test], baseline)
        for key, value in bm.items():
            compare_number(
                f"fold_{fold}_mean_baseline_{key}",
                value, saved_fold["mean_baseline"]["outer_metrics"][key], failures
            )
        fold_audit["models"]["mean_baseline"] = {"outer_metrics": bm}
        fold_audits.append(fold_audit)
        print(f"Fold {fold}/5 reproduced.")

    # Compare all full prediction matrices, not only their aggregate scores.
    prediction_differences = {}
    for name in MODELS:
        saved = np.asarray(ref["predictions"][name], dtype=float)
        require(saved.shape == preds[name].shape, f"{name}: prediction shape mismatch.")
        diff = np.abs(preds[name] - saved)
        max_diff = float(np.max(diff))
        mismatch_count = int(np.sum(diff > TOL))
        prediction_differences[name] = {
            "max_abs_difference": max_diff,
            "mismatch_count": mismatch_count,
            "n_predictions": int(diff.size),
        }
        if max_diff > TOL:
            failures.append({
                "check": f"{name}_full_prediction_matrix",
                "max_abs_difference": max_diff,
                "mismatch_count": mismatch_count,
            })

    overall = {}
    for name in MODELS:
        overall[name] = metrics(y, preds[name])
        for key, value in overall[name].items():
            compare_number(
                f"overall_{name}_{key}", value, ref["overall"][name][key], failures
            )

    # Independently recompute each zone's winner and compare all per-zone MAEs.
    zone_winners = {}
    zone_mae_differences = {}
    for j, zone in enumerate(ZONES):
        scores = {
            name: float(np.mean(np.abs(y[:, j] - preds[name][:, j])))
        for name in MODELS
        }
        saved_row = ref["zone_comparison_table"][j]
        for name in MODELS:
            compare_number(
                f"zone_{zone}_{name}_mae",
                scores[name], saved_row[f"{name}_mae"], failures
            )
        winner = min(scores, key=scores.get)
        saved_winner = ref["best_model_per_zone"][j]["best_model"]
        require(saved_winner == winner,
                f"Zone {zone}: best model differs ({winner} vs {saved_winner}).")
        zone_winners[winner] = zone_winners.get(winner, 0) + 1
        zone_mae_differences[zone] = scores

    audit = {
        "audit": "independent_expanded_zone_model_comparison_reproduction",
        "status": "PASS" if not failures else "FAIL",
        "dataset_sha256": sha256(DATA_FILE),
        "rbf_reference_sha256": sha256(RBF_FILE),
        "comparison_reference_sha256": sha256(REFERENCE_FILE),
        "records": len(records),
        "backgrounds": int(len(np.unique(groups))),
        "outer_folds": int(len(np.unique(fold_ids))),
        "inner_folds": INNER_SPLITS,
        "tree_grid_evaluations_per_fold_per_model": 6,
        "random_state": RANDOM_STATE,
        "n_estimators": N_ESTIMATORS,
        "prediction_differences": prediction_differences,
        "reproduced_overall_metrics": overall,
        "reference_overall_metrics": ref["overall"],
        "zone_winner_counts": zone_winners,
        "fold_results": fold_audits,
        "failures": failures,
    }
    OUTPUT_FILE.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print("\nMODEL-COMPARISON REPRODUCTION:", audit["status"])
    print("Full prediction differences:", json.dumps(prediction_differences))
    print("Zone winner counts:", json.dumps(zone_winners, sort_keys=True))
    print("Audit report:", OUTPUT_FILE)
    if failures:
        print("Failed checks:", len(failures))
        for failure in failures[:20]:
            print(failure)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
