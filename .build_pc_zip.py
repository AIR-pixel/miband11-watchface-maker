# -*- coding: utf-8 -*-
"""打 Windows 源码包 dist/watchface-tool-pc-<ver>.zip。

清单直接取自 `git ls-files -z`（拿原始字节，避开 core.quotepath 对中文名的转义），
只留 Windows 端需要的三块：根目录的 LICENSE / NOTICE / README.md、docs/、tools/、
watchface-tool/。安卓端与 dist/ 本身不入包。

注意：**已发布过的包不要重打。** 目标文件已存在时会拒绝覆盖，除非加 `--force`
—— 否则 `dist/` 里那份是用户已经下载走的字节，悄悄改掉会让 Release 正文里的
SHA256 对不上（发布脚本会把摘要写进正文）。

用法：
    python .build_pc_zip.py              # 用 __init__.py 里的版本号
    python .build_pc_zip.py 2.2.0        # 显式指定
    python .build_pc_zip.py 2.2.0 --force
"""
import os
import subprocess
import sys
import zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(REPO, "dist")
TOP = "miband11-watchface-maker"

KEEP_PREFIX = ("LICENSE", "NOTICE", "README.md",
               "docs/", "tools/", "watchface-tool/")
SKIP = ("__pycache__", "Compiler.exe")


def version():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        return args[0]
    init = os.path.join(REPO, "watchface-tool", "watchface_tool", "__init__.py")
    ns = {}
    with open(init, encoding="utf-8") as f:
        exec(compile(f.read(), init, "exec"), ns)
    return ns["__version__"]


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, check=True).stdout
    paths = [p.decode("utf-8") for p in out.split(b"\0") if p]
    return [p for p in paths
            if p.startswith(KEEP_PREFIX) and not any(s in p for s in SKIP)]


def main():
    ver = version()
    files = tracked()
    if not files:
        sys.exit("[X] git ls-files 没捞到东西，检查 KEEP_PREFIX")
    os.makedirs(DIST, exist_ok=True)
    target = os.path.join(DIST, "watchface-tool-pc-v%s.zip" % ver)
    if os.path.exists(target) and "--force" not in sys.argv:
        sys.exit("[X] %s 已存在（可能已经发布过了）。\n"
                 "    确认要重打就加 --force，但记得同步重跑 .gh_publish.py release，\n"
                 "    否则 Release 正文里的 SHA256 会与实际附件对不上。"
                 % os.path.relpath(target, REPO))

    # 顶层目录项按 v2.1.1 的惯例显式写上，解压后目录树才整齐
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for d in ("", "/docs", "/docs/images", "/tools", "/tools/diff",
                  "/tools/diff/jvm", "/watchface-tool", "/watchface-tool/gui",
                  "/watchface-tool/watchface_tool"):
            z.writestr(zipfile.ZipInfo(TOP + d + "/"), b"")
        for p in sorted(files):
            z.write(os.path.join(REPO, p), TOP + "/" + p)
    print("OK  %s  (%d 文件, %d B)" % (os.path.relpath(target, REPO),
                                       len(files), os.path.getsize(target)))
    for p in sorted(files):
        print("   ", p)


if __name__ == "__main__":
    main()
