[app]
title = Rolimons Ad Poster
package.name = rolimonsadposter
package.domain = io.github.rxst0

# The build copies ../roliposter, ../assets and ../config.example.json in here first
# (see .github/workflows/android.yml), so the APK uses the same engine as the PC app.
source.dir = .
source.include_exts = py,kv,png,json,ttf,txt
source.exclude_dirs = .devdata, bin, .buildozer, __pycache__

version.regex = __version__ = "(.*)"
version.filename = %(source.dir)s/roliposter/__init__.py

# requests pulls in charset-normalizer, which publishes a pure-Python wheel that works on Android.
requirements = python3,kivy==2.3.1,requests,urllib3,certifi,idna,charset-normalizer,pyjnius,android

icon.filename = %(source.dir)s/assets/icon-512.png
# Adaptive icon (Android 8+): same artwork as the PC icon, cropped to each launcher's shape.
icon.adaptive_foreground.filename = %(source.dir)s/assets/icon-fg.png
icon.adaptive_background.filename = %(source.dir)s/assets/icon-bg.png
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #15181D
orientation = portrait
fullscreen = 0

# Background posting: a sticky foreground service. Android 14+ requires a type; "specialUse" has no
# daily time limit (unlike dataSync, which Android 15 caps at 6 hours a day).
services = Poster:service.py:foreground:sticky:foregroundServiceType=specialUse

# Java helper for the view-only Received trades tab (android/java/org/roliposter/).
android.add_src = java

android.permissions = INTERNET, ACCESS_NETWORK_STATE, FOREGROUND_SERVICE, FOREGROUND_SERVICE_SPECIAL_USE, POST_NOTIFICATIONS, WAKE_LOCK, REQUEST_IGNORE_BATTERY_OPTIMIZATIONS

android.api = 35
android.minapi = 26
# 64-bit ARM only: python-for-android corrupts its pip when building two archs in one run
# (kivy/python-for-android#3364). Every current phone is 64-bit.
android.archs = arm64-v8a
android.accept_sdk_license = True
# The cookie must never be copied off the phone by Android's cloud backup.
android.allow_backup = False
android.release_artifact = apk
android.debug_artifact = apk

p4a.branch = v2026.05.09

[buildozer]
log_level = 2
warn_on_root = 0
