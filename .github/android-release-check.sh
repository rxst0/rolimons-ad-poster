#!/usr/bin/env bash
# Release APK check: install the signed APK (ARM, run through the emulator's ARM translation),
# launch it, and make sure it starts, draws its UI and stays running without Python errors.
set -x
PKG=io.github.rxst0.rolimonsadposter
OUT=shots
mkdir -p "$OUT"

if ! adb install -r -g apk/RolimonsAdPoster.apk 2>&1 | tee "$OUT/install.txt" | grep -q Success; then
  echo "APK failed to install"; exit 1
fi
adb shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS || true
adb logcat -c
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1
sleep 45
adb exec-out screencap -p > "$OUT/launch.png"
adb logcat -d > "$OUT/logcat.txt"
grep -E " python *:| PythonActivity" "$OUT/logcat.txt" > "$OUT/python.txt" || true

status=0
if ! adb shell pidof "$PKG" > /dev/null; then
  echo "App is not running 45 seconds after launch"; status=1
fi
if grep -q "Traceback" "$OUT/python.txt"; then
  echo "Python error during startup:"; grep -A 15 "Traceback" "$OUT/python.txt" | head -40; status=1
fi
exit $status
