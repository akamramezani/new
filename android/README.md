# MedConsults Dermatology — offline Android app

Native Kotlin + Jetpack Compose foundation. No WebView and no internet permission are included.

## Open
Open this `android` folder in Android Studio, allow Gradle sync, then build the app.

## Current stage
Stage 1 creates the native Android shell and the 12-presentation entry screen. It is not yet a clinical engine and must not be used for patient care.

## Next stages
1. Install and validate the exact offline knowledge export.
2. Export the frozen final model as deployable inference parameters.
3. Implement and test the original clinical rules, red flags, ranking, and question selection.
4. Connect the model only to its validated task.
5. Test offline behavior and build signed APK/AAB.

See `app/src/main/assets/ASSET_INSTALLATION.md`.
