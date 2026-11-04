
import json
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.kernel_ridge import KernelRidge
from sklearn.model_selection import GroupKFold
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

from scoring import score_findings, load_presentation


# ============================================================
# 1. PATHS AND CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent

PRESENTATION_PATH = ROOT.parent / "presentation_scaly.json"

DATA_DIR = ROOT / "zone_validation_output"

INPUT_FILE = DATA_DIR / "targeted_interaction_results.json"
OUTPUT_FILE = DATA_DIR / "rbf_expanded_nested_cv_results.json"

OUTER_SPLITS = 5
INNER_SPLITS = 4

ALPHAS = [
    1e-7,
    1e-6,
    1e-5,
    1e-4,
    1e-3,
    0.01,
    0.1,
]

GAMMAS = [
    0.0001,
    0.0003,
    0.001,
    0.003,
    0.01,
    0.03,
    0.1,
]

SELECTED_NAMES = [
    "ast",
    "ldrug",
    "lp",
    "mf",
    "num",
    "pr",
    "prp",
    "pso",
    "reac",
    "scle",
    "seb",
    "syph",
    "tin",
]

DIAGNOSIS_IDS = [
    "ast", "bowen", "dles", "eryth", "ivul", "ldrug",
    "lp", "mf", "num", "plc", "pr", "prp", "pso",
    "reac", "scle", "seb", "syph", "tin"
]

ZONE_NAMES = [
    "abdo", "ankle", "antecub", "axilla", "back",
    "buttock", "calf", "chest", "conj", "ear",
    "elbow", "face", "foot", "forearm", "genital",
    "groin", "hand", "knee", "nail", "neck",
    "oral", "palm", "perianal", "poplit", "scalp",
    "shin", "shoulder", "sole", "thigh", "umbil",
    "web", "wrist"
]


# ============================================================
# 2. VALIDATE FILES AND LOAD PRESENTATION
# ============================================================

print("=" * 80)
print("LOADING PRESENTATION")
print("=" * 80)

if not PRESENTATION_PATH.exists():
    raise FileNotFoundError(
        f"Presentation file not found: {PRESENTATION_PATH}"
    )

presentation = load_presentation(str(PRESENTATION_PATH))

if not isinstance(presentation, dict):
    raise TypeError(
        "load_presentation() did not return a valid dictionary. "
        "Check scoring.py and presentation_scaly.json."
    )

if "id" not in presentation:
    raise ValueError("Presentation has no 'id' field.")

if presentation["id"] != "scaly":
    raise ValueError(
        f"Unexpected presentation ID: {presentation['id']}"
    )

if not INPUT_FILE.exists():
    raise FileNotFoundError(
        f"Input data file not found: {INPUT_FILE}"
    )

print("Presentation loaded successfully.")
print("Presentation ID:", presentation["id"])
print("Findings:", len(presentation["find"]))
print("Diagnoses:", len(presentation["dx"]))


# ============================================================
# 3. LOAD FACTORIAL DATA
# ============================================================

print("\n" + "=" * 80)
print("LOADING FACTORIAL DATA")
print("=" * 80)

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    records = json.load(f)

if not isinstance(records, list):
    raise TypeError(
        "Expected targeted_interaction_results.json to contain a list."
    )

if not records:
    raise ValueError("The input data file contains no records.")

print("Records loaded:", len(records))


# ============================================================
# 4. RECONSTRUCT DIAGNOSIS PROBABILITIES
# ============================================================

print("\n" + "=" * 80)
print("RECONSTRUCTING DIAGNOSIS PROBABILITIES")
print("=" * 80)

diagnosis_indices = [
    DIAGNOSIS_IDS.index(name)
    for name in SELECTED_NAMES
]

X = []
Y = []
groups = []
combinations = []
source_cases = []

for record_number, record in enumerate(records, start=1):

    if "answers" not in record:
        raise KeyError(
            f"Record {record_number} has no 'answers' field."
        )

    if "zones" not in record:
        raise KeyError(
            f"Record {record_number} has no 'zones' field."
        )

    if "source_case" not in record:
        raise KeyError(
            f"Record {record_number} has no 'source_case' field."
        )

    if "combination" not in record:
        raise KeyError(
            f"Record {record_number} has no 'combination' field."
        )

    result = score_findings(
        presentation,
        record["answers"]
    )

    probability_map = {
        item["id"]: item["probability"]
        for item in result["ranked"]
    }

    missing_diagnoses = [
        diagnosis_id
        for diagnosis_id in DIAGNOSIS_IDS
        if diagnosis_id not in probability_map
    ]

    if missing_diagnoses:
        raise ValueError(
            f"Record {record_number}: missing diagnoses "
            f"{missing_diagnoses}"
        )

    missing_zones = [
        zone
        for zone in ZONE_NAMES
        if zone not in record["zones"]
    ]

    if missing_zones:
        raise ValueError(
            f"Record {record_number}: missing zones "
            f"{missing_zones}"
        )

    X.append([
        probability_map[diagnosis_id]
        for diagnosis_id in DIAGNOSIS_IDS
    ])

    Y.append([
        record["zones"][zone]
        for zone in ZONE_NAMES
    ])

    groups.append(record["source_case"])
    combinations.append(record["combination"])
    source_cases.append(record["source_case"])

    if record_number % 50 == 0:
        print(
            f"Processed {record_number}/{len(records)} records"
        )


