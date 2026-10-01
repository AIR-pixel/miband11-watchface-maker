# -*- coding: utf-8 -*-
"""纯代码生成 .face（不依赖 Compiler.exe）。

⚠️ **这个模块目前没有调用方，而且只支持无 AOD 的产物。**
Windows 端的打包一律走 `build.py`（调 Compiler.exe），所以真正在跑的是它。
这里是 v1.x「摆脱 Compiler.exe」路线的原形，留着当参考；
带 AOD 的纯代码打包在安卓端（`core/face/FaceBuilder.java`），
而仓库里那份**跨语言差分回归**的 Python 参考实现在 `tools/diff/reference.py`。
改这个文件不会影响任何产物 —— 别把它当成生产路径。

.face 二进制格式已完整逆向，逐字节布局见 docs/face格式规范.md。
此模块把「标题 + ID + 文件列表（PNG/Lua 明文） + 预览位图」按该格式拼装成字节流。

意义：PC 端与安卓端都能直接生成 .face，彻底摆脱 Compiler.exe 的 x86 与
再分发限制。小端序。
"""
import struct

MAGIC = b"\x5a\xa5\x34\x12"
PREVIEW_W = 212
PREVIEW_H = 520

# 文件头 / 元数据区里不变的常量
HDR_FIXED_0x10 = 0x800          # 头部 [16-19]，两个样本均为此值
ID_LEN = 10
TITLE_LEN = 16                  # Title 字段固定 16 字节（[104-119]，null 结尾）
INDEX_ENTRY_SIZE = 16
INDEX_START = 272


def _title_bytes(title):
    return title.encode("ascii", "replace").ljust(TITLE_LEN, b"\x00")[:TITLE_LEN]


def _id_bytes(face_id):
    return str(face_id).encode("ascii").ljust(ID_LEN, b"\x00")[:ID_LEN]


def build_face(title, face_id, files, preview_rgba, preview_w=PREVIEW_W, preview_h=PREVIEW_H):
    """拼装 .face 字节流。

    files: [(name: str, data: bytes), ...]，name 形如 "lua/face_01.png"、"lua/main.lua"。
    preview_rgba: 预览位图 RGBA8888 字节，长度须 == preview_w * preview_h * 4。
    """
    n = len(files)
    idx_table_end = INDEX_START + (n + 1) * INDEX_ENTRY_SIZE   # 索引表(含哨兵)结束 = 数据区起始

    # 计算每个文件项偏移与大小（文件项 = 20B desc + 文件名 + 数据，随后 4 字节对齐 padding）
    entries = []
    cur = idx_table_end
    for name, data in files:
        nb = name.encode("ascii")
        size = 20 + len(nb) + len(data)          # 索引表 size 不含 padding
        pad = (4 - size % 4) % 4                  # 4 字节对齐
        entries.append((nb, data, cur, size))
        cur += size + pad
    data_end = cur

    out = bytearray()

    # ---- 文件头 64B ----
    out += MAGIC                              # [0-3]
    out += b"\x00" + bytes([ID_LEN])          # [4]=0, [5]=ID 长度（与 set_face_id 一致）
    out += b"\x00" * 10                       # [6-15]
    out += struct.pack("<I", HDR_FIXED_0x10)  # [16-19]
    out += b"\x00" * 8                        # [20-27]
    out += struct.pack("<I", 1)               # [28-31]
    out += struct.pack("<I", data_end)        # [32-35]
    out += b"\x00" * 4                        # [36-39]
    out += _id_bytes(face_id)                 # [40-49]
    out += b"\x00" * 14                       # [50-63]

    # ---- Title 区 [64-119] ----
    out += b"\x00" * 40                       # [64-103]
    out += _title_bytes(title)                # [104-119] 16 字节
    out += b"\x00" * 52                       # [120-171]
    idx_end = INDEX_START + n * INDEX_ENTRY_SIZE  # 有效索引表结束（不含哨兵）
    out += struct.pack("<I", data_end)        # [172]
    out += struct.pack("<I", 1)               # [176]
    out += struct.pack("<I", 256)             # [180]
    out += struct.pack("<I", 0)               # [184]
    out += struct.pack("<I", INDEX_START)     # [188]
    out += struct.pack("<I", 0)               # [192]
    out += struct.pack("<I", INDEX_START)     # [196]
    out += struct.pack("<I", 0)               # [200]
    out += struct.pack("<I", INDEX_START)     # [204]
    out += struct.pack("<I", 0)               # [208]
    out += struct.pack("<I", INDEX_START)     # [212]
    out += struct.pack("<I", n)               # [216] 文件数
    out += struct.pack("<I", INDEX_START)     # [220]
    out += struct.pack("<I", 0)               # [224]
    out += struct.pack("<I", idx_end)         # [228]
    out += struct.pack("<I", 0)               # [232]
    out += struct.pack("<I", idx_end)         # [236]
    out += struct.pack("<I", 0)               # [240]
    out += struct.pack("<I", idx_end)         # [244]
    out += struct.pack("<I", 0)               # [248]
    out += struct.pack("<I", idx_end)         # [252]
    out += struct.pack("<I", 0)               # [256]
    out += struct.pack("<I", 0)               # [260]
    out += struct.pack("<I", idx_end)         # [264]
    out += struct.pack("<I", INDEX_ENTRY_SIZE)  # [268]

    # ---- 索引表 (n + 1 条，含哨兵) ----
    for i, (nb, data, offset, size) in enumerate(entries):
        out += struct.pack("<H", i)
        out += struct.pack("<H", 0x0500)
        out += struct.pack("<I", 0)
        out += struct.pack("<I", offset)
        out += struct.pack("<I", size)
    # 哨兵：index 重复最后一条，offset/size = 0
    out += struct.pack("<H", n - 1)
    out += struct.pack("<H", 0x0500)
    out += struct.pack("<I", 0)
    out += struct.pack("<I", 0)
    out += struct.pack("<I", 0)

    # ---- 文件数据区 ----
    for nb, data, offset, size in entries:
        out += (len(data) & 0xFFFFFF).to_bytes(3, "little")  # 数据大小 3B
        out += bytes([len(nb)])                               # 文件名长度 1B
        out += b"\x00" * 16                                   # 16B 零
        out += nb                                             # 文件名
        out += data                                           # 数据
        out += b"\x00" * ((4 - size % 4) % 4)                 # 4 字节对齐 padding

    # ---- 尾部位图（表盘预览图，RGBA8888） ----
    out += b"\x00" * 4
    out += struct.pack("<H", preview_w)
    out += struct.pack("<H", preview_h)
    out += struct.pack("<I", len(preview_rgba))
    out += preview_rgba

    return bytes(out)
