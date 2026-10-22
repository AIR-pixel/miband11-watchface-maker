# -*- coding: utf-8 -*-
"""往返回归：把 .face 拆开再用**纯代码打包器**拼回去，逐字节比对。

    python tools/roundtrip_face.py samples/*.face

这是「纯代码打包器 == Compiler.exe」最直接的证据：输入是编译器真实产物，
输出必须与它完全相同（含全部偏移、padding、元数据槽、哨兵 idx）。

退出码 0 = 全部一致。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "watchface-tool"))

from watchface_tool import facebin  # noqa: E402


def roundtrip(path):
    """返回 (是否一致, 说明)。"""
    data = open(path, "rb").read()
    try:
        f = facebin.unpack_face(data)
    except ValueError as e:
        return False, f"解包失败：{e}"

    out = facebin.pack_face(
        files=f["files"],
        preview_bgra=f["preview_bgra"],
        title=f["title"],
        face_id=f["face_id"],
        recs=f["recs"],
        has_aod=f["has_aod"],
        sentinel_idx=f["sentinel_idx"],
        id_len=f["id_len"],
    )
    if out == data:
        return True, "%d B · %d 文件 · %d 描述记录" % (len(data), f["n"], len(f["recs"]))

    if len(out) != len(data):
        return False, "长度不同：原 %d B / 重拼 %d B（差 %+d）" % (
            len(data), len(out), len(out) - len(data))
    bad = [i for i in range(len(data)) if data[i] != out[i]]
    head = ", ".join("@%d: %02x->%02x" % (i, data[i], out[i]) for i in bad[:6])
    return False, "长度相同但有 %d 字节不同：%s" % (len(bad), head)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    ok = 0
    for path in argv:
        good, msg = roundtrip(path)
        print(("✓ " if good else "✗ ") + os.path.basename(path) + "  " + msg)
        ok += 1 if good else 0
    print("\n%d/%d 逐字节一致" % (ok, len(argv)))
    return 0 if ok == len(argv) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
