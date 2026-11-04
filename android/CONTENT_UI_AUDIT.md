# Android dermatology app: content and UI audit

Audit date: 2026-11-05  
Branch: `main`  
Scope: all 12 exported presentation JSON assets, `PresentationCatalog.kt`, and `MainActivity.kt`.

## Executive summary

The exported knowledge layer is substantially richer than the current interaction model. The 12 assets contain:

| Content | Total |
|---|---:|
| Diagnosis profiles | 197 |
| Clinical findings | 382 |
| Investigations/tests | 133 |
| Patient-context modifiers | 115 |
| Escalation/stop rules | 81 |

All 12 presentations load through the manifest-backed catalog. The asset schema is compact and uses keys such as `dx`, `find`, `test`, `ctx`, and `stop`; it is not missing content simply because those names differ from the Kotlin model names.

## Per-presentation inventory

| Presentation | Diagnoses | Findings | Tests | Context modifiers | Stop rules |
|---|---:|---:|---:|---:|---:|
| Scaly plaques and patches | 18 | 40 | 14 | 11 | 6 |
| Acute generalized eruption | 16 | 33 | 12 | 11 | 8 |
| Blisters, bullae and erosions | 18 | 37 | 14 | 10 | 8 |
| Wheals and episodic swelling | 14 | 28 | 12 | 9 | 7 |
| Purpura and non-blanching lesions | 17 | 32 | 14 | 11 | 9 |
| Itchy eczematous dermatitis | 18 | 34 | 12 | 11 | 6 |
| Annular and figurate lesions | 16 | 29 | 12 | 10 | 5 |
| Pigmented lesion in question | 16 | 34 | 11 | 10 | 6 |
| Facial papules and pustules | 15 | 30 | 11 | 11 | 6 |
| Hair loss | 17 | 28 | 9 | 11 | 6 |
| Nodules and non-healing ulcers | 16 | 28 | 11 | 11 | 7 |
| Hypopigmented/depigmented macules | 16 | 29 | 11 | 9 | 7 |

## What the current app already renders

- Presentation selection and overview metadata, including counts, lead-in text, safety flag, and up to three stop rules.
- Searchable findings with present/absent/clear controls, group, evidence grade, source, and expandable likelihood-factor pairs.
- Differential ranking bars, baseline-share comparison, per-diagnosis contribution traces, correlated findings dropped by the scaly-only guard, and expandable diagnosis details.
- Investigation cards with target, sensitivity, specificity, evidence/source, indication, positive/negative interpretation, and caveats.
- Diagnosis reference profiles and context-modifier cards.

This means the issue is not that the app currently ignores every source field. The existing UI does expose many of the detailed fields, but mostly as static text and expandable cards.

## Confirmed limitations and product gaps

1. **No interactive patient-context capture.** The 115 context modifiers are displayed in Reference, but there is no workflow to enter age/context and have it alter the differential. The UI explicitly states these modifiers are reference-only.
2. **No investigation-driven update.** Tests can be read, but users cannot record a test result and see the differential update. Sensitivity/specificity are displayed as source values, not used in a Bayesian/post-test calculation.
3. **No diagnosis-to-test prioritisation.** The test list is not dynamically ranked or filtered against the current leading differential. Each test has a target, but no implemented decision-support bridge from current ranking to test choice.
4. **No dedicated visual evidence comparison.** The differential has proportional bars, but there is no compact side-by-side comparison of discriminating findings, positive/negative likelihood factors, or test characteristics across the leading diagnoses.
5. **No presentation-specific scorer outside scaly.** The current scorer uses a fixed 0.11 residual and no correlation handling for the other 11 presentations. These are explicit reconstruction limitations, not validated source-model behaviour.
6. **No adaptive next-finding/question flow.** Findings are presented as a searchable list rather than prioritised by expected discrimination or uncertainty reduction.
7. **No automated triage.** Stop rules are displayed as warnings only; they do not interrupt scoring or determine escalation. Do not imply otherwise.
8. **No media/lesion-image library is surfaced in the inspected screens.** The current catalog model does not expose image/media fields. This audit does not establish whether the source website has image assets elsewhere.

## Diagnosis profile field coverage

Across all assets, every diagnosis profile has a name, typical appearance, supporting features, opposing features, clinical confirmation, histopathology, associations, management reference, typical sites, and distribution/pattern. Dermoscopy is present selectively where supplied: 100 diagnosis profiles have a non-empty dermoscopy field. Absence of dermoscopy in the other profiles should not be treated as an export defect without checking source applicability.

## Test field coverage

All 133 test records have non-empty sensitivity, specificity, positive-result interpretation, negative-result interpretation, and caveat fields in the exported assets. These values must be presented with their evidence grade/source and must not be treated as universal test performance estimates independent of population, setting, sampling, or pre-test probability.

## Recommended implementation order

### Milestone A — richer differential comparison (safe, no new clinical inference)
- Add a leading-diagnosis comparison view with supporting/opposing findings, site/distribution, clinical confirmation, histopathology, and management text side by side.
- Add a filter/sort control to the test list by target diagnosis using only the explicit source target strings; avoid fuzzy diagnosis mappings.
- Add a test detail layout that visually separates intended use, positive/negative interpretation, and caveats.
- Preserve all source attribution and evidence grades.

### Milestone B — context capture (only with explicit source mapping)
- First audit each context modifier's exact schema and semantics, then implement only deterministic mappings present in the source data.
- Keep unmapped or ambiguous modifiers informational. Do not invent demographic or risk multipliers.
- Add regression fixtures for every applied modifier and verify that unknown context never silently changes a score.

### Milestone C — post-test reasoning (only when validated inputs are available)
- Do not infer post-test probabilities from sensitivity/specificity unless the test's applicable population, thresholds, and operating characteristics are adequately specified.
- Prefer source-provided likelihood ratios or validated test-update logic. Otherwise keep test interpretation educational and separate from the provisional ranking.

### Milestone D — scorer parity
- Obtain live website/API reference outputs or the original backend scoring implementation and compare every presentation.
- Until then, label reconstructed scoring as provisional and do not claim parity or clinical validation.

## Audit conclusion

The content export is broad and structured. The most important reason the APK feels simpler than the website is the interaction gap: context modifiers are passive, tests do not feed back into the differential, and the app lacks a rich cross-diagnosis comparison and adaptive workflow. The next safe feature milestone is an explicit diagnosis comparison view plus target-aware test browsing, without changing clinical scoring.
