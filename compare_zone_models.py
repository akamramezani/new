#!/usr/bin/env python3

import json
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor
from sklearn.model_selection import GroupKFold
from sklearn.metrics import mean_absolute_error, mean_squared_error


# ============================================================
# 1. CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent

DATA_FILE = ROOT / "targeted_interaction_results_expanded.json"

RBF_RESULTS_FILE = (
    ROOT / "rbf_expanded_nested_cv_results_expanded.json"
)

OUTPUT_FILE = ROOT / "zone_model_comparison_results.json"

INNER_SPLITS = 4
RANDOM_STATE = 20261104

N_ESTIMATORS = 300

MAX_FEATURES_GRID = [0.7, 1.0]
MIN_SAMPLES_LEAF_GRID = [1, 2, 4]

ZONE_NAMES = [
    "abdo", "ankle", "antecub", "axilla", "back",
    "buttock", "calf", "chest", "conj", "ear",
    "elbow", "face", "foot", "forearm", "genital",
    "groin", "hand", "knee", "nail", "neck",
    "oral", "palm", "perianal", "poplit", "scalp",
    "shin", "shoulder", "sole", "thigh", "umbil",
    "web", "wrist"
]

MODEL_NAMES = [
    "rbf",
    "rbf_clipped",
    "random_forest",
    "extra_trees",
    "mean_baseline"
]


# ============================================================
# 2. HELPER FUNCTIONS
# ============================================================

def sha256_file(path):

    digest = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def calculate_metrics(actual, predicted):

    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    error = predicted - actual

    clipped = np.clip(predicted, 0, 1)
    clipped_error = clipped - actual

    return {
        "raw_mae": float(np.mean(np.abs(error))),

        "raw_rmse": float(
            np.sqrt(np.mean(error ** 2))
        ),

        "raw_max_abs_error": float(
            np.max(np.abs(error))
        ),

        "raw_bias": float(
            np.mean(error)
        ),

        "clipped_mae": float(
            np.mean(np.abs(clipped_error))
        ),

        "clipped_rmse": float(
            np.sqrt(np.mean(clipped_error ** 2))
        ),

        "predictions_above_one": int(
            np.sum(predicted > 1)
        ),

        "predictions_below_zero": int(
            np.sum(predicted < 0)
        ),

        "n_values": int(actual.size)
    }


def create_tree_model(model_type, max_features, min_samples_leaf):

    common = {
        "n_estimators": N_ESTIMATORS,
        "max_features": max_features,
        "min_samples_leaf": min_samples_leaf,
        "random_state": RANDOM_STATE,
        "n_jobs": -1
    }

    if model_type == "random_forest":

        return RandomForestRegressor(
            **common
        )

    if model_type == "extra_trees":

        return ExtraTreesRegressor(
            **common
        )

    raise ValueError(f"Unknown model: {model_type}")


# ============================================================
# 3. INNER HYPERPARAMETER TUNING
# ============================================================

def tune_tree_model(
    model_type,
    X_train,
    Y_train,
    groups_train
):

    inner_cv = GroupKFold(
        n_splits=INNER_SPLITS
    )

    best_score = np.inf
    best_parameters = None

    search_results = []

    for max_features in MAX_FEATURES_GRID:

        for min_samples_leaf in MIN_SAMPLES_LEAF_GRID:

            fold_scores = []

            for inner_train, inner_valid in inner_cv.split(
                X_train,
                Y_train,
                groups_train
            ):

                train_groups = set(
                    groups_train[inner_train]
                )

                valid_groups = set(
                    groups_train[inner_valid]
                )

                if train_groups.intersection(valid_groups):

                    raise RuntimeError(
                        "Background leakage during inner CV."
                    )

                model = create_tree_model(
                    model_type,
                    max_features,
                    min_samples_leaf
                )

                model.fit(
                    X_train[inner_train],
                    Y_train[inner_train]
                )

                predictions = model.predict(
                    X_train[inner_valid]
                )

                score = np.mean(
                    np.abs(
                        predictions - Y_train[inner_valid]
                    )
                )

                fold_scores.append(float(score))

            mean_score = float(
                np.mean(fold_scores)
            )

            parameters = {
                "max_features": float(max_features),
                "min_samples_leaf": int(min_samples_leaf)
            }

            search_results.append({
                **parameters,
                "mean_inner_mae": mean_score,
                "inner_fold_mae": fold_scores
            })

            if mean_score < best_score:

                best_score = mean_score
                best_parameters = parameters

    return (
        best_parameters,
        best_score,
        search_results
    )


