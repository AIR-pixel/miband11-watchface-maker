# -*- coding: utf-8 -*-
"""调用 Compiler.exe 打包 .face，并回写表盘 ID。

Compiler.exe 是 EasyFace（m0tral）从官方 Vela IDE 提取的编译器，无开源协议，
本工具不打包它 —— 由用户在设置里指定路径。
"""
import os
import subprocess

from .constants import FACE_ID_OFFSET, FACE_ID_SIZE, FACE_MAGIC


class BuildError(RuntimeError):
    pass


def find_compiler(candidates):
    """在候选路径里找 Compiler.exe。"""
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def build_face(compiler_exe, fprj_path, out_dir, face_name, face_id):
    """运行 Compiler.exe -b，返回产物 .face 的绝对路径。"""
    if not compiler_exe or not os.path.isfile(compiler_exe):
        raise BuildError("未找到 Compiler.exe，请先在设置里指定其路径。")
    os.makedirs(out_dir, exist_ok=True)

    proc = subprocess.run(
        [compiler_exe, "-b", str(fprj_path), str(out_dir), str(face_name), str(face_id)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    face_path = os.path.join(out_dir, face_name)
    if proc.returncode != 0 or not os.path.isfile(face_path):
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        raise BuildError(f"Compiler.exe 打包失败（退出码 {proc.returncode}）:\n{tail}")

    patch_face_id(face_path, face_id)
    return face_path


def patch_face_id(face_path, face_id):
    """在 .face 头部 offset 40 处写入 10 字节 ASCII 表盘 ID（与模板脚本一致）。"""
    face_id = str(face_id)
    if not face_id.isdigit():
        raise BuildError(f"表盘 ID 必须是数字: {face_id}")
    id_bytes = face_id.encode("ascii")
    if len(id_bytes) > FACE_ID_SIZE:
        raise BuildError(f"表盘 ID 过长（最多 {FACE_ID_SIZE} 位）: {face_id}")

    with open(face_path, "rb") as f:
        data = bytearray(f.read())

    if len(data) < FACE_ID_OFFSET + FACE_ID_SIZE:
        raise BuildError("生成的 .face 太小，无法回写 ID。")
    if bytes(data[:4]) != FACE_MAGIC:
        raise BuildError("生成的 .face 头部魔数不符，拒绝回写 ID。")

    data[5] = FACE_ID_SIZE
    for i in range(FACE_ID_SIZE):
        data[FACE_ID_OFFSET + i] = 0
    data[FACE_ID_OFFSET : FACE_ID_OFFSET + len(id_bytes)] = id_bytes

    with open(face_path, "wb") as f:
        f.write(data)
