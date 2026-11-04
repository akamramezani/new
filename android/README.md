# MedConsults Dermatology — offline Android app

Native Kotlin + Jetpack Compose foundation. No WebView and no internet permission are included.

## Open
Open this `android` folder in Android Studio, allow Gradle sync, then build the app.

## Implemented in this commit
- Native Android application shell.
- Local JSON loading from APK assets.
- All 12 presentation knowledge packages bundled locally, with manifest hashes and a CI integrity validator.
- Searchable finding checklist, diagnosis profiles, context reference, and test guidance for all 12 presentations.
- Provisional offline scaly differential ranking using the reconstructed scoring reference in the repository:
  - base diagnosis weights
  - yes/no finding multipliers raised to exponent 0.7
  - seven hard-coded correlated-finding selection groups
  - residual estimate: `0.05 + 0.06 * exp(-n / 3)`
- Per-diagnosis contribution trace showing each retained finding's source multiplier, applied multiplier, and before/after model weight.
- Baseline-versus-finding-adjusted normalised share comparison.
- Safety reminders from each presentation are displayed; these are not automated triage gates.

## Not yet implemented
- Scoring models for the other 11 presentations. Their knowledge content is available, but no verified scoring implementation is present.
- Full red-flag gating logic (the displayed safety reminders are not an automated triage gate).
- Application of context modifiers to ranking; they are currently reference-only.
- Adaptive next-question selection.
- Automated confirmatory-test selection and post-test updating.
- Production scoring parity tests or a verified production test-vector set.
- Deployment-ready RBF model inference. The repository's nested-CV JSONs contain validation predictions/metrics and fold results; they are not, by themselves, a serialized fitted model for new cases.

## Safety
This is a development prototype, not a validated medical device. The scaly ranking is a reconstructed provisional model, not proven equivalent to the live website and not suitable for clinical decisions. The other presentations expose knowledge/reference content only and do not calculate diagnostic rankings. Production scoring parity and clinical validation are required before clinical use.

See `app/src/main/assets/ASSET_INSTALLATION.md`.
