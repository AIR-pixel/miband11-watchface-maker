#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨语言差分回归：同一份用例，Python 实现 ↔ JVM 实现，逐字节比对。

**为什么需要这个**：同一个算法有两份实现（`watchface-tool/*.py` 与
`watchface-android/core/face/*.java`）时，「我是逐行照抄的」什么都不能证明。
本项目就是这么栽的 —— 三个 bug（尾部对齐只做了一半、偏移量语义相对/绝对搞混、
只测了一种样本导致三个分支从没被执行过）都是这个回归抓出来的。
详见 `docs/项目经验.md` 的 Bug 4/5/6 与 §5。

三个阶段（缺一不可）：

| 阶段 | 比什么 | Python 侧 | JVM 侧 |
|---|---|---|---|
| `lua` | 生成的 `main.lua` 全文 | `watchface_tool/lua.py`（生产） | `LuaGen.java` |
| `aod` | AOD 控件表 + 描述块全部记录 | `aod.py` 真跑 build_aod 回读 fprj + 参考记录实现 | `AodGen.java` |
| `asm` | **整份 `.face` 的每一个字节** | `tools/diff/reference.py` 的参考 packer | `FaceBuilder.java` |

用法：

    python tools/diff_face.py                 # 跑全部
    python tools/diff_face.py --stage asm     # 只跑某一个（可逗号分隔）
    python tools/diff_face.py --keep          # 保留中间产物，失败时好排查

前提：JDK（`javac`/`java`，认 `JAVA_HOME`）· Pillow（AOD 阶段要跑生产代码）。

**这个回归覆盖不到什么**：`.face` 与**官方 `Compiler.exe`** 的一致性。
那需要 Compiler.exe 本体（本项目因授权不分发）与用它产出的参考样本，
所以「与编译器逐字节一致」这条结论无法只靠本仓库重跑 —— 见 `docs/项目经验.md` §5。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DIFF = os.path.join(HERE, "diff")
JVM_SRC = os.path.join(REPO, "watchface-android", "core", "face")
JVM_DRV = os.path.join(DIFF, "jvm")

STAGES = ("lua", "aod", "asm")


# ------------------------------------------------------------------ 基础设施

def which_jdk():
    """定位 JDK。

    坑：`java` 与 `javac` 可能来自**两个不同的 JDK** —— 本机 PATH 里 `javac` 是
    JDK 21，而 `java` 是 `Common Files\\Oracle\\Java\\java8path` 那个 Java 8 垫片，
    于是 javac 编出来的 class（65.0）被 java 8（只认到 52.0）拒绝。
    所以优先取**与 javac 同目录**的 java，而不是 PATH 上先撞到的那个。
    """
    def pair(bin_dir):
        jc = None
        for exe in ("javac.exe", "javac"):
            p = os.path.join(bin_dir, exe)
            if os.path.isfile(p):
                jc = p
                break
        if not jc:
            return None
        for exe in ("java.exe", "java"):
            p = os.path.join(bin_dir, exe)
            if os.path.isfile(p):
                return jc, p
        return jc, shutil.which("java")

    for key in ("JAVA_HOME", "JDK_HOME"):
        home = os.environ.get(key)
        if home:
            got = pair(os.path.join(home, "bin"))
            if got:
                return got
    jc = shutil.which("javac")
    if jc:
        return pair(os.path.dirname(jc))
    return None, None


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", **kw)
    if p.returncode != 0:
        sys.exit("[X] 命令失败 %s\n%s%s" % (" ".join(cmd), p.stdout, p.stderr))
    return p.stdout


def compile_jvm(javac, classes):
    srcs = sorted(os.path.join(JVM_SRC, f) for f in os.listdir(JVM_SRC) if f.endswith(".java"))
    srcs += sorted(os.path.join(JVM_DRV, f) for f in os.listdir(JVM_DRV) if f.endswith(".java"))
    os.makedirs(classes, exist_ok=True)
    run([javac, "-encoding", "UTF-8", "-d", classes] + srcs)


