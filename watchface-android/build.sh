#!/bin/bash
# 无 Gradle 构建安卓 APK。
#
# 流程：aapt2 link → javac → d8 → 塞 classes.dex → zipalign → apksigner
# 产物：watchface-tool.apk
#
# 需要：Android SDK（build-tools + platforms）、JDK 17+、python（可选，仅用于塞 dex）
#
# 所有路径都会自动探测；也可以用环境变量覆盖：
#   ANDROID_SDK_ROOT / ANDROID_HOME   Android SDK 根目录
#   JAVA_HOME                         JDK 根目录
#
# ─────────────────────────────────────────────────────────────────────
# 两个必踩的坑（已在本脚本中处理）：
#
# 1. d8.bat / apksigner.bat 是靠 **JAVA_HOME** 去定位 JDK 的，
#    而不是 PATH 里的 java。如果 PATH 里的 `java` 是 Java 8，
#    会报 UnsupportedClassVersionError（class 55.0 vs 52.0）——
#    因为 d8 自己要用 JVM 跑。所以下面强制 export 一个 JDK 17+ 的 JAVA_HOME。
#
# 2. javac 用 `--release 8`（不是 `-source/-target 8`）。
#    `--release` 会同时约束 API 签名，产出的字节码才能在 minSdk 24 上跑；
#    只用 -source/-target 会出现「编译过、装上去 NoSuchMethodError」。
# ─────────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")"

die() { echo "错误：$*" >&2; exit 1; }

# ---------------------------------------------------------------- 找 SDK
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [ -z "$SDK" ]; then
  for c in \
    "$HOME/AppData/Local/Android/Sdk" \
    "/c/Users/$USER/AppData/Local/Android/Sdk" \
    "$HOME/Library/Android/sdk" \
    "$HOME/Android/Sdk" \
    "/usr/lib/android-sdk"; do
    [ -d "$c" ] && SDK="$c" && break
  done
fi
[ -n "$SDK" ] && [ -d "$SDK" ] || die "找不到 Android SDK。请设置 ANDROID_SDK_ROOT。"

# ---------------------------------------------------------------- 找 build-tools（取版本最高的）
# 注意：Windows 的 build-tools 里是 aapt2.exe / d8.bat / apksigner.bat，
# 不带扩展名的同名文件在 Linux/macOS 上才有。所以要显式挑。
pick_tool() {
  _base="$1"
  for _c in "$BT/$_base.exe" "$BT/$_base.bat" "$BT/$_base"; do
    [ -f "$_c" ] && { echo "$_c"; return 0; }
  done
  return 1
}

BT=""
for d in $(ls -1d "$SDK"/build-tools/*/ 2>/dev/null | sort -V -r); do
  if [ -f "${d}aapt2.exe" ] || [ -f "${d}aapt2" ] || [ -f "${d}aapt2.bat" ]; then
    BT="${d%/}"; break
  fi
done
[ -n "$BT" ] || die "在 $SDK/build-tools 下找不到 build-tools。请用 sdkmanager 安装。"

AAPT2=$(pick_tool aapt2)         || die "build-tools 里没有 aapt2"
D8=$(pick_tool d8)               || die "build-tools 里没有 d8"
ZIPALIGN=$(pick_tool zipalign)   || die "build-tools 里没有 zipalign"
APKSIGNER=$(pick_tool apksigner) || die "build-tools 里没有 apksigner"

# ---------------------------------------------------------------- 找 platform（取 android.jar 版本最高的）
PLATFORM=""
for d in $(ls -1d "$SDK"/platforms/android-*/ 2>/dev/null | sort -V -r); do
  if [ -f "${d}android.jar" ]; then PLATFORM="${d%/}/android.jar"; break; fi
done
[ -n "$PLATFORM" ] || die "在 $SDK/platforms 下找不到 android.jar。"

# ---------------------------------------------------------------- 找 JDK
JH="${JAVA_HOME:-}"
if [ -z "$JH" ] || [ ! -d "$JH" ]; then
  JH=""
  for c in \
    "/c/Program Files/Microsoft"/jdk-* \
    "/c/Program Files/Java"/jdk-* \
    "/c/Program Files/Eclipse Adoptium"/jdk-* \
    "/usr/lib/jvm"/*; do
    [ -x "$c/bin/javac" ] && JH="$c" && break
  done
fi
[ -n "$JH" ] || die "找不到 JDK。请设置 JAVA_HOME 指向 JDK 17 或更高版本。"
export JAVA_HOME="$JH"
JAVAC="$JH/bin/javac"
KEYTOOL="$JH/bin/keytool"
[ -x "$JAVAC" ] || die "JAVA_HOME=$JH 里没有 bin/javac。"

# ---------------------------------------------------------------- 找 python（仅用于向 apk 追加 dex）
PY=""
for c in "$PYTHON" python3 python py; do
  if [ -n "$c" ] && command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

# ---------------------------------------------------------------- 报告环境
echo "SDK        : $SDK"
echo "build-tools: $(basename "$BT")"
echo "platform   : $(basename "$(dirname "$PLATFORM")")"
echo "JAVA_HOME  : $JH"
echo "python     : ${PY:-（无，将改用 zip 命令）}"
echo

rm -rf out && mkdir -p out/classes out/apk

echo "=== 1/6 javac 编译 ==="
"$JAVAC" --release 8 -encoding UTF-8 -nowarn -classpath "$PLATFORM" \
  -d out/classes \
  $(find core app/src -name "*.java")

echo "=== 2/6 aapt2 link ==="
"$AAPT2" link -o out/apk/base.apk -I "$PLATFORM" \
  --manifest app/AndroidManifest.xml --min-sdk-version 24 --target-sdk-version 34

echo "=== 3/6 d8 → classes.dex ==="
"$D8" --release --lib "$PLATFORM" --output out/apk/ \
  $(find out/classes -name "*.class")

echo "=== 4/6 塞 classes.dex ==="
cd out/apk
if [ -n "$PY" ]; then
  "$PY" -c "import zipfile; z=zipfile.ZipFile('base.apk','a'); z.write('classes.dex','classes.dex'); z.close()"
elif command -v zip >/dev/null 2>&1; then
  zip -q base.apk classes.dex
else
  die "需要 python 或 zip 命令之一，用来把 classes.dex 追加进 apk。"
fi
cd ../..

echo "=== 5/6 zipalign + 签名 ==="
"$ZIPALIGN" -f 4 out/apk/base.apk out/apk/aligned.apk
if [ ! -f debug.keystore ]; then
  echo "（未找到 debug.keystore，自动生成一个）"
  "$KEYTOOL" -genkeypair -v -keystore debug.keystore -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Debug,O=Debug,C=CN"
fi
"$APKSIGNER" sign --ks debug.keystore --ks-pass pass:android --key-pass pass:android \
  --out watchface-tool.apk out/apk/aligned.apk

echo "=== 6/6 完成 ==="
ls -la watchface-tool.apk