# ============================================================
# 4. CHECK FILES
# ============================================================

print("=" * 75)
print("RBF vs RANDOM FOREST vs EXTRA TREES")
print("=" * 75)

for path in [
    DATA_FILE,
    RBF_RESULTS_FILE
]:

    if not path.exists():
        raise FileNotFoundError(path)

if OUTPUT_FILE.exists():

    raise FileExistsError(
        f"Output already exists: {OUTPUT_FILE}\n"
        "Rename it before running again."
    )


# ============================================================
# 5. LOAD DATA AND EXISTING RBF RESULTS
# ============================================================

with open(DATA_FILE, "r", encoding="utf-8") as f:
    records = json.load(f)

with open(RBF_RESULTS_FILE, "r", encoding="utf-8") as f:
    rbf_results = json.load(f)

print("Dataset records:", len(records))

# Verify that the existing RBF results correspond to this exact dataset.
dataset_hash = sha256_file(DATA_FILE)

if dataset_hash != rbf_results["dataset_sha256"]:

    raise ValueError(
        "Dataset SHA256 does not match the dataset used "
        "for the existing RBF analysis."
    )

if len(records) != rbf_results["records"]:

    raise ValueError("Record count mismatch.")

if rbf_results["zone_names"] != ZONE_NAMES:

    raise ValueError("Zone ordering mismatch.")

if rbf_results["grouping_variable"] != "background_id":

    raise ValueError("Unexpected grouping variable.")


# ============================================================
# 6. RECONSTRUCT MODEL MATRICES
# ============================================================

print("\nPreparing predictor and target matrices...")

X = np.asarray(
    [
        record["predictors"]
        for record in records
    ],
    dtype=float
)

Y = np.asarray(
    [
        [
            record["zones"][zone]
            for zone in ZONE_NAMES
        ]
        for record in records
    ],
    dtype=float
)

groups = np.asarray(
    [
        record["background_id"]
        for record in records
    ]
)

combinations = np.asarray(
    [
        record["combination"]
        for record in records
    ]
)

if X.shape[1] != 13:

    raise ValueError(
        f"Expected 13 predictors; found {X.shape[1]}"
    )

if Y.shape[1] != 32:

    raise ValueError(
        f"Expected 32 zones; found {Y.shape[1]}"
    )

if not np.all(np.isfinite(X)):

    raise ValueError("Non-finite predictors detected.")

if not np.all(np.isfinite(Y)):

    raise ValueError("Non-finite targets detected.")


# Check that data ordering matches the previous analysis.
if not np.allclose(
    Y,
    np.asarray(rbf_results["actual"]),
    atol=1e-12,
    rtol=0
):

    raise ValueError(
        "Target matrix does not match the existing RBF results."
    )

if not np.array_equal(
    groups,
    np.asarray(rbf_results["groups"])
):

    raise ValueError(
        "Background ordering does not match the RBF results."
    )

if not np.array_equal(
    combinations,
    np.asarray(rbf_results["combinations"])
):

    raise ValueError(
        "Combination ordering does not match the RBF results."
    )


# ============================================================
# 7. REUSE EXACT OUTER FOLD ASSIGNMENTS
# ============================================================

print("\nChecking saved outer-fold assignments...")

assignments = rbf_results["record_fold_assignments"]

if len(assignments) != len(records):

    raise ValueError("Fold assignment count mismatch.")

fold_ids = np.asarray(
    [
        item["outer_fold"]
        for item in assignments
    ],
    dtype=int
)

if not np.array_equal(
    np.asarray([item["record_index"] for item in assignments]),
    np.arange(len(records))
):

    raise ValueError("Record ordering mismatch in fold assignments.")

