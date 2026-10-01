# 跨语言差分回归的资料

入口在上一层：`tools/diff_face.py`。这里放的是它用到的**用例表**、**JVM 侧驱动**和
**Python 参考实现**。

```bash
python tools/diff_face.py            # 三个阶段全跑（约 35 s）
python tools/diff_face.py --stage asm --keep
```

前提：JDK（只要 `javac`/`java`，不需要 Android SDK）＋ Pillow。

## 文件

| 文件 | 作用 |
|---|---|
| `../diff_face.py` | 入口：编译 JVM 侧、跑三个阶段、比对、汇总 |
| `lua_cases.txt` | LuaGen 用例，12 例，20 字段 |
| `aod_cases.txt` | AOD 用例，12 例，13 字段 |
| `assemble_cases.txt` | 装配用例，21 例，5 字段 |
| `jvm/DiffMain.java` | JVM 侧驱动（`lua` / `aod` / `asm` 三个模式） |
| `reference.py` | Python 参考侧：用例解析、记录推导、参考 packer |

## 三个阶段各测什么

| 阶段 | 比对对象 | Python 侧 | JVM 侧 | 例数 |
|---|---|---|---|---|
| `lua` | `main.lua` **全文** | `watchface_tool/lua.py`（生产代码） | `LuaGen.java` | 12 |
| `aod` | AOD **控件表 + 描述块全部记录** | 真跑 `aod.build_aod()` 再**回读它写出的 fprj** ＋ 参考记录实现 | `AodGen.java` | 12 |
| `asm` | **整份 `.face` 的每一个字节** | `reference.py` 的参考 packer | `FaceBuilder.java` | 21 |

`aod` 阶段刻意**回读 fprj**，而不是另写一份布局算法 —— 那样测到的才是生产路径。

## 为什么必须「逐字节」而不是「比关键字段」

比 `size` / `offset` 会漏掉对齐、padding、元数据槽数这类「边角 88 字节」的问题，
而恰恰是这些让产物不可用。本回归抓到的三个 bug 都属这一类：

| Bug | 形态 | 只比关键字段能发现吗 |
|---|---|---|
| 4 | 尾部对齐只做了一半 —— 同样的代码，样本 n=8 看着对，n=12 就短 2 字节 | 不会 |
| 5 | `firstRecOff()` 返回的是相对偏移，调用方当绝对用 → 每个样本错得一模一样 | 不会 |
| 6 | 只测了一种样本 → 三个分支**从来没被执行过** | 不会 |

所以 `assemble_cases.txt` 里专门有一组 `*_pad1 / *_pad2 / *_pad3` 用例，
把「文件数据区总长的模 4 余数」走遍 0/1/2/3 —— 那是 Bug 4 的触发条件。

## 素材为什么是「合成的」

用例不读任何真实素材或参考产物：

- 装配用例的主文件由 `nFiles` / `extraLast` 唯一确定（规则写在
  `DiffMain.filesFor()` 与 `reference.files_for()`，两边必须一字不差）；
- AOD 的位图**两边都用零像素**，只要尺寸对上 —— 像素字节的搬运是平凡逻辑，
  真正会出错的是记录的分类、顺序、头部字段与偏移。

好处是它不依赖任何二进制样本，**clone 下来就能跑**。

## 这份回归覆盖不到什么

**与官方 `Compiler.exe` 的一致性。** 那需要 Compiler.exe 本体（本项目因授权不分发，
见仓库 `NOTICE`）以及用它产出的参考产物，所以「与编译器逐字节一致」这条结论
无法只靠本仓库重跑。它当初的做法是把编译器的产物拆成素材、用纯代码重新打包再对拍，
那一步的脚本依赖 Compiler.exe，没有随仓库发布 —— `docs/项目经验.md` §5 有说明。

换句话说：**这个回归能保证两份实现在「同一份输入」下不会各走各的；
不能保证这份输入本身的布局和官方编译器一致。** 后者的证据是实测记录，不是可重跑的脚本。
