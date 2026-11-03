
import json
import time
import hashlib
from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd
import requests

from sklearn.kernel_ridge import KernelRidge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from scoring import score_findings, load_presentation


# ============================================================
# 1. CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "zone_validation_output"

PRESENTATION_PATH = ROOT.parent / "presentation_scaly.json"
TRAINING_FILE = DATA_DIR / "targeted_interaction_results.json"

CHECKPOINT_FILE = DATA_DIR / "rbf_external_checkpoint.json"
OUTPUT_FILE = DATA_DIR / "rbf_external_validation_results.json"

API_URL = "https://api.medconsults.ai/api/knowledge/derm/assess"

SEED = 20261103

N_NEW_BACKGROUNDS = 30

# Frozen RBF model parameters
ALPHA = 0.0001
GAMMA = 0.003

# Factorial findings
FINDING_A = 13
FINDING_B = 17

# API request configuration
MAX_RETRIES = 8
BASE_BACKOFF_SECONDS = 60
MAX_BACKOFF_SECONDS = 900
REQUEST_INTERVAL_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 45

# Model predictors
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

COMBINATIONS = {
    "YY": ("y", "y"),
    "YN": ("y", "n"),
    "NY": ("n", "y"),
    "NN": ("n", "n"),
}


# ============================================================
# 2. GENERAL HELPERS
# ============================================================

def answer_key(index):
    return f"scaly|{index}"


def normalize_background(answers):

    normalized = {}

    for key, value in answers.items():

        try:
            index = int(str(key).split("|")[-1])
        except ValueError:
            continue

        if index in (FINDING_A, FINDING_B):
            continue

        normalized[index] = str(value).lower()

    return normalized