# Convert to NumPy arrays.

X = np.asarray(X, dtype=float)
Y = np.asarray(Y, dtype=float)

groups = np.asarray(groups)
combinations = np.asarray(combinations)
source_cases = np.asarray(source_cases)

# Retain the preselected 13 predictors.

X = X[:, diagnosis_indices]

n_records, n_predictors = X.shape
n_zones = Y.shape[1]

if not (
    len(X) == len(Y) == len(groups)
    == len(combinations) == len(source_cases)
):
    raise RuntimeError("Input arrays have inconsistent lengths.")

if not np.all(np.isfinite(X)):
    raise ValueError("Predictor matrix contains non-finite values.")

if not np.all(np.isfinite(Y)):
    raise ValueError("Zone matrix contains non-finite values.")

unique_groups = np.unique(groups)

if len(unique_groups) < OUTER_SPLITS:
    raise ValueError(
        f"Need at least {OUTER_SPLITS} unique backgrounds."
    )

print("\nData reconstruction completed.")
print("Records:", n_records)
print("Predictors:", n_predictors)
print("Zones:", n_zones)
print("Unique backgrounds:", len(unique_groups))
print("Selected predictors:", SELECTED_NAMES)


# ============================================================
# 5. MODEL AND INNER HYPERPARAMETER SEARCH
# ============================================================

def make_model(alpha, gamma):

    return Pipeline([
        ("scale", StandardScaler()),
        (
            "model",
            KernelRidge(
                alpha=alpha,
                kernel="rbf",
                gamma=gamma
            )
        )
    ])


def tune_rbf(X_train, Y_train, groups_train):

    inner_cv = GroupKFold(
        n_splits=INNER_SPLITS
    )

    best_score = np.inf
    best_alpha = None
    best_gamma = None

    search_results = []

    for alpha in ALPHAS:

        for gamma in GAMMAS:

            fold_scores = []

            for inner_train, inner_valid in inner_cv.split(
                X_train,
                Y_train,
                groups_train
            ):

                model = make_model(
                    alpha,
                    gamma
                )

                model.fit(
                    X_train[inner_train],
                    Y_train[inner_train]
                )

                predictions = model.predict(
                    X_train[inner_valid]
                )

                score = mean_absolute_error(
                    Y_train[inner_valid],
                    predictions
                )

                fold_scores.append(float(score))

            mean_score = float(
                np.mean(fold_scores)
            )

            search_results.append({
                "alpha": float(alpha),
                "gamma": float(gamma),
                "inner_mae": mean_score,
                "inner_fold_mae": fold_scores
            })

            if mean_score < best_score:

                best_score = mean_score
                best_alpha = alpha
                best_gamma = gamma

    return (
        best_alpha,
        best_gamma,
        best_score,
        search_results
    )


# ============================================================
# 6. OUTER NESTED GROUPED CROSS-VALIDATION
# ============================================================

print("\n" + "=" * 80)
print("NESTED GROUPED CROSS-VALIDATION")
print("=" * 80)

outer_cv = GroupKFold(
    n_splits=OUTER_SPLITS
)

outer_predictions = np.zeros_like(Y)

fold_results = []

for fold, (train_idx, test_idx) in enumerate(
    outer_cv.split(X, Y, groups),
    start=1
):

    print("\n" + "=" * 80)
    print(f"OUTER FOLD {fold}")
    print("=" * 80)

    X_train = X[train_idx]
    Y_train = Y[train_idx]

    X_test = X[test_idx]
    Y_test = Y[test_idx]

    groups_train = groups[train_idx]

    (
        best_alpha,
        best_gamma,
        inner_score,
        search_results
    ) = tune_rbf(
        X_train,
        Y_train,
        groups_train
    )

    print(f"Selected alpha: {best_alpha}")
    print(f"Selected gamma: {best_gamma}")
    print(f"Best inner MAE: {inner_score:.8f}")

    model = make_model(
        best_alpha,
        best_gamma
    )

    model.fit(
        X_train,
        Y_train
    )

    predictions = model.predict(
        X_test
    )

    outer_predictions[test_idx] = predictions

    fold_mae = mean_absolute_error(
        Y_test,
        predictions
    )

    fold_rmse = np.sqrt(
        mean_squared_error(
            Y_test,
            predictions
        )
    )

    print(f"Outer MAE: {fold_mae:.8f}")
    print(f"Outer RMSE: {fold_rmse:.8f}")

    fold_results.append({
        "fold": fold,
        "train_records": int(len(train_idx)),
        "test_records": int(len(test_idx)),
        "train_backgrounds": int(
            len(np.unique(groups_train))
        ),
        "test_backgrounds": int(
            len(np.unique(groups[test_idx]))
        ),
        "alpha": float(best_alpha),
        "gamma": float(best_gamma),
        "inner_mae": float(inner_score),
        "outer_mae": float(fold_mae),
        "outer_rmse": float(fold_rmse),
        "search_results": search_results
    })


