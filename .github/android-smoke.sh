#!/usr/bin/env bash
# Emulator smoke test: opens each screen, then starts the background service with a fake cookie
# (Rolimons rejects it, which proves the service ran and reported back). Results go to shots/.
set -x
PKG=io.github.rxst0.rolimonsadposter
ACTIVITY=$PKG/org.kivy.android.PythonActivity
OUT=shots
mkdir -p "$OUT"
APK=$(ls apk/*.apk | head -1)
adb install -r -g "$APK"

launch() {
  local name=$1
  shift
  adb shell am force-stop "$PKG"
  adb shell am start -n "$ACTIVITY" --es demo 1 "$@"
  sleep 30
  adb exec-out screencap -p > "$OUT/$name.png"
}

launch home
launch edit --es screen edit --es search dom
launch settings --es screen settings
launch history --es screen history
launch login --es login 1

adb shell am force-stop "$PKG"
printf 'ROLI_VERIFICATION=aaaaaaaa.bbbbbbbb.cccccccc\n' | \
  adb shell "run-as $PKG sh -c 'mkdir -p files/roliposter && cat > files/roliposter/.env'"
launch service-start --es autostart 1
sleep 30
adb exec-out screencap -p > "$OUT/service-result.png"

adb shell "run-as $PKG find files -maxdepth 3" > "$OUT/files.txt" 2>&1
adb shell "run-as $PKG cat files/roliposter/status.json" > "$OUT/status.json" 2>&1
adb shell "run-as $PKG cat files/roliposter/logs/poster.log" > "$OUT/poster.log" 2>&1
adb shell dumpsys activity services "$PKG" > "$OUT/services.txt" 2>&1
adb logcat -d > "$OUT/logcat.txt"
grep -iE "python|traceback|error" "$OUT/logcat.txt" | tail -200 > "$OUT/python.txt"

# Usability test: from a clean install, drive the real UI through the main flows (android/selftest.py).
adb shell am force-stop "$PKG"
adb shell pm clear "$PKG"
adb shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS || true
adb logcat -c
adb shell am start -n "$ACTIVITY" --es selftest 1
for i in $(seq 1 120); do
  if adb shell "run-as $PKG test -f files/roliposter/selftest.json"; then break; fi
  sleep 5
done
adb shell "run-as $PKG cat files/roliposter/selftest.json" > "$OUT/selftest.json" 2>&1
mkdir -p "$OUT/selftest"
for shot in $(adb shell "run-as $PKG ls files/roliposter/selftest" | tr -d '\r'); do
  adb exec-out "run-as $PKG cat files/roliposter/selftest/$shot" > "$OUT/selftest/$shot"
done
adb logcat -d | grep "SELFTEST" > "$OUT/selftest.log" || true
cat "$OUT/selftest.log"
python3 - "$OUT/selftest.json" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception as e:
    sys.exit(f"Self-test produced no results: {e}")
for r in data["results"]:
    print(("PASS " if r["ok"] else "FAIL ") + r["step"], r["detail"][:200] if not r["ok"] else "")
print(f"{data['passed']}/{data['total']} passed")
sys.exit(0 if data["total"] >= 13 and data["passed"] == data["total"] else 1)
PY
