#!/bin/bash
# 拉一套最小可用的 Kotlin 命令行编译器（约 62 MB）。
#
# 为什么不用官方 kotlin-compiler-*.zip（约 80 MB）：
#   kotlin-compiler-embeddable + 6 个依赖 jar 就够跑 K2JVMCompiler，
#   不用解压、不用配 KOTLIN_HOME，直接 java -cp 敲主类。
#
# 目标目录（默认 ./.kotlinc，已在 .gitignore 里）：
#   build.sh 会自动从这里取；也可以用 KOTLINC_DIR 环境变量指到别处。
#
# 用法：bash fetch_kotlinc.sh
set -e
cd "$(dirname "$0")"

VER="${KOTLIN_VERSION:-2.2.20}"
CORO_VER="${COROUTINES_VERSION:-1.8.1}"
DIR="${KOTLINC_DIR:-$PWD/.kotlinc}"
# 主源 + 境内镜像。直连 Maven Central 时常见 502/超时，镜像能救回来。
MIRRORS=(
  "https://repo1.maven.org/maven2"
  "https://maven.aliyun.com/repository/central"
)

mkdir -p "$DIR"
echo "目标目录：$DIR"
echo "Kotlin    ：$VER"
echo

# 下载：逐个镜像试，每个镜像内带重试。任一成功即返回。
fetch() {
  name="$1"; path="$2"
  if [ -s "$DIR/$name" ]; then
    echo "  ✓ $name 已存在，跳过"
    return 0
  fi
  for base in "${MIRRORS[@]}"; do
    echo "  ↓ $name  ← $base"
    if curl -L -sS --fail \
         --retry 6 --retry-all-errors --retry-delay 3 \
         --connect-timeout 20 -o "$DIR/$name" "$base/$path" 2>/dev/null; then
      return 0
    fi
  done
  echo "  ✗ $name 所有源都失败：$path" >&2
  exit 1
}

fetch kotlin-compiler-embeddable.jar "org/jetbrains/kotlin/kotlin-compiler-embeddable/$VER/kotlin-compiler-embeddable-$VER.jar"
fetch kotlin-stdlib.jar               "org/jetbrains/kotlin/kotlin-stdlib/$VER/kotlin-stdlib-$VER.jar"
fetch kotlin-reflect.jar              "org/jetbrains/kotlin/kotlin-reflect/$VER/kotlin-reflect-$VER.jar"
fetch kotlin-script-runtime.jar       "org/jetbrains/kotlin/kotlin-script-runtime/$VER/kotlin-script-runtime-$VER.jar"
fetch kotlinx-coroutines-core-jvm.jar "org/jetbrains/kotlinx/kotlinx-coroutines-core-jvm/$CORO_VER/kotlinx-coroutines-core-jvm-$CORO_VER.jar"
fetch trove4j.jar                     "org/jetbrains/intellij/deps/trove4j/1.0.20200330/trove4j-1.0.20200330.jar"
fetch annotations.jar                 "org/jetbrains/annotations/24.1.0/annotations-24.1.0.jar"

echo
echo "完成。文件清单："
ls -l "$DIR"
echo
echo "自检："
echo "  java -cp \"<上面这些 jar 用 ; 串起来>\" \\"
echo "       org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -version"
echo
echo "注意：Git Bash 下 classpath 用 ';' 分隔时不会自动做路径转换，"
echo "      路径必须写成 C:\\... 形式（否则报 ClassNotFoundException）。"
echo "      build.sh 里已经用 cygpath -w 处理过了。"