# ============================================================
# 7. OVERALL PERFORMANCE
# ============================================================

raw_errors = outer_predictions - Y

clipped_predictions = np.clip(
    outer_predictions,
    0,
    1
)

clipped_errors = clipped_predictions - Y

overall = {
    "raw_mae": float(
        np.mean(np.abs(raw_errors))
    ),
    "raw_rmse": float(
        np.sqrt(np.mean(raw_errors ** 2))
    ),
    "raw_max_abs_error": float(
        np.max(np.abs(raw_errors))
    ),
    "clipped_mae": float(
        np.mean(np.abs(clipped_errors))
    ),
    "clipped_rmse": float(
        np.sqrt(np.mean(clipped_errors ** 2))
    ),
    "clipped_max_abs_error": float(
        np.max(np.abs(clipped_errors))
    ),
    "predictions_above_one": int(
        np.sum(outer_predictions > 1)
    ),
    "predictions_below_zero": int(
        np.sum(outer_predictions < 0)
    )
}

print("\n" + "=" * 80)
print("OVERALL RBF PERFORMANCE")
print("=" * 80)

for key, value in overall.items():
    print(f"{key}: {value}")


# ============================================================
# 8. PERFORMANCE BY COMBINATION
# ============================================================

print("\n" + "=" * 80)
print("PERFORMANCE BY COMBINATION")
print("=" * 80)

combination_results = {}

for combination in ["YY", "YN", "NY", "NN"]:

    mask = combinations == combination

    if not np.any(mask):
        continue

    combination_results[combination] = {
        "n": int(mask.sum()),
        "raw_mae": float(
            np.mean(np.abs(raw_errors[mask]))
        ),
        "clipped_mae": float(
            np.mean(np.abs(clipped_errors[mask]))
        ),
        "raw_rmse": float(
            np.sqrt(np.mean(raw_errors[mask] ** 2))
        ),
        "clipped_rmse": float(
            np.sqrt(np.mean(clipped_errors[mask] ** 2))
        ),
        "max_abs_error": float(
            np.max(np.abs(raw_errors[mask]))
        )
    }

    print(
        combination,
        combination_results[combination]
    )


# ============================================================
# 9. PERFORMANCE BY ZONE
# ============================================================

print("\n" + "=" * 80)
print("PERFORMANCE BY ZONE")
print("=" * 80)

zone_results = []

for j, zone in enumerate(ZONE_NAMES):

    zone_results.append({
        "zone": zone,
        "raw_mae": float(
            np.mean(np.abs(raw_errors[:, j]))
        ),
        "clipped_mae": float(
            np.mean(np.abs(clipped_errors[:, j]))
        ),
        "raw_rmse": float(
            np.sqrt(np.mean(raw_errors[:, j] ** 2))
        ),
        "max_abs_error": float(
            np.max(np.abs(raw_errors[:, j]))
        ),
        "bias": float(
            np.mean(raw_errors[:, j])
        )
    })

zone_df = pd.DataFrame(zone_results)

zone_df = zone_df.sort_values(
    "raw_mae",
    ascending=False
)

print(
    zone_df.to_string(
        index=False,
        float_format=lambda x: f"{x:.8f}"
    )
)


# ============================================================
# 10. SAVE RESULTS
# ============================================================

output = {
    "model": "RBF Kernel Ridge",
    "predictors": SELECTED_NAMES,
    "diagnosis_ids": DIAGNOSIS_IDS,
    "zone_names": ZONE_NAMES,
    "records": int(n_records),
    "unique_backgrounds": int(
        len(unique_groups)
    ),
    "outer_splits": OUTER_SPLITS,
    "inner_splits": INNER_SPLITS,
    "alpha_grid": ALPHAS,
    "gamma_grid": GAMMAS,
    "fold_results": fold_results,
    "overall": overall,
    "by_combination": combination_results,
    "per_zone": zone_results,
    "predictions": outer_predictions.tolist(),
    "clipped_predictions": clipped_predictions.tolist(),
    "actual": Y.tolist(),
    "groups": groups.tolist(),
    "combinations": combinations.tolist(),
    "source_cases": source_cases.tolist()
}

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        output,
        f,
        indent=2
    )

print("\n" + "=" * 80)
print("SAVED RESULTS")
print("=" * 80)

print(OUTPUT_FILE)
print("Analysis completed successfully.")
