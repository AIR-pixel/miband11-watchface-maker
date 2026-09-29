# 手环 11 动态表盘制作工具（安卓版）

和小米手环 11（212×520，Vela OS）动态表盘生成器。手机端直接出 `.face`，不需要电脑。

> 本文件只讲安卓版。**仓库总览（含 Windows 版、配置说明、免责声明）见 [仓库根 README](../README.md)**。
> `.face` 二进制格式见 [`docs/face格式规范.md`](../docs/face格式规范.md)。

## 为什么单独做了安卓版

官方打包工具 `Compiler.exe` 是从 Vela IDE 里提取的 **x86 Windows 二进制**，安卓上跑不了。

所以安卓版走的是**纯代码拼装**路线：不调用任何外部编译器，直接用 Java 按
[`.face` 二进制格式](../docs/face格式规范.md)把字节流拼出来。

好处：

- **不需要 `Compiler.exe`** —— 摆脱 x86 依赖和授权不明的第三方二进制
- **完全离线** —— 不联网、不上传素材
- 核心算法放在 `core/face/` 下，**零 Android 依赖**，纯 JavaSE 也能跑
  （`test/face/TestMain.java` 就是这么自测的）

`core/face/FaceBuilder.java` 与 Python 版 `watchface_tool/face_builder.py`
是**逐字节等价**的两份实现，产物完全一致。

## 安装

下载 [watchface-tool-android-v1.0.0.apk](../../releases/latest/download/watchface-tool-android-v1.0.0.apk)。

- 系统要求：**Android 7.0+**（minSdk 24 / targetSdk 34）
- 安装时系统可能提示「未知来源应用」，需在设置里允许
- 包名 `face.tool`，launcher 名「表盘制作」

## 使用

界面从上到下：

| 位置 | 控件 | 说明 |
|---|---|---|
| 1 | **选择视频 / 图片** | 系统文件选择器；视频、GIF、图片都可以 |
| 2 | **裁剪区** | 拖动移动 · 拖右下角缩放 · 双指捏合缩放 |
| 3 | 重置裁剪框 / 铺满画面 | 下方两个按钮 |
| 4 | **压缩程度** | 6 档：高画质 RGB / 均衡 P256 / 小体积 P128 / 极限 P64 / 极小 P32 / 微缩 P16 |
| 5 | **帧率** | 7 档：6 / 8 / 12 / 16 / 20 / 24 / 30 FPS |
| 6 | **编码格式** | PNG（无损）/ JPEG（有损·更小） |
| 7 | **帧数上限** | 7 档：32 / 48 / 64 / 96 / 128 / 192 / 240 帧 |
| 8 | **JPEG 质量** | 5 档：q90 / q85 / q80 / q70 / q60（**仅当选了 JPEG 时可点**，选 PNG 时置灰） |
| 9 | **起始 / 时长** | 单位秒；时长留空 = 取到结尾 |
| 10 | **保持帧率、压缩时长（快放）** | 见下 |
| 11 | **预估行** | 「预计 N 帧 @ X fps · 约 Y MB · 播放 Z s」，快放时额外标出倍速 |
| 12 | **生成 .face** | 产物存到 `Android/data/face.tool/files/faces/` |

### 「快放」是什么

帧数上限触顶时，抽帧和播放节奏可以解耦：

- **不勾**（默认）：自动降帧率保住时长 → 时长不变，但会掉帧
- **勾上**：帧率不变，把上限帧数摊到整段时长 → 流畅，但播放变快

两种模式抽的是**同一批帧、体积完全相同**，区别只在生成的 `main.lua` 里一个 `period` 值。

### ⚠️ 安卓版 JPEG 的质量天花板低于 Windows 版

原因是 `Bitmap.compress(Bitmap.CompressFormat.JPEG, ...)` **固定使用 4:2:0 色度子采样**，
没有参数可调。这会把 212×520 的色度平面砍到 106×260，彩色边缘出现色晕。

Windows 版用的是 PIL，可以显式指定 `subsampling=0`（4:4:4），所以那边 JPEG 观感更好。

**如果你在安卓端觉得 JPEG 画质不满意，建议直接用 PNG P64。**
这不是 bug，是平台 API 的限制。详见 [`docs/体积与画质实测.md`](../docs/体积与画质实测.md#4-jpeg-的色度子采样问题)。

## 从源码构建

不需要 Android Studio，不需要 Gradle。

**前置：**

- Android SDK，含 `build-tools` 与 `platforms`（`sdkmanager` 装即可）
- JDK **17 或更高**
- Python 或 `zip` 命令（用于把 `classes.dex` 塞进 APK）

**构建：**

```bash
cd watchface-android
bash build.sh
```

产物：`watchface-tool.apk`

脚本会自动探测 SDK / build-tools / JDK，也可以用环境变量覆盖：

```bash
ANDROID_SDK_ROOT=/path/to/sdk JAVA_HOME=/path/to/jdk bash build.sh
```

### 构建链说明

```
aapt2 link     →  生成带资源索引的 base.apk
javac          →  编译 Java（--release 8）
d8             →  class 文件 → classes.dex
（追加）       →  把 classes.dex 塞进 base.apk
zipalign       →  4 字节对齐
apksigner      →  签名（首次会自动生成 debug.keystore）
```

### 两个必踩的坑

**1. `d8.bat` / `apksigner.bat` 靠 `JAVA_HOME` 定位 JDK，不看 PATH。**

它们自己要用 JVM 运行。如果 PATH 里的 `java` 是 Java 8，会报：

```
UnsupportedClassVersionError: class file version 55.0, this version only recognizes up to 52.0
```

脚本里已强制 `export JAVA_HOME=<JDK 17+>`。

**2. `javac` 必须用 `--release 8`，不是 `-source 8 -target 8`。**

`--release` 会同时约束 API 签名；只用 `-source/-target` 会出现
「编译通过、装到手机上 `NoSuchMethodError`」这类问题。

## 目录结构

```
watchface-android/
├── build.sh                    无 Gradle 构建脚本
├── app/
│   ├── AndroidManifest.xml
│   └── src/face/tool/
│       ├── MainActivity.java   主界面与参数编排
│       ├── CropView.java       裁剪控件（拖动/角点缩放/双指缩放）
│       └── FaceGenerator.java  抽帧 → 裁切 → 量化 → 编码 → 拼装
├── core/face/                  零 Android 依赖的核心算法
│   ├── FaceBuilder.java        拼装 .face 字节流
│   ├── Quantizer.java          调色板量化（中位切分 + Floyd-Steinberg 抖动）
│   ├── PngEncoder.java         PNG 编码（含调色板写入）
│   └── LuaGen.java             生成 main.lua
└── test/face/                  核心算法自测（纯 JavaSE，可直接 java 运行）
```

`core/` 下的四个类不 import 任何 `android.*`，可以单独抽出来复用。

## 界面实现

界面是**纯代码构建**的（`MainActivity.buildUi()`），没有 layout XML ——
为了少一层资源编译依赖，构建链更简单。

主题固定用系统的 `@android:style/Theme.Material.Light.NoActionBar`（浅色），
**不跟随系统深色模式**。裁剪框的背景色是硬编码的 `0xFF282828`。
