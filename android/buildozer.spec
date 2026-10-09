[app]
title = Rolimons Ad Poster
package.name = rolimonsadposter
package.domain = io.github.rxst0

# The build copies ../roliposter, ../assets and ../config.example.json in here first
# (see .github/workflows/android.yml), so the APK uses the same engine as the PC app.
source.dir = .
source.include_exts = py,kv,png,json
source.exclude_dirs = .devdata, bin, .buildozer, __pycache__

version.regex = __version__ = "(.*)"
version.filename = %(source.dir)s/roliposter/__init__.py

# charset-normalizer 2.x is pure Python (3.x ships host-compiled extensions that break on Android).
requirements = python3,kivy==2.3.1,requests,urllib3,certifi,idna,charset-normalizer==2.1.1,pyjnius,android

icon.filename = %(source.dir)s/assets/icon-512.png
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #15181D
orientation = portrait
fullscreen = 0

# Background posting: a sticky foreground service. Android 14+ requires a type; "specialUse" has no
# daily time limit (unlike dataSync, which Android 15 caps at 6 hours a day).
services = Poster:service.py:foreground:sticky:foregroundServiceType=specialUse

android.permissions = INTERNET, ACCESS_NETWORK_STATE, FOREGROUND_SERVICE, FOREGROUND_SERVICE_SPECIAL_USE, POST_NOTIFICATIONS, WAKE_LOCK, REQUEST_IGNORE_BATTERY_OPTIMIZATIONS

android.api = 35
android.minapi = 26
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
# The cookie must never be copied off the phone by Android's cloud backup.
android.allow_backup = False
android.release_artifact = apk
android.debug_artifact = apk

p4a.branch = v2026.05.09

[buildozer]
log_level = 2
warn_on_root = 0
