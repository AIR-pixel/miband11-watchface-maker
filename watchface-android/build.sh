#!/bin/bash
# 无 Gradle 构建安卓 APK（Kotlin UI + Java 核心算法）。
#
# 流程：aapt2 link → javac(Java) → kotlinc(Kotlin) → R8 → 塞 classes.dex → zipalign → apksigner
# 产物：watchface-tool.apk
#
# 需要：Android SDK（build-tools + platforms）、JDK 17+、Kotlin CLI（见 fetch_kotlinc.sh）、
#       python 或 zip（仅用于塞 dex）
#
# 路径自动探测，也可用环境变量覆盖：
#   ANDROID_SDK_ROOT / ANDROID_HOME   Android SDK 根目录
#   JAVA_HOME                         JDK 根目录
#   KOTLINC_DIR                       Kotlin CLI 的 jar 目录（默认 ./.kotlinc）
#   NOR8=1                            跳过 R8 压缩（快很多，但 APK 会大 2 MB）
#
# ─────────────────────────────────────────────────────────────────────
# 几个必踩的坑（都已在本脚本里处理）：
#
# 1. d8.bat / apksigner.bat / R8 是靠 **JAVA_HOME** 去定位 JDK 的，
#    而不是 PATH 里的 java。如果 PATH 里的 `java` 是 Java 8，
#    会报 UnsupportedClassVersionError（class 55.0 vs 52.0）——
#    因为 d8 自己要用 JVM 跑。所以下面强制 export 一个 JDK 17+ 的 JAVA_HOME。
#
# 2. javac 用 `--release 8`（不是 `-source/-target 8`）。
#    `--release` 会同时约束 API 签名，产出的字节码才能在 minSdk 24 上跑；
#    只用 -source/-target 会出现「编译过、装上去 NoSuchMethodError」。
#
# 3. Git Bash 下 classpath 用 ';' 分隔时 **不会** 做路径转换，
#    `/c/Users/...` 这种形式 java 认不出来，症状是
#    `ClassNotFoundException: org.jetbrains.kotlin.cli.jvm.K2JVMCompiler`
#    （看起来像 jar 坏了，其实路径没转）。所以所有要给 kotlinc / R8 的
#    classpath 都先过一遍 `cygpath -w`。
#
# 4. kotlinc 的 `-no-stdlib` 只关掉「自动把 kotlin-home 里的 stdlib 加进编译
#    classpath」，不等于「不需要 stdlib」—— 还得自己把 kotlin-stdlib.jar
#    写进 -classpath，否则每个内建类型都报
#    `cannot access built-in declaration 'kotlin.String'`。
#
# 5. d8 / R8 要显式带上 kotlin-stdlib.jar，否则运行时报
#    `NoClassDefFoundError: kotlin/jvm/internal/Intrinsics`。
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
JAVA="$JH/bin/java"
KEYTOOL="$JH/bin/keytool"
[ -x "$JAVAC" ] || die "JAVA_HOME=$JH 里没有 bin/javac。"

# ---------------------------------------------------------------- 找 Kotlin CLI
KD="${KOTLINC_DIR:-$PWD/.kotlinc}"
[ -s "$KD/kotlin-compiler-embeddable.jar" ] || \
  die "在 $KD 找不到 Kotlin 编译器。先跑一次：bash fetch_kotlinc.sh"

# 注意：classpath 分隔符必须用 ';'（Windows 语义），且路径要转成 C:\ 形式
KCP=""
for j in kotlin-compiler-embeddable.jar kotlin-stdlib.jar kotlin-reflect.jar \
         kotlin-script-runtime.jar kotlinx-coroutines-core-jvm.jar \
         trove4j.jar annotations.jar; do
  [ -s "$KD/$j" ] || die "$KD 里缺少 $j。删掉该目录后重跑 fetch_kotlinc.sh"
  KCP="$KCP$(cygpath -w "$KD/$j");"
done
STDLIB="$KD/kotlin-stdlib.jar"

# ---------------------------------------------------------------- 找 R8（Android SDK 自带，不用另外下）
R8=""
for c in "$SDK"/cmdline-tools/*/lib/r8.jar "$SDK"/build-tools/*/lib/r8.jar; do
  [ -f "$c" ] && R8="$c" && break
