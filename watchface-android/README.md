# 手环 11 表盘自定义工具（安卓版）

小米手环 11（212×520，Vela OS）的表盘制作与自定义工具。手机端直接出 `.face`，不需要电脑。

除了动态壁纸，还能配**息屏 AOD、主屏时间日期、点击交互、多壁纸** ——
与 [Windows 版](../README.md)功能对齐。

> 本文件只讲安卓版。**仓库总览（含 Windows 版、配置说明、免责声明）见 [仓库根 README](../README.md)**。
> `.face` 二进制格式见 [`docs/face格式规范.md`](../docs/face格式规范.md)。

## 为什么单独做了安卓版

官方打包工具 `Compiler.exe` 是从 Vela IDE 里提取的 **x86 Windows 二进制**，安卓上跑不了。

所以安卓版走的是**纯代码拼装**路线：不调用任何外部编译器，直接按
[`.face` 二进制格式](../docs/face格式规范.md)把字节流拼出来。

好处：

- **不需要 `Compiler.exe`** —— 摆脱 x86 依赖和授权不明的第三方二进制
- **完全离线** —— 不联网、不上传素材
- 核心算法放在 `core/face/` 下，**零 Android 依赖**，纯 JavaSE 也能跑
  （`test/face/TestMain.java` 就是这么自测的）

`core/face/FaceBuilder.java` 与 Python 版 `watchface_tool/face_builder.py`
是**逐字节等价**的两份实现，产物完全一致：

| 产物 | 与官方 `Compiler.exe` 输出对比 |
|---|---|
| 不带 AOD | **7/7 字节一致** |
| 带 AOD | **6/6 字节一致** |

> 这个结论不是靠肉眼看代码得出的。两边各自跑真实产物再做逐字节差分，
> 样本集按「能触发哪些分支」设计（帧数 1/2/3/5/8/12；AOD 的空 / 时间 / 时间+日期 /
> 黑底 / 大字号 / 自定义色）。过程中揪出三个**只在特定样本上才现形**的 bug，
> 详见 [`docs/项目经验.md`](../docs/项目经验.md) 的 Bug 4/5/6。

### 语言分工：界面 Kotlin，算法 Java

- **`app/src/face/tool/` 下的界面层是 Kotlin**（`MainActivity.kt` / `CropView.kt` / `AodPreviewView.kt`）——
  几百行命令式构建 View 的代码，Kotlin 的 `apply`、lambda、SAM 转换能省掉一大截样板。
- **`core/face/` 和 `FaceGenerator.java` / `AodRenderer.java` 保持 Java** —— 这部分已经逐字节验证过，
  没有理由为了语言统一去冒重写的风险；而且它零 Android 依赖，桌面 JVM 也能编。
  AOD 也按同样思路拆开：`core/face/AodGen.java` 是**纯逻辑**（布局规划 + 描述记录推导 +
  体积预估，可对拍），屏幕绘制才落到 `app/src/face/tool/AodRenderer.java`。

**Kotlin 会不会让 APK 变大？** 这是上 Kotlin 前最该问的问题，实测结论是**不会**。

下面三行是 v1.1.0 时为回答这个问题专门量的（同一份界面分别用三种方式构建）：

| 构建（v1.1.0 界面） | classes.dex | APK |
|---|---|---|
| 纯 Java | 42,208 B | 49,555 B |
| Kotlin，直接 d8（不过滤） | 2,149,124 B | 2,158,995 B |
| Kotlin + **R8 full mode** | 42,696 B | **53,651 B** |

不压缩时 kotlin-stdlib 会带进 **1108 个 `kotlin/*` 类**、APK 涨 2.06 MB；
过一遍 R8 后这些类**全部被 tree-shake 掉（归零）**，dex 里只剩 `face/tool/*`。

当前 v2.0.0（多了 AOD / 多壁纸 / 第二页）：

| 构建 | classes.dex | APK |
|---|---|---|
| v1.1.0（Kotlin + R8） | 42,696 B | 53,651 B |
| **v2.0.0（Kotlin + R8）** | **79,448 B** | **90,515 B** |

