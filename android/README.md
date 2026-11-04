# MedConsults Dermatology — offline Android app

Native Kotlin + Jetpack Compose foundation. No WebView and no internet permission are included.

## Open
Open this `android` folder in Android Studio, allow Gradle sync, then build the app.

## Implemented in this commit
- Native Android application shell.
- Local JSON loading from APK assets.
- Scaly presentation knowledge package bundled at `app/src/main/assets/knowledge/presentation_scaly.json`.
- Finding checklist for the 40 scaly findings.
- Offline scaly differential ranking using the reconstructed scoring reference in the repository:
  - base diagnosis weights
  - yes/no likelihood multipliers raised to exponent 0.7
  - seven documented correlated-finding selection groups
  - residual estimate currently validated for scaly only: `0.05 + 0.06 * exp(-n / 3)`
- Safety reminders from the scaly presentation are displayed.

## Not yet implemented
- Remaining 11 presentation JSON packages.
- Full red-flag gating logic (the displayed safety reminders are not an automated triage gate).
- Context modifiers and their application to ranking.
- Adaptive next-question selection.
- Confirmatory test selection and post-test probability updating.
- Deployment-ready RBF model inference. The repository's nested-CV JSONs contain validation predictions/metrics and fold results; they are not, by themselves, a serialized fitted model for new cases.
- Automated parity tests against the production API and Android build verification.

## Safety
This is a development prototype, not a validated medical device. The scaly ranking component must pass deterministic parity tests against the reference implementation and production API before clinical use. Other presentations must remain unavailable until their data and scoring rules are independently validated.

See `app/src/main/assets/ASSET_INSTALLATION.md`.