done

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
echo "Kotlin     : $KD"
if [ -n "$NOR8" ]; then
  echo "压缩       : 关闭（NOR8=1）"
elif [ -n "$R8" ]; then
  echo "压缩       : R8（$R8）"
else
  echo "压缩       : 找不到 r8.jar，退回 d8（APK 会大约 +2 MB）"
fi
echo "python     : ${PY:-（无，将改用 zip 命令）}"
echo

rm -rf out && mkdir -p out/classes out/apk out/r8

# ---------------------------------------------------------------- 1a javac（核心算法 + FaceGenerator，纯 JavaSE）
# core/ 是零 Android 依赖的算法；app/src/ 下的 FaceGenerator.java 是算法与界面之间的编排层。
# 界面层（MainActivity / CropView）已经是 Kotlin，见下一步。
echo "=== 1/6 javac 编译 Java 部分 ==="
"$JAVAC" --release 8 -encoding UTF-8 -nowarn -classpath "$PLATFORM" \
  -d out/classes \
  $(find core app/src -name "*.java")

# ---------------------------------------------------------------- 1b kotlinc（界面层）
echo "=== 2/6 kotlinc 编译 app/src/ ==="
PLATFORM_W=$(cygpath -w "$PLATFORM")
CLASSES_W=$(cygpath -w "$PWD/out/classes")
STDLIB_W=$(cygpath -w "$STDLIB")
"$JAVA" -cp "$KCP" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler \
  -classpath "$PLATFORM_W;$CLASSES_W;$STDLIB_W" \
  -jvm-target 17 -no-stdlib -nowarn \
  -d out/classes \
  $(find app/src -name "*.kt")

# ---------------------------------------------------------------- 2 aapt2 link
echo "=== 3/6 aapt2 link ==="
"$AAPT2" link -o out/apk/base.apk -I "$PLATFORM" \
  --manifest app/AndroidManifest.xml --min-sdk-version 24 --target-sdk-version 34

# ---------------------------------------------------------------- 3 dex
CLASSES=$(find out/classes -name "*.class")
if [ -n "$R8" ] && [ -z "$NOR8" ]; then
  echo "=== 4/6 R8（tree-shake + 混淆，把 kotlin-stdlib 摇掉）==="
  "$JAVA" -cp "$(cygpath -w "$R8")" com.android.tools.r8.R8 \
    --release --lib "$PLATFORM_W" --min-api 24 \
    --pg-conf r8-rules.pro \
    --output out/r8 \
    $CLASSES "$STDLIB_W"
  cp out/r8/classes.dex out/apk/classes.dex
else
  echo "=== 4/6 d8 → classes.dex ==="
  "$D8" --release --lib "$PLATFORM" --min-api 24 --output out/apk/ \
    $CLASSES "$STDLIB"
fi

# ---------------------------------------------------------------- 4 塞 dex
echo "=== 5/6 塞 classes.dex ==="
cd out/apk
if [ -n "$PY" ]; then
  "$PY" -c "import zipfile; z=zipfile.ZipFile('base.apk','a'); z.write('classes.dex','classes.dex'); z.close()"
elif command -v zip >/dev/null 2>&1; then
  zip -q base.apk classes.dex
else
  die "需要 python 或 zip 命令之一，用来把 classes.dex 追加进 apk。"
fi
cd ../..

# ---------------------------------------------------------------- 5 zipalign + 签名
echo "=== 6/6 zipalign + 签名 ==="
"$ZIPALIGN" -f 4 out/apk/base.apk out/apk/aligned.apk
if [ ! -f debug.keystore ]; then
  echo "（未找到 debug.keystore，自动生成一个）"
  "$KEYTOOL" -genkeypair -v -keystore debug.keystore -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Debug,O=Debug,C=CN"
fi
"$APKSIGNER" sign --ks debug.keystore --ks-pass pass:android --key-pass pass:android \
  --out watchface-tool.apk out/apk/aligned.apk

echo
echo "=== 完成 ==="
ls -l watchface-tool.apk
echo "classes.dex: $(stat -c%s out/apk/classes.dex 2>/dev/null || wc -c < out/apk/classes.dex) 字节"