def diff_report(want, got, label_w, label_g):
    """返回首个差异的描述（相同则 None）。"""
    if want == got:
        return None
    lim = min(len(want), len(got))
    first = next((i for i in range(lim) if want[i] != got[i]), lim)
    cnt = sum(1 for i in range(lim) if want[i] != got[i])
    out = ["  首个差异 @%d（共 %d B 不同；%s %d B / %s %d B）"
           % (first, cnt, label_w, len(want), label_g, len(got))]
    base = max(0, (first // 16) * 16 - 16)
    for off in range(base, min(base + 80, max(len(want), len(got))), 16):
        a = want[off:off + 16]
        b = got[off:off + 16]
        mark = "" if a == b else "  <<<"
        out.append("   %06X  %-47s %-47s%s"
                   % (off, " ".join("%02X" % x for x in a), " ".join("%02X" % x for x in b), mark))
    return "\n".join(out)


# ------------------------------------------------------------------ 三个阶段

def stage_lua(java, classes, work):
    from diff import reference                                    # noqa: PLC0415
    sys.path.insert(0, os.path.join(REPO, "watchface-tool"))
    from watchface_tool.lua import generate_lua                   # noqa: PLC0415

    cases = reference.load_lua_cases(os.path.join(DIFF, "lua_cases.txt"))
    py_dir, jv_dir = os.path.join(work, "py", "lua"), os.path.join(work, "jvm", "lua")
    os.makedirs(py_dir, exist_ok=True)

    print("== 阶段 lua：生成的 main.lua 全文 ==")
    for c in cases:
        kw = dict(c)
        name = kw.pop("name")
        src = generate_lua(**kw)
        with open(os.path.join(py_dir, name + ".lua"), "wb") as f:
            f.write(src.encode("utf-8"))

    run([java, "-cp", classes, "DiffMain", "lua",
         os.path.join(DIFF, "lua_cases.txt"), jv_dir])

    ok = 0
    for c in cases:
        a = open(os.path.join(py_dir, c["name"] + ".lua"), "rb").read()
        b = open(os.path.join(jv_dir, c["name"] + ".lua"), "rb").read()
        d = diff_report(a, b, "py", "java")
        if d is None:
            ok += 1
            print("  %-26s %6d B  一致 ✓" % (c["name"], len(a)))
        else:
            print("  %-26s 不一致 ✗" % c["name"])
            print(d)
    return ok, len(cases)


def stage_aod(java, classes, work):
    from diff import reference                                    # noqa: PLC0415
    sys.path.insert(0, os.path.join(REPO, "watchface-tool"))
    from watchface_tool import aod as aod_mod                     # noqa: PLC0415

    cases = reference.load_aod_cases(os.path.join(DIFF, "aod_cases.txt"))
    py_dir, jv_dir = os.path.join(work, "py", "aod"), os.path.join(work, "jvm", "aod")
    os.makedirs(py_dir, exist_ok=True)

    print("== 阶段 aod：控件表 + 描述块记录 ==")
    for c in cases:
        wd = os.path.join(work, "aodwork", c["name"])
        shutil.rmtree(wd, ignore_errors=True)
        os.makedirs(wd, exist_ok=True)
        ws = reference.python_widgets_for(c, wd, aod_mod)
        text = "" if ws is None else reference.canon(
            ws, reference.records_from_spec(reference.zero_images(ws), ws))
        with open(os.path.join(py_dir, c["name"] + ".txt"), "w", encoding="utf-8") as f:
            f.write(text)

    run([java, "-cp", classes, "DiffMain", "aod",
         os.path.join(DIFF, "aod_cases.txt"), jv_dir])

    ok = 0
    for c in cases:
        a = open(os.path.join(py_dir, c["name"] + ".txt"), encoding="utf-8").read()
        b = open(os.path.join(jv_dir, c["name"] + ".txt"), encoding="utf-8").read()
        d = diff_report(a.encode(), b.encode(), "py", "java")
        n_rec = a.count("\nR|")
        if d is None:
            ok += 1
            print("  %-20s %2d 控件 %2d 记录 %7d B  一致 ✓"
                  % (c["name"], a.count("\nW|"), n_rec, len(a.encode())))
        else:
            print("  %-20s 不一致 ✗" % c["name"])
            print(d)
    return ok, len(cases)


def stage_asm(java, classes, work):
    from diff import reference                                    # noqa: PLC0415
    sys.path.insert(0, os.path.join(REPO, "watchface-tool"))
    from watchface_tool import aod as aod_mod                     # noqa: PLC0415

    cases = reference.load_asm_cases(os.path.join(DIFF, "assemble_cases.txt"))
    aod_cases = {c["name"]: c for c in reference.load_aod_cases(os.path.join(DIFF, "aod_cases.txt"))}
    py_dir, jv_dir = os.path.join(work, "py", "asm"), os.path.join(work, "jvm", "asm")
    os.makedirs(py_dir, exist_ok=True)

    print("== 阶段 asm：整份 .face 逐字节 ==")
    for c in cases:
        files = reference.files_for(c["n_files"], c["extra_last"])
        recs = []
        has_aod = c["has_aod"]
        if has_aod:
            ac = aod_cases[c["aod_case"]]
            wd = os.path.join(work, "aodwork_asm", c["name"])
            shutil.rmtree(wd, ignore_errors=True)
            os.makedirs(wd, exist_ok=True)
            ws = reference.python_widgets_for(ac, wd, aod_mod)
            assert ws is not None, c["name"]
            recs = reference.records_from_spec(reference.zero_images(ws), ws)
        made = reference.pack(files, recs, reference.TITLE, reference.FACE_ID,
                              reference.preview_block(), has_aod)
        with open(os.path.join(py_dir, c["name"] + ".face"), "wb") as f:
            f.write(made)

    run([java, "-cp", classes, "DiffMain", "asm",
         os.path.join(DIFF, "assemble_cases.txt"), jv_dir,
         os.path.join(DIFF, "aod_cases.txt")])

    ok = 0
    for c in cases:
        a = open(os.path.join(py_dir, c["name"] + ".face"), "rb").read()
        b = open(os.path.join(jv_dir, c["name"] + ".face"), "rb").read()
        d = diff_report(a, b, "py", "java")
        if d is None:
            ok += 1
            print("  %-20s %2d 文件 %-5s %9d B  一致 ✓"
                  % (c["name"], c["n_files"], "AOD" if c["has_aod"] else "无AOD", len(a)))
        else:
            print("  %-20s 不一致 ✗" % c["name"])
            print(d)
    return ok, len(cases)


# ------------------------------------------------------------------ 入口

def main():
    ap = argparse.ArgumentParser(description="跨语言差分回归")
    ap.add_argument("--stage", default=",".join(STAGES),
                    help="只跑指定阶段，逗号分隔：%s" % ",".join(STAGES))
    ap.add_argument("--keep", action="store_true", help="保留中间产物目录")
    args = ap.parse_args()

    want = [s.strip() for s in args.stage.split(",") if s.strip()]
    for s in want:
        if s not in STAGES:
            sys.exit("[X] 未知阶段 %r，可选 %s" % (s, "/".join(STAGES)))

    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("[X] 缺 Pillow —— AOD 阶段要跑生产的 watchface_tool/aod.py。\n"
                 "    pip install -r watchface-tool/requirements.txt")

    javac, java = which_jdk()
    if not javac:
        sys.exit("[X] 找不到 javac/java。装 JDK 或设 JAVA_HOME（只需要 JDK，不需要 Android SDK）")

    work = tempfile.mkdtemp(prefix="face_diff_")
    classes = os.path.join(work, "classes")
    try:
        print("编译 JVM 侧：%s + tools/diff/jvm" % os.path.relpath(JVM_SRC, REPO))
        compile_jvm(javac, classes)
        print("  输出 %s\n" % classes)

        total_ok = total = 0
        failed = []
        for stage in want:
            fn = {"lua": stage_lua, "aod": stage_aod, "asm": stage_asm}[stage]
            ok, n = fn(java, classes, work)
            total_ok += ok
            total += n
            if ok != n:
                failed.append(stage)
            print()

        print("=" * 60)
        if failed:
            print("✗ 失败：%s" % "、".join(failed))
        else:
            print("✓ %d/%d 全部逐字节一致（阶段：%s）" % (total_ok, total, "、".join(want)))
        if args.keep:
            print("  中间产物保留在 %s" % work)
        return 0 if not failed else 1
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
