# ENYGMA — the native shell

Wraps the live ENYGMA at `https://enygma.arkhm.io` in an Android app, so the web
app stays the one source of truth and updates the moment you deploy to the Spark,
with no rebuild. What the shell adds is the things a browser tab cannot do.

The reason to have it at all is **recording**. In a browser, `MediaRecorder` runs
only while the page is open: the screen goes off, Android reclaims the tab, the
meeting is gone. Inside this shell the recording runs in a foreground service
with a notification, which Android will not kill, so he can press record, put the
phone in his pocket, and press stop an hour later.

The web app already knows about both. `src/static/js/app.js` picks its engine at
runtime — `window.Capacitor.isNativePlatform()` — so the same Record button uses
`MediaRecorder` in a browser and the plugin here, and nothing else in the app has
to know which it got.

---

## Build it

Needs Node and Android Studio, which the `phntm-twa` setup already put on this
machine. From this folder:

    npm init -y
    npm install @capacitor/core@latest @capacitor/cli@latest @capacitor/android@latest
    npm install @capacitor/filesystem@latest
    npm install @capgo/capacitor-audio-recorder@latest
    npm install @capawesome-team/capacitor-android-foreground-service@latest

    npx cap add android
    npx cap sync
    npx cap open android      # Android Studio -> Run on the Fold

`capacitor.config.json` is already written and already points at
`enygma.arkhm.io`, so `cap init` is not needed and would overwrite it.

Use `@latest` for everything. The plugin majors track Capacitor's major, and
pinning versions from memory is how a build breaks for no visible reason.

## After `npx cap add android`, edit two things

Both are in `android/app/src/main/AndroidManifest.xml`. `cap sync` does not
overwrite them once they are there.

**1. Permissions**, inside `<manifest>` and above `<application>`:

```xml
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MICROPHONE" />
<uses-permission android:name="android.permission.WAKE_LOCK" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
```

And inside `<application>`, so the service is allowed to hold the microphone:

```xml
<service
    android:name="io.capawesome.capacitorjs.plugins.foregroundservice.AndroidForegroundService"
    android:foregroundServiceType="microphone" />
<receiver android:name="io.capawesome.capacitorjs.plugins.foregroundservice.NotificationActionBroadcastReceiver" />
```

`foregroundServiceType="microphone"` is the part that matters. With the wrong
type, Android 14 and up refuses to start the service and the recording quietly
becomes an ordinary foreground one that dies with the screen.

**2. Orientation.** On `<activity android:name=".MainActivity">`:

```xml
android:screenOrientation="unspecified"
```

`unspecified` means *follow the phone*, which is what he asked for: locked when
his rotation lock is on, free when it is off. This is the whole reason the app
was ignoring his rotation lock as a PWA — Android bakes an orientation into the
installed package, and the old web manifest claimed `"any"`, which is an
explicit "I handle every orientation" and overrides the lock. If you ever want it
pinned regardless of the phone, that is `"portrait"` here, not in the web
manifest.

## Icons

    npm install -D @capacitor/assets
    npx capacitor-assets generate --android

Point it at ENYGMA's existing 512px icon (`src/static/icons/icon-512.png` in the
app repo) placed at `assets/icon.png` here.

## What this does not fix

The web UI. Same HTML, same CSS, same layout, same everything — a shell is a
jacket, not a redesign.

And it is `server.url`, which Capacitor's own documentation calls "not intended
for use in production". That warning is about app-store review and about losing
offline behaviour. Neither store review nor offline applies here: this is
sideloaded onto one phone, and ENYGMA has never worked offline because it is
server-rendered from the Spark. What it does mean is that if the Spark or the
tunnel is down, the app shows `www/unreachable.html` rather than anything useful.
That is a real limitation and it is the price of the web app being the one source
of truth.

## Next, when they are wanted

Each is one plugin and a few lines, and none of them are needed for recording:

- Biometric unlock — `@aparajita/capacitor-biometric-auth`, a face or fingerprint
  gate in front of the passkey.
- Push — `@capacitor/push-notifications`. The Friday note is written, a
  transcription finished, a recording failed.
- Share target — take an audio file from any app straight into ENYGMA.
