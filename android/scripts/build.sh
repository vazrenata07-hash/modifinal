#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

: "${ANDROID_JAR:?Defina ANDROID_JAR com o android.jar API 35}"
: "${ANDROID_BUILD_TOOLS:?Defina ANDROID_BUILD_TOOLS com os Build Tools 35.0.0}"
: "${ECJ_JAR:?Defina ECJ_JAR com o compilador ecj-3.42.0.jar}"
: "${PIX_KEYSTORE:?Defina PIX_KEYSTORE com o caminho da chave de assinatura}"
: "${PIX_KEYSTORE_PASSWORD:?Defina PIX_KEYSTORE_PASSWORD para assinar o APK}"
PIX_KEY_ALIAS="${PIX_KEY_ALIAS:-consultapix}"
BUILD_ROOT="$PWD/build"
mkdir -p "$BUILD_ROOT/classes" "$BUILD_ROOT/dex" "$BUILD_ROOT/generated" "$BUILD_ROOT/tests"

"$ANDROID_BUILD_TOOLS/aapt2" compile --dir app/src/main/res -o "$BUILD_ROOT/resources.zip"
"$ANDROID_BUILD_TOOLS/aapt2" link -I "$ANDROID_JAR" --manifest app/src/main/AndroidManifest.xml \
  --java "$BUILD_ROOT/generated" --auto-add-overlay -o "$BUILD_ROOT/resources.apk" "$BUILD_ROOT/resources.zip"

java -jar "$ECJ_JAR" -source 8 -target 8 -encoding UTF-8 -classpath "$ANDROID_JAR" \
  -d "$BUILD_ROOT/classes" $(find app/src/main/java "$BUILD_ROOT/generated" -name '*.java' -print)

python3 - <<'PY'
from pathlib import Path
import zipfile
root = Path('build/classes')
with zipfile.ZipFile('build/classes.jar', 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob('*.class')):
        archive.write(path, path.relative_to(root).as_posix())
PY

"$ANDROID_BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --min-api 28 --output "$BUILD_ROOT/dex" "$BUILD_ROOT/classes.jar"
python3 - <<'PY'
from pathlib import Path
import zipfile
with zipfile.ZipFile('build/resources.apk') as original:
    with zipfile.ZipFile('build/unsigned.apk', 'w') as target:
        for entry in original.infolist():
            target.writestr(entry, original.read(entry.filename))
        for dex in sorted(Path('build/dex').glob('*.dex')):
            target.write(dex, dex.name, compress_type=zipfile.ZIP_DEFLATED)
PY

"$ANDROID_BUILD_TOOLS/zipalign" -p -f 4 "$BUILD_ROOT/unsigned.apk" "$BUILD_ROOT/aligned.apk"
"$ANDROID_BUILD_TOOLS/apksigner" sign --ks "$PIX_KEYSTORE" --ks-key-alias "$PIX_KEY_ALIAS" \
  --ks-pass env:PIX_KEYSTORE_PASSWORD --key-pass env:PIX_KEYSTORE_PASSWORD \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --out "$BUILD_ROOT/ConsultaPix-Android.apk" "$BUILD_ROOT/aligned.apk"
printf '\nAPK gerado em %s\n' "$BUILD_ROOT/ConsultaPix-Android.apk"
