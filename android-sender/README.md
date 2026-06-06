# PC Lifelog Sender for Android

Android screen-time sender for PC Lifelog Stats.

The app is designed around one-time QR pairing:

1. Open PC Lifelog Stats on Windows.
2. Show the Android pairing QR.
3. Scan the QR in this Android app.
4. Grant Usage Access.
5. Tap Sync now or start 15-minute auto sync.

After pairing, the QR is not needed again. The app stores the PC endpoints and token locally on the phone.

Automatic sync uses WorkManager with an unmetered-network constraint, so it is intended to run on Wi-Fi rather than burn through mobile data. Manual Sync now still runs immediately when you press it.

## Connection Strategy

The QR can contain multiple endpoints:

- Tailscale endpoint, when available
- LAN endpoint, such as `http://192.168.x.x:8766`
- Current network endpoint, as fallback

The sender tries the previous successful endpoint first, then the endpoints from the QR.

## Build

Open this `android-sender` folder in Android Studio and build the `app` module.

This repository does not include a Gradle wrapper yet. Android Studio can use its bundled Gradle/JDK to sync the project.

From a prepared command-line environment:

```powershell
gradle assembleDebug
```

The debug APK is created at:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## Permissions

The app requires:

- Usage Access
- Internet access
- Network state access

Usage Access must be granted by the user in Android settings.