def background_hash(answers):

    normalized = normalize_background(answers)

    canonical = json.dumps(
        sorted(normalized.items()),
        separators=(",", ":")
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def generate_new_backgrounds(
    existing_records,
    finding_count,
    number,
    seed
):

    rng = np.random.default_rng(seed)

    excluded = {
        FINDING_A,
        FINDING_B
    }

    eligible = [
        i for i in range(finding_count)
        if i not in excluded
    ]

    existing_hashes = {
        background_hash(record["answers"])
        for record in existing_records
    }

    generated = []
    generated_hashes = set()

    attempts = 0
    max_attempts = 100000

    while len(generated) < number:

        attempts += 1

        if attempts > max_attempts:
            raise RuntimeError(
                "Could not generate enough unique backgrounds."
            )

        # Randomly answer 5–12 of the 38 non-factorial findings.
        n_answered = int(
            rng.integers(5, 13)
        )

        selected = rng.choice(
            eligible,
            size=n_answered,
            replace=False
        )

        answers = {}

        for index in selected:

            value = (
                "y" if rng.random() < 0.5 else "n"
            )

            answers[answer_key(int(index))] = value

        digest = background_hash(answers)

        if digest in existing_hashes:
            continue

        if digest in generated_hashes:
            continue

        generated_hashes.add(digest)

        generated.append({
            "background_id": (
                f"external_{len(generated) + 1:03d}"
            ),
            "answers": answers,
            "background_hash": digest,
            "answered_background_findings": len(answers)
        })

    return generated


# ============================================================
# 3. MODEL
# ============================================================

def build_model():

    return Pipeline([
        ("scale", StandardScaler()),
        (
            "model",
            KernelRidge(
                alpha=ALPHA,
                kernel="rbf",
                gamma=GAMMA
            )
        )
    ])


def reconstruct_probability_vector(
    presentation,
    answers
):

    result = score_findings(
        presentation,
        answers
    )

    probability_map = {
        item["id"]: item["probability"]
        for item in result["ranked"]
    }

    missing = [
        diagnosis
        for diagnosis in SELECTED_NAMES
        if diagnosis not in probability_map
    ]

    if missing:
        raise ValueError(
            f"Missing diagnosis probabilities: {missing}"
        )

    return np.asarray([
        probability_map[name]
        for name in SELECTED_NAMES
    ], dtype=float)


# ============================================================
# 4. API FUNCTIONS WITH RATE-LIMIT HANDLING
# ============================================================

def query_api(session, answers):

    payload = {
        "ctx": {
            "presId": "scaly",
            "today": date.today().isoformat(),
            "state": {
                "find": dict(answers)
            }
        }
    }

    for attempt in range(MAX_RETRIES):

        try:

            response = session.post(
                API_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS
            )

        except requests.RequestException as exc:

            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(
                    f"API connection failed after "
                    f"{MAX_RETRIES} attempts: {exc}"
                ) from exc

            wait_seconds = min(
                BASE_BACKOFF_SECONDS * (2 ** attempt),
                MAX_BACKOFF_SECONDS
            )

            print(
                f"Connection error. Retrying in "
                f"{wait_seconds} seconds: {exc}"
            )

            time.sleep(wait_seconds)
            continue

        if response.status_code == 429:

            retry_after = response.headers.get(
                "Retry-After"
            )

            try:
                server_wait = float(retry_after)
            except (TypeError, ValueError):
                server_wait = 0

            backoff_wait = min(
                BASE_BACKOFF_SECONDS * (2 ** attempt),
                MAX_BACKOFF_SECONDS
            )

            wait_seconds = max(
                server_wait,
                backoff_wait
            )

            print(
                f"HTTP 429: rate limited. "
                f"Attempt {attempt + 1}/{MAX_RETRIES}. "
                f"Waiting {wait_seconds:.0f} seconds."
            )

            if attempt == MAX_RETRIES - 1:
                break

            time.sleep(wait_seconds)
            continue

        if response.status_code >= 500:

            if attempt == MAX_RETRIES - 1:
                response.raise_for_status()

            wait_seconds = min(
                BASE_BACKOFF_SECONDS * (2 ** attempt),
                MAX_BACKOFF_SECONDS
            )

            print(
                f"Server error {response.status_code}. "
                f"Retrying in {wait_seconds} seconds."
            )

            time.sleep(wait_seconds)
            continue

        response.raise_for_status()

        return response.json()

    raise RuntimeError(
        f"API request failed after {MAX_RETRIES} attempts."
    )


def extract_api_zones(response_json):

    if "zones" not in response_json:
        raise KeyError(
            "API response does not contain top-level 'zones'. "
            f"Available keys: {list(response_json.keys())}"
        )

    zones = response_json["zones"]

    if not isinstance(zones, dict):
        raise TypeError(
            f"Expected zones dictionary, got {type(zones)}"
        )

    missing = [
        zone
        for zone in ZONE_NAMES
        if zone not in zones
    ]

    if missing:
        raise ValueError(
            f"API response is missing zones: {missing}"
        )

    return {
        zone: float(zones[zone])
        for zone in ZONE_NAMES
    }


# ============================================================
# 5. CHECKPOINT FUNCTIONS
# ============================================================

def save_checkpoint(backgrounds, validation_records):

    checkpoint = {
        "seed": SEED,
        "alpha": ALPHA,
        "gamma": GAMMA,
        "finding_a": FINDING_A,
        "finding_b": FINDING_B,
        "background_definitions": backgrounds,
        "validation_records": validation_records
    }

    temporary_file = CHECKPOINT_FILE.with_suffix(".tmp")

    with open(
        temporary_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            checkpoint,
            f,
            indent=2
        )

    temporary_file.replace(CHECKPOINT_FILE)


def load_checkpoint():

    if not CHECKPOINT_FILE.exists():
        return None

    with open(
        CHECKPOINT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        checkpoint = json.load(f)

    expected_settings = {
        "seed": SEED,
        "alpha": ALPHA,
        "gamma": GAMMA,
        "finding_a": FINDING_A,
        "finding_b": FINDING_B
    }

    for key, expected in expected_settings.items():

        if checkpoint.get(key) != expected:
            raise ValueError(
                f"Checkpoint setting mismatch: {key}. "
                "Do not reuse this checkpoint with changed settings."
            )

    return checkpoint


# ============================================================
# 6. METRIC FUNCTIONS
# ============================================================

def calculate_metrics(actual, predicted):

    errors = predicted - actual

    clipped_predictions = np.clip(
        predicted,
        0,
        1
    )

    clipped_errors = clipped_predictions - actual

    return {
        "raw_mae": float(
            np.mean(np.abs(errors))
        ),
        "raw_rmse": float(
            np.sqrt(np.mean(errors ** 2))
        ),
        "raw_max_abs_error": float(
            np.max(np.abs(errors))
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
            np.sum(predicted > 1)
        ),
        "predictions_below_zero": int(
            np.sum(predicted < 0)
        )
    }


# ============================================================
# 7. LOAD PRESENTATION AND TRAINING DATA
# ============================================================

print("=" * 80)
print("LOADING PRESENTATION AND TRAINING DATA")
print("=" * 80)

if not PRESENTATION_PATH.exists():
    raise FileNotFoundError(PRESENTATION_PATH)

if not TRAINING_FILE.exists():
    raise FileNotFoundError(TRAINING_FILE)

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

presentation = load_presentation(
    str(PRESENTATION_PATH)
)

if not isinstance(presentation, dict):
    raise TypeError("Presentation loading failed.")

if presentation.get("id") != "scaly":
    raise ValueError("Unexpected presentation ID.")

finding_count = len(presentation["find"])

if finding_count != 40:
    raise ValueError(
        f"Expected 40 findings, got {finding_count}"
    )

with open(
    TRAINING_FILE,
    "r",
    encoding="utf-8"
) as f:

    training_records = json.load(f)

if not isinstance(training_records, list):
    raise TypeError("Training file must contain a list.")

if len(training_records) != 480:
    raise ValueError(
        f"Expected 480 training records, got {len(training_records)}"
    )

print("Presentation:", presentation["id"])
print("Findings:", finding_count)
print("Training records:", len(training_records))


# ============================================================
# 8. RECONSTRUCT TRAINING DATA
# ============================================================

print("\n" + "=" * 80)
print("RECONSTRUCTING TRAINING DATA")
print("=" * 80)

X_train = []
Y_train = []

for i, record in enumerate(
    training_records,
    start=1
):

    probabilities = reconstruct_probability_vector(
        presentation,
        record["answers"]
    )

    zones = [
        float(record["zones"][zone])
        for zone in ZONE_NAMES
    ]

    X_train.append(probabilities)
    Y_train.append(zones)

    if i % 100 == 0:
        print(
            f"Processed {i}/{len(training_records)}"
        )

X_train = np.asarray(
    X_train,
    dtype=float
)

Y_train = np.asarray(
    Y_train,
    dtype=float
)

if not np.all(np.isfinite(X_train)):
    raise ValueError("Training predictors contain non-finite values.")

if not np.all(np.isfinite(Y_train)):
    raise ValueError("Training targets contain non-finite values.")

print("Training X:", X_train.shape)
print("Training Y:", Y_train.shape)


# ============================================================
# 9. FIT FROZEN MODEL
# ============================================================

print("\n" + "=" * 80)
print("FITTING FROZEN RBF MODEL")
print("=" * 80)

model = build_model()

model.fit(
    X_train,
    Y_train
)

print("Model fitted successfully.")
print("Alpha:", ALPHA)
print("Gamma:", GAMMA)
print("Predictors:", SELECTED_NAMES)


# ============================================================
# 10. LOAD OR GENERATE EXTERNAL BACKGROUNDS
# ============================================================

print("\n" + "=" * 80)
print("LOADING EXTERNAL BACKGROUNDS")
print("=" * 80)

checkpoint = load_checkpoint()

if checkpoint is not None:

    backgrounds = checkpoint["background_definitions"]

    validation_records = checkpoint["validation_records"]

    print("Existing checkpoint found.")
    print("Backgrounds:", len(backgrounds))
    print("Saved observations:", len(validation_records))

else:

    backgrounds = generate_new_backgrounds(
        existing_records=training_records,
        finding_count=finding_count,
        number=N_NEW_BACKGROUNDS,
        seed=SEED
    )

    validation_records = []

    save_checkpoint(
        backgrounds,
        validation_records
    )

    print("New backgrounds generated.")
    print("Initial checkpoint saved.")

if len(backgrounds) != N_NEW_BACKGROUNDS:
    raise ValueError(
        "Checkpoint contains an unexpected number of backgrounds."
    )

training_hashes = {
    background_hash(record["answers"])
    for record in training_records
}

for background in backgrounds:

    if background["background_hash"] in training_hashes:
        raise RuntimeError(
            "External background overlaps with training data."
        )

print("All backgrounds are independent of training backgrounds.")


# ============================================================
# 11. VALIDATE CHECKPOINT CONTENTS
# ============================================================

valid_background_ids = {
    background["background_id"]
    for background in backgrounds
}

completed = set()

for record in validation_records:

    key = (
        record["background_id"],
        record["combination"]
    )

    if record["background_id"] not in valid_background_ids:
        raise ValueError(
            f"Checkpoint contains unknown background: {key}"
        )

    if record["combination"] not in COMBINATIONS:
        raise ValueError(
            f"Checkpoint contains unknown combination: {key}"
        )

    if key in completed:
        raise ValueError(
            f"Duplicate checkpoint observation: {key}"
        )

    if len(record["api_zones"]) != len(ZONE_NAMES):
        raise ValueError(
            f"Incomplete API zone data in checkpoint: {key}"
        )

    completed.add(key)

print("Checkpoint validation passed.")
print("Already completed:", len(completed))


# ============================================================
# 12. QUERY API WITH AUTOMATIC RESUMPTION
# ============================================================

print("\n" + "=" * 80)
print("EXTERNAL API VALIDATION")
print("=" * 80)

session = requests.Session()

session.headers.update({
    "Content-Type": "application/json",
    "Accept": "application/json"
})

total_requests = (
    N_NEW_BACKGROUNDS * len(COMBINATIONS)
)

print("Total planned observations:", total_requests)
print("Remaining observations:", total_requests - len(completed))

for background in backgrounds:

    background_id = background["background_id"]

    base_answers = dict(
        background["answers"]
    )

    for combination, pair in COMBINATIONS.items():

        request_key = (
            background_id,
            combination
        )

        if request_key in completed:

            print(
                f"Skipping completed: "
                f"{background_id} - {combination}"
            )

            continue

        answers = dict(base_answers)

        answers[answer_key(FINDING_A)] = pair[0]
        answers[answer_key(FINDING_B)] = pair[1]

        print(
            f"\nRequest {len(completed) + 1}/{total_requests}: "
            f"{background_id} - {combination}"
        )

        try:

            api_response = query_api(
                session,
                answers
            )

            api_zones = extract_api_zones(
                api_response
            )

            probabilities = reconstruct_probability_vector(
                presentation,
                answers
            )

            prediction = model.predict(
                probabilities.reshape(1, -1)
            )[0]

            record = {
                "background_id": background_id,
                "background_hash": background["background_hash"],
                "combination": combination,
                "answers": answers,
                "predictors": probabilities.tolist(),
                "api_zones": api_zones,
                "predicted_zones": {
                    zone: float(prediction[j])
                    for j, zone in enumerate(ZONE_NAMES)
                }
            }

            validation_records.append(record)

            completed.add(request_key)

            # Save immediately after each successful API response.
            save_checkpoint(
                backgrounds,
                validation_records
            )

            print(
                f"Success. Checkpoint saved. "
                f"Completed {len(completed)}/{total_requests}"
            )

        except Exception as exc:

            save_checkpoint(
                backgrounds,
                validation_records
            )

            raise RuntimeError(
                f"Request failed for {background_id}, "
                f"{combination}. "
                f"Completed {len(completed)}/{total_requests}. "
                f"Checkpoint preserved. Error: {exc}"
            ) from exc

        time.sleep(REQUEST_INTERVAL_SECONDS)


# ============================================================
# 13. CHECK COMPLETENESS
# ============================================================

print("\n" + "=" * 80)
print("CHECKING COMPLETENESS")
print("=" * 80)

expected_records = (
    N_NEW_BACKGROUNDS * len(COMBINATIONS)
)

if len(validation_records) != expected_records:
    raise RuntimeError(
        f"Expected {expected_records} observations, "
        f"received {len(validation_records)}."
    )

for background in backgrounds:

    found = {
        record["combination"]
        for record in validation_records
        if record["background_id"] == background["background_id"]
    }

    if found != set(COMBINATIONS):
        raise RuntimeError(
            f"Incomplete combinations for {background['background_id']}: "
            f"{found}"
        )

print("All 30 backgrounds have all four combinations.")
print("Total observations:", len(validation_records))


# ============================================================
# 14. CALCULATE OVERALL PERFORMANCE
# ============================================================

actual = np.asarray([
    [
        record["api_zones"][zone]
        for zone in ZONE_NAMES
    ]
    for record in validation_records
], dtype=float)

predicted = np.asarray([
    [
        record["predicted_zones"][zone]
        for zone in ZONE_NAMES
    ]
    for record in validation_records
], dtype=float)

overall = calculate_metrics(
    actual,
    predicted
)

overall["n_backgrounds"] = N_NEW_BACKGROUNDS
overall["n_observations"] = len(validation_records)

print("\n" + "=" * 80)
print("OVERALL EXTERNAL VALIDATION PERFORMANCE")
print("=" * 80)

for key, value in overall.items():
    print(f"{key}: {value}")


# ============================================================
# 15. PERFORMANCE BY COMBINATION
# ============================================================

print("\n" + "=" * 80)
print("PERFORMANCE BY COMBINATION")
print("=" * 80)

combination_results = {}

for combination in COMBINATIONS:

    mask = np.asarray([
        record["combination"] == combination
        for record in validation_records
    ])

    metrics = calculate_metrics(
        actual[mask],
        predicted[mask]
    )

    metrics["n"] = int(mask.sum())

    combination_results[combination] = metrics

    print(combination, metrics)


# ============================================================
# 16. PERFORMANCE BY ZONE
# ============================================================

print("\n" + "=" * 80)
print("PERFORMANCE BY ZONE")
print("=" * 80)

zone_results = []

clipped_predictions = np.clip(
    predicted,
    0,
    1
)

for j, zone in enumerate(ZONE_NAMES):

    errors = predicted[:, j] - actual[:, j]

    clipped_errors = (
        clipped_predictions[:, j] - actual[:, j]
    )

    zone_results.append({
        "zone": zone,
        "raw_mae": float(
            np.mean(np.abs(errors))
        ),
        "clipped_mae": float(
            np.mean(np.abs(clipped_errors))
        ),
        "raw_rmse": float(
            np.sqrt(np.mean(errors ** 2))
        ),
        "max_abs_error": float(
            np.max(np.abs(errors))
        ),
        "bias": float(
            np.mean(errors)
        )
    })

zone_df = pd.DataFrame(
    zone_results
).sort_values(
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
# 17. PERFORMANCE BY BACKGROUND
# ============================================================

print("\n" + "=" * 80)
print("PERFORMANCE BY BACKGROUND")
print("=" * 80)

background_results = []

for background in backgrounds:

    background_id = background["background_id"]

    indices = [
        i
        for i, record in enumerate(validation_records)
        if record["background_id"] == background_id
    ]

    metrics = calculate_metrics(
        actual[indices],
        predicted[indices]
    )

    background_results.append({
        "background_id": background_id,
        "raw_mae": metrics["raw_mae"],
        "clipped_mae": metrics["clipped_mae"],
        "raw_rmse": metrics["raw_rmse"],
        "max_abs_error": metrics["raw_max_abs_error"]
    })

background_df = pd.DataFrame(
    background_results
).sort_values(
    "raw_mae",
    ascending=False
)

print("\nWorst 10 backgrounds:")

print(
    background_df.head(10).to_string(
        index=False,
        float_format=lambda x: f"{x:.8f}"
    )
)


# ============================================================
# 18. SAVE FINAL RESULTS
# ============================================================

output = {
    "validation_type": "Independent external validation",
    "model": "RBF Kernel Ridge",
    "model_frozen": True,
    "alpha": ALPHA,
    "gamma": GAMMA,
    "predictors": SELECTED_NAMES,
    "diagnosis_ids": DIAGNOSIS_IDS,
    "zone_names": ZONE_NAMES,
    "training_records": len(training_records),
    "training_backgrounds": len({
        record["source_case"]
        for record in training_records
    }),
    "external_backgrounds": N_NEW_BACKGROUNDS,
    "external_observations": len(validation_records),
    "seed": SEED,
    "factorial_findings": [
        FINDING_A,
        FINDING_B
    ],
    "overall": overall,
    "by_combination": combination_results,
    "per_zone": zone_results,
    "per_background": background_results,
    "background_definitions": backgrounds,
    "validation_records": validation_records
}

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
print("FINAL RESULTS SAVED")
print("=" * 80)

print("Results:", OUTPUT_FILE)
print("Checkpoint:", CHECKPOINT_FILE)
print("External observations:", len(validation_records))
print("Analysis completed successfully.")
