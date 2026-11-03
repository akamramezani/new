
import json
import math
from pathlib import Path


DEFAULT_EXPONENT = 0.7
DEFAULT_RESIDUAL = 0.11

# Experimentally reconstructed residual parameters.
RESIDUAL_FLOOR = 0.05
RESIDUAL_INITIAL_EXCESS = 0.06
RESIDUAL_DECAY_CONSTANT = 3.0

# The residual function has only been validated for this presentation.
RESIDUAL_VALIDATED_PRESENTATIONS = {"scaly"}


# ============================================================
# RESIDUAL ESTIMATION
# ============================================================

def estimate_residual(retained_count):
    """
    Estimate residual probability from the number of retained,
    independent findings.

    Reconstructed API formula:

        R(n) = 0.05 + 0.06 * exp(-n / 3)

    Parameters
    ----------
    retained_count:
        Number of independent findings remaining after
        correlation handling.

    Returns
    -------
    float
        Estimated residual probability.
    """

    if isinstance(retained_count, bool) or not isinstance(
        retained_count, int
    ):
        raise TypeError(
            "retained_count must be a non-negative integer."
        )

    if retained_count < 0:
        raise ValueError(
            "retained_count cannot be negative."
        )

    return (
        RESIDUAL_FLOOR
        + RESIDUAL_INITIAL_EXCESS
        * math.exp(
            -retained_count / RESIDUAL_DECAY_CONSTANT
        )
    )


# ============================================================
# PRESENTATION LOADING
# ============================================================

def load_presentation(path):
    """Load a presentation configuration exported from the backend."""

    path = Path(path)

    with path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    required = ("id", "dx", "find")
    missing = [key for key in required if key not in data]

    if missing:
        raise ValueError(
            f"Presentation JSON is missing: {missing}"
        )

    return data


# ============================================================
# ANSWER VALIDATION
# ============================================================

def get_answered_findings(presentation, answers):
    """
    Return valid answers indexed by finding index.

    Expected format:
        {"scaly|0": "y", "scaly|3": "n"}
    """

    presentation_id = presentation["id"]

    return {
        i: answers.get(f"{presentation_id}|{i}")
        for i in range(len(presentation["find"]))
        if answers.get(f"{presentation_id}|{i}") in ("y", "n")
    }


# ============================================================
# CORRELATION GUARD
# ============================================================

def select_correlated_findings(presentation, answers):
    """
    Apply experimentally confirmed correlation rules.

    Currently validated for the 'scaly' presentation only.

    Unmapped groups and presentations are left unchanged.
    """

    answered = get_answered_findings(
        presentation,
        answers,
    )

    retained = set(answered)

    if presentation["id"] != "scaly":
        return retained, []

    def resolve(indices, selector):
        """
        Resolve a tested correlation group.

        A group with fewer than two answered findings is unchanged.
        """

        available = [
            i for i in indices
            if i in answered
        ]

        if len(available) < 2:
            return

        selected = selector(answered)

        if selected not in available:
            return

        for i in available:
            if i != selected:
                retained.discard(i)

    # --------------------------------------------------------
    # Group 1: pso-morph (0, 1)
    # Retain 1 only when 0 = No and 1 = Yes.
    # Otherwise retain 0.
    # --------------------------------------------------------

    resolve(
        (0, 1),
        lambda a: (
            1 if a[0] == "n" and a[1] == "y"
            else 0
        ),
    )

    # --------------------------------------------------------
    # Group 2: lp-morph (10, 11)
    # Retain 11 if 11 = Yes; otherwise retain 10.
    # --------------------------------------------------------

    resolve(
        (10, 11),
        lambda a: (
            11 if a[11] == "y" else 10
        ),
    )

    # --------------------------------------------------------
    # Group 3: mf-morph (19, 20)
    # Retain 19 if 19 = Yes; otherwise retain 20.
    # --------------------------------------------------------

    resolve(
        (19, 20),
        lambda a: (
            19 if a[19] == "y" else 20
        ),
    )

    # --------------------------------------------------------
    # Group 4: photo (16, 25)
    # Retain 16 if Yes.
    # Otherwise retain 25 if Yes.
    # If both are No, retain 16.
    # --------------------------------------------------------

    resolve(
        (16, 25),
        lambda a: (
            16 if a[16] == "y"
            else 25 if a[25] == "y"
            else 16
        ),
    )

    # --------------------------------------------------------
    # Group 5: palm (13, 29)
    # Retain 29 if 29 = Yes; otherwise retain 13.
    # --------------------------------------------------------

    resolve(
        (13, 29),
        lambda a: (
            29 if a[29] == "y" else 13
        ),
    )

    # --------------------------------------------------------
    # Group 6: prp-morph (17, 18)
    # Retain 18 only when 17 = No and 18 = Yes.
    # Otherwise retain 17.
    # --------------------------------------------------------

    resolve(
        (17, 18),
        lambda a: (
            18 if a[17] == "n"
            else 17
        ),
    )

    # --------------------------------------------------------
    # Group 7: pr-morph (7, 8, 9)
    # Priority:
    # 1. Finding 7 if Yes.
    # 2. Otherwise finding 9 if Yes.
    # 3. Otherwise finding 8.
    #
    # For partially answered combinations where no supported
    # selection exists, retain all answered findings.
    # --------------------------------------------------------

    available = [
        i for i in (7, 8, 9)
        if i in answered
    ]

    if len(available) >= 2:

        selected = None

        if 7 in answered and answered[7] == "y":
            selected = 7

        elif 9 in answered and answered[9] == "y":
            selected = 9

        elif 8 in answered:
            selected = 8
            
        elif 7 in answered:
            selected = 7

        elif 9 in answered:
            selected = 9

        if selected is not None:
            for i in available:
                if i != selected:
                    retained.discard(i)

    # --------------------------------------------------------
    # Return dropped findings with original metadata.
    # --------------------------------------------------------

    dropped = []

    for i in sorted(answered):

        if i not in retained:

            dropped.append({
                "f": presentation["find"][i],
                "i": i,
                "v": answered[i],
            })

    return retained, dropped


