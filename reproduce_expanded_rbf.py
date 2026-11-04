#!/usr/bin/env python3
"""
Independent reproduction audit for the expanded scaly RBF nested-CV analysis.

This script does NOT overwrite the reference results. It:
1. Loads the expanded dataset and saved RBF reference output.
2. Reconstructs all 13 predictors from scoring.py and checks them against
   the predictors stored in the dataset (tolerance: 1e-10).
3. Re-runs the exact 5-fold outer / 4-fold inner GroupKFold procedure.
4. Repeats the 49 alpha/gamma combinations in every outer training fold.
5. Compares fold membership, hyperparameter selections, inner-CV scores,
   all 33,408 raw predictions, clipped predictions, and aggregate metrics.
6. Writes a separate reproduction audit JSON.

Run from the repository root:
    python reproduce_expanded_rbf.py

Required files:
    presentation_scaly.json
    scoring.py
    targeted_interaction_results_expanded.json
    rbf_expanded_nested_cv_results_expanded.json

Dependencies:
    pip install numpy scikit-learn
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.kernel_ridge import KernelRidge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from scoring import load_presentation, score_findings


ROOT = Path(__file__).resolve().parent
PRESENTATION_FILE = ROOT / "presentation_scaly.json"
DATA_FILE = ROOT / "targeted_interaction_results_expanded.json"
REFERENCE_FILE = ROOT / "rbf_expanded_nested_cv_results_expanded.json"
OUTPUT_FILE = ROOT / "rbf_expanded_reproduction_audit.json"

OUTER_SPLITS = 5
INNER_SPLITS = 4
PREDICTOR_TOLERANCE = 1e-10
PREDICTION_TOLERANCE = 1e-10
METRIC_TOLERANCE = 1e-10

ALPHAS = [1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 0.01, 0.1]
GAMMAS = [0.0001, 0.0003, 0.001, 0.003, 0.01, 0.03, 0.1]

PREDICTORS = [
    "ast", "ldrug", "lp", "mf", "num", "pr", "prp",
    "pso", "reac", "scle", "seb", "syph", "tin",
]
ZONES = [
    "abdo", "ankle", "antecub", "axilla", "back", "buttock",
    "calf", "chest", "conj", "ear", "elbow", "face", "foot",
    "forearm", "genital", "groin", "hand", "knee", "nail",
    "neck", "oral", "palm", "perianal", "poplit", "scalp",
    "shin", "shoulder", "sole", "thigh", "umbil", "web", "wrist",
]


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def make_model(alpha, gamma):
    return Pipeline([
        ("scale", StandardScaler()),
        ("model", KernelRidge(
            alpha=float(alpha),
            kernel="rbf",
            gamma=float(gamma),
        )),
    ])


def metric_bundle(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    error = predicted - actual
    clipped = np.clip(predicted, 0.0, 1.0)
    clipped_error = clipped - actual
    return {
        "raw_mae": float(np.mean(np.abs(error))),
        "raw_rmse": float(np.sqrt(np.mean(error ** 2))),
        "raw_max_abs_error": float(np.max(np.abs(error))),
        "raw_bias": float(np.mean(error)),
        "clipped_mae": float(np.mean(np.abs(clipped_error))),
        "clipped_rmse": float(np.sqrt(np.mean(clipped_error ** 2))),
        "clipped_max_abs_error": float(np.max(np.abs(clipped_error))),
        "predictions_above_one": int(np.sum(predicted > 1.0)),
        "predictions_below_zero": int(np.sum(predicted < 0.0)),
        "n_values": int(actual.size),
    }


def reconstruct_predictors(presentation, answers, record_number):
    result = score_findings(presentation, answers)
    probability_map = {
        row["id"]: float(row["probability"])
        for row in result["ranked"]
    }
    missing = [name for name in PREDICTORS if name not in probability_map]
    require(not missing,
            f"Record {record_number}: missing predictors {missing}")
    values = np.asarray([probability_map[name] for name in PREDICTORS],
                        dtype=float)
    require(np.all(np.isfinite(values)),
            f"Record {record_number}: non-finite reconstructed predictors")
    return values


def load_inputs():
    for path in (PRESENTATION_FILE, DATA_FILE, REFERENCE_FILE):
        require(path.is_file(), f"Required file not found: {path}")

    presentation = load_presentation(str(PRESENTATION_FILE))
    require(presentation.get("id") == "scaly",
            "Unexpected presentation ID; expected 'scaly'.")
    require(len(presentation["find"]) == 40,
            f"Expected 40 findings; got {len(presentation['find'])}.")

    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    reference = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
    actual_dataset_sha = sha256_file(DATA_FILE)
    actual_presentation_sha = sha256_file(PRESENTATION_FILE)
    require(actual_dataset_sha == reference.get("dataset_sha256"),
            "Expanded dataset SHA-256 does not match the reference metadata.")
    require(actual_presentation_sha == reference.get("presentation_sha256"),
            "Presentation SHA-256 does not match the reference metadata.")
    require(isinstance(records, list) and len(records) > 0,
            "Expanded dataset must be a non-empty JSON list.")
    return presentation, records, reference


def build_arrays(presentation, records, skip_score_reconstruction=False):
    X_stored, Y, groups, combinations = [], [], [], []
    predictor_max_diff = 0.0
    predictor_mismatch_count = 0

    for number, record in enumerate(records, start=1):
        for field in ("background_id", "answers", "predictors",
                      "combination", "zones"):
            require(field in record,
                    f"Record {number}: missing required field '{field}'.")

        stored_x = np.asarray(record["predictors"], dtype=float)
        require(stored_x.shape == (len(PREDICTORS),),
                f"Record {number}: expected 13 stored predictors.")
        require(np.all(np.isfinite(stored_x)),
                f"Record {number}: non-finite stored predictor.")
        if not skip_score_reconstruction:
            reconstructed = reconstruct_predictors(
                presentation, record["answers"], number
            )
            difference = np.abs(reconstructed - stored_x)
            predictor_max_diff = max(
                predictor_max_diff, float(np.max(difference))
            )
            predictor_mismatch_count += int(
                np.sum(difference > PREDICTOR_TOLERANCE)
            )

        missing_zones = [zone for zone in ZONES if zone not in record["zones"]]
        require(not missing_zones,
                f"Record {number}: missing zones {missing_zones}")
        y = np.asarray([record["zones"][zone] for zone in ZONES], dtype=float)
        require(np.all(np.isfinite(y)),
                f"Record {number}: non-finite target.")

        X_stored.append(stored_x)
        Y.append(y)
        groups.append(str(record["background_id"]))
        combinations.append(str(record["combination"]))

    X = np.asarray(X_stored, dtype=float)
    Y = np.asarray(Y, dtype=float)
    groups = np.asarray(groups)
    combinations = np.asarray(combinations)

    require(X.shape == (len(records), len(PREDICTORS)),
            "Unexpected predictor matrix shape.")
    require(Y.shape == (len(records), len(ZONES)),
            "Unexpected target matrix shape.")
    require(len(np.unique(groups)) == 261,
            f"Expected 261 backgrounds; got {len(np.unique(groups))}.")

    counts = {}
    for group in groups:
        counts[group] = counts.get(group, 0) + 1
    require(all(count == 4 for count in counts.values()),
            "Every background must have exactly four factorial records.")

    require(predictor_mismatch_count == 0,
            "Reconstructed predictors differ from stored predictors by "
            f"more than {PREDICTOR_TOLERANCE}; "
            f"mismatched values={predictor_mismatch_count}, "
            f"max difference={predictor_max_diff:.17g}")

    return X, Y, groups, combinations, {
        "predictor_reconstruction_performed": not skip_score_reconstruction,
        "predictor_values_checked": 0 if skip_score_reconstruction else int(X.size),
        "predictor_mismatch_count": predictor_mismatch_count,
        "predictor_max_abs_difference": predictor_max_diff,
        "predictor_tolerance": PREDICTOR_TOLERANCE,
    }


def tune_rbf(X_train, Y_train, groups_train):
    inner_cv = GroupKFold(n_splits=INNER_SPLITS)
    search = []
    best_score = np.inf
    best_alpha = None
    best_gamma = None

    for alpha in ALPHAS:
        for gamma in GAMMAS:
            fold_scores = []
            for inner_train, inner_valid in inner_cv.split(
                    X_train, Y_train, groups_train):
                train_groups = set(groups_train[inner_train])
                valid_groups = set(groups_train[inner_valid])
                require(not train_groups.intersection(valid_groups),
                        "Background leakage in inner CV.")

                model = make_model(alpha, gamma)
                model.fit(X_train[inner_train], Y_train[inner_train])
                prediction = model.predict(X_train[inner_valid])
                fold_scores.append(float(mean_absolute_error(
                    Y_train[inner_valid], prediction
                )))

            mean_score = float(np.mean(fold_scores))
            search.append({
                "alpha": float(alpha),
                "gamma": float(gamma),
                "mean_inner_mae": mean_score,
                "inner_fold_mae": fold_scores,
            })
            # Strict '<' deliberately preserves the original grid-order
            # tie-breaking behavior.
            if mean_score < best_score:
                best_score = mean_score
                best_alpha = alpha
                best_gamma = gamma

    return best_alpha, best_gamma, best_score, search


def compare_float(name, reproduced, reference, tolerance, failures):
    difference = abs(float(reproduced) - float(reference))
    if difference > tolerance:
        failures.append({
            "check": name,
            "reproduced": float(reproduced),
            "reference": float(reference),
            "absolute_difference": difference,
            "tolerance": tolerance,
        })
    return difference


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-score-reconstruction",
        action="store_true",
        help="Use stored predictors without re-running scoring.py. "
             "Not recommended for the full audit.",
    )
    args = parser.parse_args()

    presentation, records, reference = load_inputs()
    require(reference.get("analysis") == "nested_grouped_cross_validation",
            "Reference file is not the expected nested grouped CV result.")
    require(reference.get("predictors") == PREDICTORS,
            "Reference predictor order differs from this script.")
    require(reference.get("zone_names") == ZONES,
            "Reference zone order differs from this script.")
    require(reference.get("outer_splits") == OUTER_SPLITS
            and reference.get("inner_splits") == INNER_SPLITS,
            "Reference CV split counts differ from this script.")
    require(reference.get("alpha_grid") == ALPHAS
            and reference.get("gamma_grid") == GAMMAS,
            "Reference hyperparameter grids differ from this script.")
    require(reference.get("grouping_variable") == "background_id",
            "Reference grouping variable is not background_id.")

    X, Y, groups, combinations, predictor_audit = build_arrays(
        presentation, records, args.skip_score_reconstruction
    )
    n_records = len(records)
    require(reference.get("records") == n_records,
            "Dataset record count differs from reference.")
    require(reference.get("unique_backgrounds") == len(np.unique(groups)),
            "Unique background count differs from reference.")

    saved_assignments = reference["record_fold_assignments"]
    require(len(saved_assignments) == n_records,
            "Saved fold assignment count differs from dataset.")

    outer_cv = GroupKFold(n_splits=OUTER_SPLITS)
    predictions = np.zeros_like(Y)
    fold_audits = []
    failures = []

    for fold_number, (train_idx, test_idx) in enumerate(
            outer_cv.split(X, Y, groups), start=1):
        train_groups = set(groups[train_idx])
        test_groups = set(groups[test_idx])
        require(not train_groups.intersection(test_groups),
                f"Outer fold {fold_number}: group leakage.")

        for index in test_idx:
            saved = saved_assignments[int(index)]
            require(saved["record_index"] == int(index),
                    f"Fold {fold_number}: saved record index mismatch.")
            require(saved["background_id"] == groups[index],
                    f"Fold {fold_number}: saved background ID mismatch.")
            require(saved["outer_fold"] == fold_number,
                    f"Fold {fold_number}: saved fold assignment mismatch.")

        alpha, gamma, inner_score, search = tune_rbf(
            X[train_idx], Y[train_idx], groups[train_idx]
        )
        model = make_model(alpha, gamma)
        model.fit(X[train_idx], Y[train_idx])
        fold_prediction = model.predict(X[test_idx])
        predictions[test_idx] = fold_prediction

        fold_reference = next(
            item for item in reference["fold_results"]
            if item["fold"] == fold_number
        )
        require(int(fold_reference["train_records"]) == len(train_idx),
                f"Fold {fold_number}: train record count mismatch.")
        require(int(fold_reference["test_records"]) == len(test_idx),
                f"Fold {fold_number}: test record count mismatch.")
        require(int(fold_reference["train_backgrounds"]) == len(train_groups),
                f"Fold {fold_number}: train background count mismatch.")
        require(int(fold_reference["test_backgrounds"]) == len(test_groups),
                f"Fold {fold_number}: test background count mismatch.")
        require(set(fold_reference["train_background_ids"]) == train_groups,
                f"Fold {fold_number}: training background IDs differ.")
        require(set(fold_reference["test_background_ids"]) == test_groups,
                f"Fold {fold_number}: test background IDs differ.")

        require(float(fold_reference["alpha"]) == float(alpha),
                f"Fold {fold_number}: selected alpha differs "
                f"(reproduced={alpha}, reference={fold_reference['alpha']}).")
        require(float(fold_reference["gamma"]) == float(gamma),
                f"Fold {fold_number}: selected gamma differs "
                f"(reproduced={gamma}, reference={fold_reference['gamma']}).")
        compare_float(
            f"fold_{fold_number}_best_inner_mae",
            inner_score, fold_reference["best_inner_mae"],
            METRIC_TOLERANCE, failures
        )

        reference_search = fold_reference["hyperparameter_search"]
        require(len(reference_search) == len(search) == 49,
                f"Fold {fold_number}: expected 49 grid evaluations.")
        max_inner_difference = 0.0
        for current, saved in zip(search, reference_search):
            require(current["alpha"] == saved["alpha"]
                    and current["gamma"] == saved["gamma"],
                    f"Fold {fold_number}: hyperparameter grid order mismatch.")
            max_inner_difference = max(
                max_inner_difference,
                abs(current["mean_inner_mae"] - saved["mean_inner_mae"])
            )
            require(len(current["inner_fold_mae"])
                    == len(saved["inner_fold_mae"]) == INNER_SPLITS,
                    f"Fold {fold_number}: expected four inner folds.")
            for inner_number, (a, b) in enumerate(zip(
                    current["inner_fold_mae"], saved["inner_fold_mae"]), 1):
                compare_float(
                    f"fold_{fold_number}_grid_{current['alpha']}_{current['gamma']}"
                    f"_inner_{inner_number}",
                    a, b, METRIC_TOLERANCE, failures
                )

        fold_metrics = metric_bundle(Y[test_idx], fold_prediction)
        ref_metrics = fold_reference["outer_metrics"]
        for metric in ("raw_mae", "raw_rmse", "clipped_mae", "clipped_rmse"):
            compare_float(
                f"fold_{fold_number}_{metric}",
                fold_metrics[metric], ref_metrics[metric],
                METRIC_TOLERANCE, failures
            )

        fold_audits.append({
            "fold": fold_number,
            "train_records": int(len(train_idx)),
            "test_records": int(len(test_idx)),
            "train_backgrounds": int(len(train_groups)),
            "test_backgrounds": int(len(test_groups)),
            "alpha": float(alpha),
            "gamma": float(gamma),
            "best_inner_mae": float(inner_score),
            "hyperparameter_combinations": len(search),
            "max_inner_grid_score_difference": float(max_inner_difference),
            "outer_metrics": fold_metrics,
        })
        print(
            f"Fold {fold_number}/5 complete | alpha={alpha:g} "
            f"gamma={gamma:g} | outer MAE={fold_metrics['raw_mae']:.12f}"
        )

    reference_predictions = np.asarray(reference["predictions"], dtype=float)
    reference_clipped = np.asarray(
        reference["clipped_predictions"], dtype=float
    )
    reference_actual = np.asarray(reference["actual"], dtype=float)

    require(reference_predictions.shape == predictions.shape,
            "Saved prediction matrix has unexpected shape.")
    require(reference_actual.shape == Y.shape,
            "Saved actual matrix has unexpected shape.")

    actual_difference = float(np.max(np.abs(reference_actual - Y)))
    require(actual_difference == 0.0,
            f"Actual target matrix differs; max difference={actual_difference}")

    clipped_predictions = np.clip(predictions, 0.0, 1.0)
    raw_prediction_difference = float(
        np.max(np.abs(predictions - reference_predictions))
    )
    clipped_prediction_difference = float(
        np.max(np.abs(clipped_predictions - reference_clipped))
    )
    raw_prediction_mismatch_count = int(np.sum(
        np.abs(predictions - reference_predictions) > PREDICTION_TOLERANCE
    ))
    clipped_prediction_mismatch_count = int(np.sum(
        np.abs(clipped_predictions - reference_clipped) > PREDICTION_TOLERANCE
    ))

    if raw_prediction_difference > PREDICTION_TOLERANCE:
        failures.append({
            "check": "all_raw_predictions",
            "max_abs_difference": raw_prediction_difference,
            "mismatch_count": raw_prediction_mismatch_count,
            "tolerance": PREDICTION_TOLERANCE,
        })
    if clipped_prediction_difference > PREDICTION_TOLERANCE:
        failures.append({
            "check": "all_clipped_predictions",
            "max_abs_difference": clipped_prediction_difference,
            "mismatch_count": clipped_prediction_mismatch_count,
            "tolerance": PREDICTION_TOLERANCE,
        })

    reproduced_metrics = metric_bundle(Y, predictions)
    clipped_reference_metrics = metric_bundle(Y, reference_predictions)
    for key, value in reproduced_metrics.items():
        if isinstance(value, (int, float)):
            compare_float(
                f"overall_{key}", value, reference["overall"][key],
                METRIC_TOLERANCE, failures
            )

    # Independently verify saved clipped predictions and their metrics.
    require(np.allclose(
        reference_clipped,
        np.clip(reference_predictions, 0.0, 1.0),
        rtol=0.0, atol=PREDICTION_TOLERANCE
    ), "Reference clipped predictions are not clip(raw predictions, 0, 1).")

    audit = {
        "audit": "independent_expanded_rbf_nested_cv_reproduction",
        "status": "PASS" if not failures else "FAIL",
        "dataset_file": DATA_FILE.name,
        "reference_file": REFERENCE_FILE.name,
        "dataset_sha256": sha256_file(DATA_FILE),
        "presentation_sha256": sha256_file(PRESENTATION_FILE),
        "reference_sha256": sha256_file(REFERENCE_FILE),
        "records": int(n_records),
        "unique_backgrounds": int(len(np.unique(groups))),
        "predictors": PREDICTORS,
        "zones": ZONES,
        "outer_splits": OUTER_SPLITS,
        "inner_splits": INNER_SPLITS,
        "alpha_grid": ALPHAS,
        "gamma_grid": GAMMAS,
        "predictor_audit": predictor_audit,
        "actual_matrix_max_abs_difference": actual_difference,
        "raw_prediction_max_abs_difference": raw_prediction_difference,
        "raw_prediction_mismatch_count": raw_prediction_mismatch_count,
        "clipped_prediction_max_abs_difference": clipped_prediction_difference,
        "clipped_prediction_mismatch_count": clipped_prediction_mismatch_count,
        "prediction_tolerance": PREDICTION_TOLERANCE,
        "reproduced_overall_metrics": reproduced_metrics,
        "reference_overall_metrics": reference["overall"],
        "fold_results": fold_audits,
        "failures": failures,
    }

    OUTPUT_FILE.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("EXPANDED RBF REPRODUCTION AUDIT:", audit["status"])
    print("=" * 72)
    print("Records:", n_records)
    print("Backgrounds:", len(np.unique(groups)))
    print("Predictor max absolute difference:",
          f"{predictor_audit['predictor_max_abs_difference']:.17g}")
    print("Raw prediction max absolute difference:",
          f"{raw_prediction_difference:.17g}")
    print("Raw prediction mismatches:",
          raw_prediction_mismatch_count)
    print("Clipped prediction max absolute difference:",
          f"{clipped_prediction_difference:.17g}")
    print("Clipped prediction mismatches:",
          clipped_prediction_mismatch_count)
    print("Reproduced raw MAE:", f"{reproduced_metrics['raw_mae']:.12f}")
    print("Reproduced clipped MAE:",
          f"{reproduced_metrics['clipped_mae']:.12f}")
    print("Audit report:", OUTPUT_FILE.resolve())

    if failures:
        print("FAILED CHECKS:", len(failures))
        for failure in failures[:20]:
            print(" -", failure)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