涨的这 37 KB 全部是**新功能自己的代码**（AOD 记录推导、AOD 预览绘制、多壁纸、第二页 UI），
不是 stdlib 的账 —— 每次发版都复查一遍：dex 里 `Lkotlin/*` 的出现次数**仍然是 0**。

## 安装

下载 [watchface-tool-android-v2.0.0.apk](../../releases/latest/download/watchface-tool-android-v2.0.0.apk)。

- 系统要求：**Android 7.0+**（minSdk 24 / targetSdk 34）
- 安装时系统可能提示「未知来源应用」，需在设置里允许
- 包名 `face.tool`，launcher 名「表盘制作」，APK 内版本 `2.0`（versionCode 200）

## 使用

顶部是两个页签，底部「生成 .face」固定贴底。

### 页签 ① 动态壁纸

| 位置 | 控件 | 说明 |
|---|---|---|
| 1 | **选择视频 / 图片** | 系统文件选择器；视频、GIF、图片都可以 |
| 2 | **裁剪区** | 拖动移动 · 拖右下角缩放 · 双指捏合缩放 |
| 3 | 重置裁剪框 / 铺满画面 | 下方两个按钮 |
| 4 | **多壁纸** | 「＋ 添加一张壁纸」，最多 8 张；列表里每张可单独删除 |
| 5 | **压缩程度** | 6 档：高画质 RGB / 均衡 P256 / 小体积 P128 / 极限 P64 / 极小 P32 / 微缩 P16 |
| 6 | **帧率** | 7 档：6 / 8 / 12 / 16 / 20 / 24 / 30 FPS |
| 7 | **编码格式** | PNG（无损）/ JPEG（有损·更小） |
| 8 | **每张帧数上限** | 7 档：32 / 48 / 64 / 96 / 128 / 192 / 240 帧（**按每张壁纸算**） |
| 9 | **JPEG 质量** | 5 档：q90 / q85 / q80 / q70 / q60（**仅当选了 JPEG 时可点**，选 PNG 时置灰） |
| 10 | **起始 / 时长** | 单位秒；时长留空 = 取到结尾 |
| 11 | **保持帧率、压缩时长（快放）** | 见下 |
| 12 | **预估行** | 「N 张 / 共 N 帧 · 约 X MB（含固定开销 431KB）」 |

> 第 4 项加的额外壁纸**沿用同一套帧率 / 压缩 / 时长参数**，裁切固定用「全高居中」——
> 一张张单独配参数会让这个页面长到没法用。

### 页签 ② 功能自定义

| 位置 | 控件 | 说明 |
|---|---|---|
| 1 | **主屏 · 时间 / 日期** | 各自可开关；对齐位置 9 种（左上…右下）、X/Y 偏移、字号、颜色、格式 |
| 2 | **点击表盘** | 短按行为：无 / 切换壁纸 / 显隐时间日期 / 暂停动画 |
| 3 | **息屏显示（AOD）** | 开关；底图（无 / 纯黑 / 自定义图片）；显示内容（不显示 / 时间 / 时间+日期）；时间行与日期行的 Y；颜色 |
| 4 | **AOD 预览 + 预估** | 按当前配置实时画出息屏画面，并给出「约 N KB」 |
| 5 | **生成 .face** | 产物存到 `Android/data/face.tool/files/faces/` |

**关于 AOD**：不做 AOD 的话，**息屏时手环会停在动画的最后一帧**（真机实测），
所以想省电就得开。AOD 屏**不能跑 Lua**，时间和日期走系统数据源控件，
因此 AOD 上的字体是系统字体的粗体，与 Windows 版的 Arial Bold 有细微差别。

**关于「跳转系统 App」**：**做不到，本工具不提供。** 实测在 `DeviceType=466`（手环 10/11）下
编译器完全忽略 `btn[...]` 控件名语义，Lua 侧也没有对外跳转的 API。详见[根 README](../README.md)。