# ============================================================
# DIAGNOSIS SCORING
# ============================================================

def score_findings(
    presentation,
    answers,
    residual=None,
    exponent=DEFAULT_EXPONENT,
    retained_indices=None,
):
    """
    Calculate diagnosis weights and probabilities.

    Weight formula:

        W_i = B_i * product(m_ij ** exponent)

    Probability formula:

        P_i = (1 - residual) * W_i / sum(W)

    Automatic residual formula for validated presentations:

        R(n) = 0.05 + 0.06 * exp(-n / 3)

    Parameters
    ----------
    presentation:
        Parsed presentation JSON.

    answers:
        Dictionary such as:
        {"scaly|0": "y", "scaly|3": "n"}.

    residual:
        Optional manually specified residual.

        If None, residual is estimated automatically for
        experimentally validated presentations.

        For other presentations, DEFAULT_RESIDUAL is used
        until their residual functions are independently tested.

    exponent:
        Finding modifier exponent.

    retained_indices:
        Optional iterable of manually selected finding indices.
        If supplied, automatic correlation handling is bypassed.

    Returns
    -------
    Dictionary containing diagnosis rankings and scoring details.
    """

    if residual is not None:

        if not isinstance(residual, (int, float)):
            raise TypeError(
                "Residual must be a number or None."
            )

        if not math.isfinite(residual) or not 0 <= residual < 1:
            raise ValueError(
                "Residual must be finite and >= 0 and < 1."
            )

    if not isinstance(exponent, (int, float)):
        raise TypeError(
            "Exponent must be numeric."
        )

    if not math.isfinite(exponent) or exponent <= 0:
        raise ValueError(
            "Exponent must be finite and positive."
        )

    if not isinstance(answers, dict):
        raise TypeError(
            "answers must be a dictionary."
        )

    # --------------------------------------------------------
    # Count all valid raw answers, including dropped findings.
    # --------------------------------------------------------

    answered = get_answered_findings(
        presentation,
        answers,
    )

    raw_answered_count = len(answered)

    # --------------------------------------------------------
    # Apply correlation selection unless manually overridden.
    # --------------------------------------------------------

    if retained_indices is not None:

        retained = set(retained_indices)

        dropped_findings = []

        for i in sorted(answered):

            if i not in retained:

                dropped_findings.append({
                    "f": presentation["find"][i],
                    "i": i,
                    "v": answered[i],
                })

    else:

        retained, dropped_findings = (
            select_correlated_findings(
                presentation,
                answers,
            )
        )

    # Only answered and retained indices contribute to scoring
    # and residual estimation.
    effective_retained = (
        set(retained).intersection(answered)
    )

    retained_count = len(effective_retained)

    # --------------------------------------------------------
    # Determine residual.
    #
    # Explicit residual overrides automatic estimation.
    # Automatic estimation is currently validated for 'scaly'.
    # --------------------------------------------------------

    if residual is None:

        if presentation["id"] in RESIDUAL_VALIDATED_PRESENTATIONS:

            residual = estimate_residual(
                retained_count
            )

        else:

            residual = DEFAULT_RESIDUAL

    # --------------------------------------------------------
    # Initialize diagnosis weights from configured base values.
    # --------------------------------------------------------

    weights = {}

    for diagnosis in presentation["dx"]:

        diagnosis_id = diagnosis["id"]
        base = float(diagnosis["base"])

        if not math.isfinite(base) or base <= 0:
            raise ValueError(
                f"Invalid base weight for diagnosis {diagnosis_id}"
            )

        weights[diagnosis_id] = base

    applied_findings = []

    # --------------------------------------------------------
    # Apply modifiers only from retained answered findings.
    # --------------------------------------------------------

    for index in sorted(effective_retained):

        answer = answered[index]

        finding = presentation["find"][index]

        multiplier_position = (
            0 if answer == "y" else 1
        )

        modifiers = finding.get("f", {})

        affected = []

        for diagnosis_id, pair in modifiers.items():

            if diagnosis_id not in weights:
                continue

            if len(pair) != 2:
                raise ValueError(
                    f"Invalid modifier at finding {index}, "
                    f"diagnosis {diagnosis_id}"
                )

            multiplier = float(
                pair[multiplier_position]
            )

            if not math.isfinite(multiplier) or multiplier <= 0:
                raise ValueError(
                    f"Invalid multiplier at finding {index}, "
                    f"diagnosis {diagnosis_id}"
                )

            weights[diagnosis_id] *= (
                multiplier ** exponent
            )

            affected.append(diagnosis_id)

        applied_findings.append({
            "index": index,
            "answer": answer,
            "group": finding.get("g"),
            "affected_diagnoses": affected,
        })

    # --------------------------------------------------------
    # Calculate total diagnosis weight.
    # --------------------------------------------------------

    total_weight = sum(weights.values())

    if not math.isfinite(total_weight) or total_weight <= 0:
        raise ValueError(
            "Total diagnosis weight is not positive and finite."
        )

    # --------------------------------------------------------
    # Calculate diagnosis probabilities.
    # --------------------------------------------------------

    ranked = []

    for diagnosis in presentation["dx"]:

        diagnosis_id = diagnosis["id"]

        raw_weight = weights[diagnosis_id]

        probability = (
            (1.0 - residual)
            * raw_weight
            / total_weight
        )

        ranked.append({
            "id": diagnosis_id,
            "name": diagnosis["n"],
            "base": float(diagnosis["base"]),
            "weight": raw_weight,
            "probability": probability,
        })

    ranked.sort(
        key=lambda item: item["probability"],
        reverse=True,
    )

    return {
        "presentation": presentation["id"],
        "answered": raw_answered_count,
        "scored_findings": len(applied_findings),
        "residual": residual,
        "exponent": exponent,
        "total_weight": total_weight,
        "probability_sum": sum(
            item["probability"]
            for item in ranked
        ),
        "findings": applied_findings,
        "dropped_findings": dropped_findings,
        "ranked": ranked,
    }


# ============================================================
# RANKING DISPLAY
# ============================================================

def print_ranking(result, limit=None):
    """Print a readable diagnosis ranking."""

    print(
        f"\nPresentation: {result['presentation']}"
    )

    print(
        f"Answered findings: {result['answered']}"
    )

    print(
        f"Scored findings: {result['scored_findings']}"
    )

    print(
        f"Residual: {result['residual']:.8f}"
    )

    print(
        f"Probability sum: {result['probability_sum']:.8f}"
    )

    print(
        "\nRank  Diagnosis                              Probability"
    )

    print("-" * 68)

    rows = result["ranked"]

    if limit is not None:
        rows = rows[:limit]

    for position, item in enumerate(rows, start=1):

        print(
            f"{position:<6}"
            f"{item['name'][:37]:<39}"
            f"{item['probability']:.6f}"
        )

    if result["dropped_findings"]:

        print("\nDropped findings:")

        for item in result["dropped_findings"]:

            print(
                f"  Index {item['i']}: "
                f"{item['v']} - "
                f"{item['f'].get('l', 'Unknown finding')}"
            )
