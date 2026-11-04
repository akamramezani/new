# Offline clinical assets — pending integration

This app must not generate clinical rankings until the exact production assets are installed and validated.

## Required knowledge export
Expected destination: `knowledge/derm_bootstrap.json`

It must be the exact exported knowledge package used by the website, including the 12 presentations, diagnoses, findings, tests, context modifiers, urgent rules, base weights, likelihood modifiers, correlated-finding correction metadata, and question-selection metadata.

## Required deployable RBF model
Expected destination: `model/rbf_deployable_model.json`

The nested-CV result JSON and out-of-fold predictions are validation artifacts, not deployable inference weights. A deployable RBF artifact must include exact feature order, fitted preprocessing/scaler parameters, support vectors, dual coefficients, intercept, kernel/gamma, target definition, and frozen output transformations.

## Safety requirement
Red-flag rules must execute before ranking. Preserve the existing clinical scoring and question-selection logic. Do not replace it with an approximate RBF formula. The app must fail closed if required assets are absent or invalid.