if not np.array_equal(
    np.asarray([item["background_id"] for item in assignments]),
    groups
):

    raise ValueError("Background IDs mismatch in fold assignments.")

outer_folds = sorted(
    np.unique(fold_ids).tolist()
)

if len(outer_folds) != 5:

    raise ValueError("Expected exactly five outer folds.")

# Every background must belong to one outer fold only.
background_fold = {}

for i, background in enumerate(groups):

    fold = int(fold_ids[i])

    previous = background_fold.setdefault(
        background,
        fold
    )

    if previous != fold:

        raise ValueError(
            f"Background {background} appears in multiple folds."
        )

print("Outer folds:", outer_folds)
print("Unique backgrounds:", len(background_fold))
print("Background leakage: none")


# ============================================================
# 8. LOAD EXISTING RBF PREDICTIONS
# ============================================================

rbf_predictions = np.asarray(
    rbf_results["predictions"],
    dtype=float
)

if rbf_predictions.shape != Y.shape:

    raise ValueError("RBF prediction dimensions do not match.")

rbf_clipped_predictions = np.clip(
    rbf_predictions,
    0,
    1
)


# ============================================================
# 9. INITIALIZE OTHER MODEL PREDICTIONS
# ============================================================

rf_predictions = np.full_like(
    Y,
    np.nan,
    dtype=float
)

et_predictions = np.full_like(
    Y,
    np.nan,
    dtype=float
)

baseline_predictions = np.full_like(
    Y,
    np.nan,
    dtype=float
)

fold_results = []


# ============================================================
# 10. OUTER FOLD MODEL COMPARISON
# ============================================================

for fold in outer_folds:

    print("\n" + "=" * 75)
    print(f"OUTER FOLD {fold}")
    print("=" * 75)

    test_idx = np.where(
        fold_ids == fold
    )[0]

    train_idx = np.where(
        fold_ids != fold
    )[0]

    train_groups = set(groups[train_idx])
    test_groups = set(groups[test_idx])

    if train_groups.intersection(test_groups):

        raise RuntimeError(
            f"Leakage in outer fold {fold}."
        )

    X_train = X[train_idx]
    Y_train = Y[train_idx]

    X_test = X[test_idx]

    groups_train = groups[train_idx]

    print("Training records:", len(train_idx))
    print("Testing records:", len(test_idx))
    print("Training backgrounds:", len(train_groups))
    print("Testing backgrounds:", len(test_groups))

    fold_output = {
        "fold": int(fold),
        "train_records": int(len(train_idx)),
        "test_records": int(len(test_idx)),
        "train_backgrounds": int(len(train_groups)),
        "test_backgrounds": int(len(test_groups)),
        "test_background_ids": sorted(test_groups)
    }

    # --------------------------------------------------------
    # A. RANDOM FOREST
    # --------------------------------------------------------

    print("\nTuning Random Forest...")

    (
        rf_parameters,
        rf_inner_score,
        rf_search
    ) = tune_tree_model(
        "random_forest",
        X_train,
        Y_train,
        groups_train
    )

    rf_model = create_tree_model(
        "random_forest",
        rf_parameters["max_features"],
        rf_parameters["min_samples_leaf"]
    )

    rf_model.fit(
        X_train,
        Y_train
    )

    rf_pred = rf_model.predict(
        X_test
    )

    rf_predictions[test_idx] = rf_pred

    rf_fold_metrics = calculate_metrics(
        Y[test_idx],
        rf_pred
    )

    print("RF parameters:", rf_parameters)
    print("RF inner MAE:", rf_inner_score)
    print("RF outer MAE:", rf_fold_metrics["raw_mae"])

    fold_output["random_forest"] = {
        "selected_parameters": rf_parameters,
        "best_inner_mae": rf_inner_score,
        "outer_metrics": rf_fold_metrics,
        "hyperparameter_search": rf_search
    }

    # --------------------------------------------------------
    # B. EXTRA TREES
    # --------------------------------------------------------

    print("\nTuning Extra Trees...")

    (
        et_parameters,
        et_inner_score,
        et_search
    ) = tune_tree_model(
        "extra_trees",
        X_train,
        Y_train,
        groups_train
    )

    et_model = create_tree_model(
        "extra_trees",
        et_parameters["max_features"],
        et_parameters["min_samples_leaf"]
    )

    et_model.fit(
        X_train,
        Y_train
    )

    et_pred = et_model.predict(
        X_test
    )

    et_predictions[test_idx] = et_pred

    et_fold_metrics = calculate_metrics(
        Y[test_idx],
        et_pred
    )

    print("ET parameters:", et_parameters)
    print("ET inner MAE:", et_inner_score)
    print("ET outer MAE:", et_fold_metrics["raw_mae"])

    fold_output["extra_trees"] = {
        "selected_parameters": et_parameters,
        "best_inner_mae": et_inner_score,
        "outer_metrics": et_fold_metrics,
        "hyperparameter_search": et_search
    }

    # --------------------------------------------------------
    # C. MEAN BASELINE
    # --------------------------------------------------------

    # Predict each zone using its mean in the outer training set.
    zone_means = np.mean(
        Y_train,
        axis=0
    )

    baseline_pred = np.tile(
        zone_means,
        (len(test_idx), 1)
    )

    baseline_predictions[test_idx] = baseline_pred

    baseline_fold_metrics = calculate_metrics(
        Y[test_idx],
        baseline_pred
    )

    fold_output["mean_baseline"] = {
        "outer_metrics": baseline_fold_metrics
    }

    # --------------------------------------------------------
    # D. EXISTING RBF RESULTS
    # --------------------------------------------------------

    fold_output["rbf"] = {
        "outer_metrics": calculate_metrics(
            Y[test_idx],
            rbf_predictions[test_idx]
        )
    }

    fold_output["rbf_clipped"] = {
        "outer_metrics": calculate_metrics(
            Y[test_idx],
            rbf_clipped_predictions[test_idx]
        )
    }

    fold_results.append(fold_output)