界面结构：两个页签各是一个 `ScrollView`，
**「生成」按钮那一行在 `ScrollView` 外面**固定贴底 —— 这样它在任何屏幕尺寸/字号下
都不会被挤出屏幕。详见下方[界面实现](#界面实现)。

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
- Kotlin 命令行编译器 —— 跑一次 `bash fetch_kotlinc.sh` 自动拉（约 62 MB）
- Python 或 `zip` 命令（用于把 `classes.dex` 塞进 APK）

**构建：**

```bash
cd watchface-android
bash fetch_kotlinc.sh          # 首次执行一次；装在 ./.kotlinc/（已 gitignore）
bash build.sh
```

产物：`watchface-tool.apk`

脚本会自动探测 SDK / build-tools / JDK / r8，也可以用环境变量覆盖：

```bash
ANDROID_SDK_ROOT=/path/to/sdk JAVA_HOME=/path/to/jdk \
KOTLINC_DIR=/path/to/kotlin-jars bash build.sh
```

| 环境变量 | 作用 |
|---|---|
| `ANDROID_SDK_ROOT` / `ANDROID_HOME` | Android SDK 根目录 |
| `JAVA_HOME` | JDK 根目录 |
| `KOTLINC_DIR` | Kotlin CLI 的 jar 目录（默认 `./.kotlinc`） |
| `NOR8=1` | 跳过 R8 压缩。构建从约 50 s 降到约 10 s，但 APK 变成 2.1 MB |

### 构建链说明

```
aapt2 link     →  生成带资源索引的 base.apk
javac          →  编译 Java 部分（--release 8）
kotlinc        →  编译 Kotlin 界面层（-jvm-target 17，输出到同一个 classes 目录）
R8             →  tree-shake + 混淆，把 kotlin-stdlib 整棵摇掉 → classes.dex
（追加）       →  把 classes.dex 塞进 base.apk
zipalign       →  4 字节对齐
apksigner      →  签名（首次会自动生成 debug.keystore）
```

R8 用的是 **Android SDK 自带**的 `cmdline-tools/*/lib/r8.jar`，不需要额外下载。
保留规则只有两条（见 `r8-rules.pro`）：`MainActivity` 和 `CropView`
——manifest 是按字符串引用它们的，R8 看不见引用关系，不 keep 会把入口一起删掉。
这个项目没有反射、没有 XML 布局，所以不需要保留别的东西。

### 四个必踩的坑

**1. `d8.bat` / `apksigner.bat` / R8 靠 `JAVA_HOME` 定位 JDK，不看 PATH。**

它们自己要用 JVM 运行。如果 PATH 里的 `java` 是 Java 8，会报：

```
UnsupportedClassVersionError: class file version 55.0, this version only recognizes up to 52.0
```

脚本里已强制 `export JAVA_HOME=<JDK 17+>`。

**2. `javac` 必须用 `--release 8`，不是 `-source 8 -target 8`。**

`--release` 会同时约束 API 签名；只用 `-source/-target` 会出现
「编译通过、装到手机上 `NoSuchMethodError`」这类问题。

**3. Git Bash 下 classpath 用 `;` 拼接时不做事路径转换。**

`/c/Users/...` 这种形式 Java 认不出来，症状是

```
错误: 找不到或无法加载主类 org.jetbrains.kotlin.cli.jvm.K2JVMCompiler
```

看起来像 jar 损坏，其实只是路径没转。单个路径时 Git Bash 会自动转换，
**只有拼接时才暴露**，所以这个坑很容易踩。脚本里一律先 `cygpath -w`。

**4. `-no-stdlib` 不等于「不需要 stdlib」。**

它只关掉「自动去 kotlin-home 找 stdlib 加进编译 classpath」。
你还得把 `kotlin-stdlib.jar` 自己写进 `-classpath`，否则每个内建类型都报

```
error: cannot access built-in declaration 'kotlin.String'
```

同理 d8 / R8 也必须显式带上 `kotlin-stdlib.jar`，否则运行时
`NoClassDefFoundError: kotlin/jvm/internal/Intrinsics`。

## 目录结构

```
watchface-android/
├── build.sh                    无 Gradle 构建脚本（javac + kotlinc + R8）
├── fetch_kotlinc.sh            拉一套最小 Kotlin CLI（约 62 MB → ./.kotlinc/）
├── r8-rules.pro                R8 保留规则
├── app/
│   ├── AndroidManifest.xml
│   └── src/face/tool/
│       ├── MainActivity.kt     主界面（两页签）与参数编排（Kotlin）
│       ├── CropView.kt         裁剪控件（拖动/角点缩放/双指缩放，Kotlin）
│       ├── AodPreviewView.kt   息屏画面预览（自绘 View，Kotlin）
│       ├── AodRenderer.java    把 AOD 布局画成位图（Canvas / Typeface）
│       └── FaceGenerator.java  抽帧 → 裁切 → 量化 → 编码 → 拼装（Java）
├── core/face/                  零 Android 依赖的核心算法
│   ├── FaceBuilder.java        拼装 .face 字节流（含 AOD 描述块与素材区）
│   ├── Quantizer.java          调色板量化（中位切分 + Floyd-Steinberg 抖动）
│   ├── PngEncoder.java         PNG 编码（含调色板写入）
│   ├── AodGen.java             AOD 纯逻辑：布局规划 / 描述记录推导 / 体积预估
│   └── LuaGen.java             生成 main.lua
└── test/face/                  核心算法自测（纯 JavaSE，可直接 java 运行）
```

`core/` 下的类不 import 任何 `android.*`，可以单独抽出来复用。
AOD 刻意拆成两半：**`AodGen` 纯逻辑、`AodRenderer` 才碰 Canvas** ——
这样"布局算得对不对"能在桌面 JVM 上和 PC 端 Python 参考实现逐字段对拍，不用装安卓。

## 界面实现

界面是**纯代码构建**的（`MainActivity.buildUi()`），没有 layout XML ——
为了少一层资源编译依赖，构建链更简单。

模块结构：

```
root(LinearLayout, VERTICAL)
├── 页签条                                  dp(42)，两个按钮
├── pages(LinearLayout, height=0, weight=1)  ← 富余高度在这一层
│   ├── ScrollView#1  (基本壁纸页)            ← 同时只 VISIBLE 一个
│   └── ScrollView#2  (功能自定义页)              GONE 的那个不占高度
└── 生成按钮 + 进度条 + 状态                  固定贴底
```

这样做的目的是**让「生成」按钮在任何屏幕尺寸和字号下都点得到** —— 它自始至终在
两个 `ScrollView` 外面。

四个关键点，改布局时别弄丢：

1. **「生成」按钮必须在 `ScrollView` 外面。** 早先所有控件竖着塞进一个
   `LinearLayout`，参数一多按钮就被顶出屏幕外，小屏必现。
2. **页签切换用 `GONE`，不要用 `INVISIBLE`。** `LinearLayout` 测量时**跳过 `GONE` 的子 View**，
   所以「两页各带 `weight=1`、同时只显示一个」是成立的：可见那页独占全部富余高度。
   换成 `INVISIBLE` 就变成两页各分一半，两页都会莫名出现滚动条。
   （不需要 ViewPager —— 页签条 + 两个 `ScrollView` 零依赖、零第三方库，R8 之后一个类都不多。）
3. **裁剪预览与 AOD 预览用「基准高 + `weight=1`」**（分别 `dp(120)` / `dp(220)` + 权重）。
   屏幕放得下时它把富余高度全部吃掉，参数按自然高度排下来，中间不留空档；
   放不下时退到基准高，整页滚动。配合 `ScrollView.isFillViewport = true`
   —— LinearLayout 第二趟测量才会拿到精确高度，`weight` 才生效。

   > 实测提醒：功能自定义页内容高约 1396 dp，而 1080×2400@2.75 的滚动区只有 636 dp，
   > **这类设置页永远拿不到富余** —— weight 在这里是"防呆护栏"（矮屏/横屏不塌），
   > 不是填充器。想让页变短只能减行数。
4. **两栏参数的 `LayoutParams` 高度必须是 `WRAP_CONTENT`。** 里面是
   「小标题 + 控件」两层，写死高度会把两层压扁，参数挤成一团 —— 这个坑踩过一次。

`CropView` 在 `ACTION_DOWN` 时调了 `requestDisallowInterceptTouchEvent(true)`，
保证在 `ScrollView` 里拖裁剪框不会被父容器把手势截走。

主题固定用系统的 `@android:style/Theme.Material.Light.NoActionBar`（浅色），
**不跟随系统深色模式**。裁剪框的背景色是硬编码的 `0xFF282828`。