# ============================================================
# 11. VERIFY PREDICTION COMPLETENESS
# ============================================================

for name, predictions in [
    ("Random Forest", rf_predictions),
    ("Extra Trees", et_predictions),
    ("Mean baseline", baseline_predictions)
]:

    if not np.all(np.isfinite(predictions)):

        raise RuntimeError(
            f"{name}: missing or invalid predictions."
        )


# ============================================================
# 12. COLLECT ALL MODEL PREDICTIONS
# ============================================================

all_predictions = {

    "rbf": rbf_predictions,

    "rbf_clipped": rbf_clipped_predictions,

    "random_forest": rf_predictions,

    "extra_trees": et_predictions,

    "mean_baseline": baseline_predictions
}


# ============================================================
# 13. OVERALL METRICS
# ============================================================

print("\n" + "=" * 75)
print("OVERALL MODEL COMPARISON")
print("=" * 75)

overall_results = {}

for model_name, predictions in all_predictions.items():

    overall_results[model_name] = calculate_metrics(
        Y,
        predictions
    )

comparison_table = pd.DataFrame([
    {
        "model": name,
        "MAE": values["raw_mae"],
        "RMSE": values["raw_rmse"],
        "Max_error": values["raw_max_abs_error"],
        "Bias": values["raw_bias"],
        "Above_1": values["predictions_above_one"],
        "Below_0": values["predictions_below_zero"]
    }
    for name, values in overall_results.items()
])

comparison_table = comparison_table.sort_values(
    "MAE"
)

print(
    comparison_table.to_string(
        index=False,
        float_format=lambda x: f"{x:.6f}"
    )
)


# ============================================================
# 14. PERFORMANCE BY FACTORIAL COMBINATION
# ============================================================

print("\n" + "=" * 75)
print("PERFORMANCE BY COMBINATION")
print("=" * 75)

combination_results = {}

for combination in ["YY", "YN", "NY", "NN"]:

    mask = combinations == combination

    combination_results[combination] = {}

    for model_name, predictions in all_predictions.items():

        combination_results[combination][model_name] = (
            calculate_metrics(
                Y[mask],
                predictions[mask]
            )
        )

    print("\n", combination)

    for model_name in all_predictions:

        print(
            model_name,
            "MAE:",
            combination_results[combination][model_name]["raw_mae"]
        )


# ============================================================
# 15. PERFORMANCE BY ZONE
# ============================================================

print("\n" + "=" * 75)
print("PERFORMANCE BY ZONE")
print("=" * 75)

per_zone_results = {}

for model_name, predictions in all_predictions.items():

    zone_results = []

    for j, zone in enumerate(ZONE_NAMES):

        zone_metrics = calculate_metrics(
            Y[:, j],
            predictions[:, j]
        )

        zone_results.append({
            "zone": zone,
            **zone_metrics
        })

    per_zone_results[model_name] = zone_results


# Create a compact comparison table for each zone.
zone_comparison = []

for j, zone in enumerate(ZONE_NAMES):

    row = {"zone": zone}

    for model_name, predictions in all_predictions.items():

        row[f"{model_name}_mae"] = float(
            np.mean(
                np.abs(
                    Y[:, j] - predictions[:, j]
                )
            )
        )

    zone_comparison.append(row)


zone_df = pd.DataFrame(zone_comparison)

print(
    zone_df.to_string(
        index=False,
        float_format=lambda x: f"{x:.5f}"
    )
)


# ============================================================
# 16. BEST MODEL PER ZONE
# ============================================================

best_model_per_zone = []

for j, zone in enumerate(ZONE_NAMES):

    zone_scores = {}

    for model_name, predictions in all_predictions.items():

        zone_scores[model_name] = float(
            np.mean(
                np.abs(
                    Y[:, j] - predictions[:, j]
                )
            )
        )

    best_model = min(
        zone_scores,
        key=zone_scores.get
    )

    best_model_per_zone.append({
        "zone": zone,
        "best_model": best_model,
        "best_mae": zone_scores[best_model],
        "all_model_mae": zone_scores
    })


# ============================================================
# 17. SAVE RESULTS
# ============================================================

output = {

    "analysis": "nested_grouped_model_comparison",

    "dataset_file": DATA_FILE.name,
    "dataset_sha256": dataset_hash,

    "reference_rbf_results": RBF_RESULTS_FILE.name,
    "reference_rbf_results_sha256": sha256_file(
        RBF_RESULTS_FILE
    ),

    "records": int(len(records)),
    "backgrounds": int(len(background_fold)),

    "predictors": 13,
    "zones": ZONE_NAMES,

    "outer_folds": outer_folds,
    "inner_folds": INNER_SPLITS,

    "outer_fold_source": (
        "Exact saved record-level assignments from "
        "rbf_expanded_nested_cv_results_expanded.json"
    ),

    "grouping_variable": "background_id",

    "random_state": RANDOM_STATE,
    "n_estimators": N_ESTIMATORS,

    "tree_hyperparameter_grid": {
        "max_features": MAX_FEATURES_GRID,
        "min_samples_leaf": MIN_SAMPLES_LEAF_GRID
    },

    "models": MODEL_NAMES,

    "overall": overall_results,

    "by_combination": combination_results,

    "per_zone": per_zone_results,

    "zone_comparison_table": zone_comparison,

    "best_model_per_zone": best_model_per_zone,

    "fold_results": fold_results,

    "predictions": {
        name: values.tolist()
        for name, values in all_predictions.items()
    },

    "actual": Y.tolist(),

    "groups": groups.tolist(),

    "combinations": combinations.tolist(),

    "outer_fold_ids": fold_ids.tolist()
}


with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        output,
        f,
        indent=2,
        ensure_ascii=False
    )


# ============================================================
# 18. FINISHED
# ============================================================

print("\n" + "=" * 75)
print("MODEL COMPARISON COMPLETED")
print("=" * 75)

print("Saved:", OUTPUT_FILE)

print("\nModel ranking by overall MAE:")

for rank, (_, row) in enumerate(
    comparison_table.iterrows(),
    start=1
):

    print(
        rank,
        row["model"],
        f"MAE={row['MAE']:.6f}",
        f"RMSE={row['RMSE']:.6f}"
    )

print("\nNo scoring rules or original datasets were modified.")