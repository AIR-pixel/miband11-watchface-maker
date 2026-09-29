#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`.face` 结构检查器（只读）。

按 docs/face格式规范.md 解析 .face，逐项打印索引表内容，
并做几项一致性检查。用来回答"这个表盘为什么装不上/黑屏"。

用法：
    python verify_face.py <文件.face> [更多文件...]

检查项：
    1. magic 是否正确
    2. 索引表偏移是否与数据区吻合（能查出对齐算错这类问题）
    3. 帧文件扩展名与 main.lua 里引用的是否一致（不一致 = 手环黑屏）
    4. main.lua 的 period，换算成播放帧率与总时长

仅依赖标准库，不需要装任何东西。
"""
import os
import re
import struct
import sys

MAGIC = b"\x5a\xa5\x34\x12"
INDEX_START = 272


def _le24(b, off):
    return b[off] | (b[off + 1] << 8) | (b[off + 2] << 16)


def parse(path):
    with open(path, "rb") as f:
        d = f.read()

    print(f"── {path}")
    print(f"   大小 {len(d):,} B ({len(d) / 1048576:.2f} MB)")

    if d[0:4] != MAGIC:
        print(f"   ✗ magic 错误：期望 {MAGIC.hex(' ')}，实际 {d[0:4].hex(' ')}")
        return False

    n = d[216]
    face_id = d[40:50].rstrip(b"\x00").decode("ascii", "replace")
    title = d[104:120].rstrip(b"\x00").decode("ascii", "replace")
    data_end_hdr = struct.unpack_from("<I", d, 32)[0]

    print(f"   magic ✓   文件数 N={n}   表盘 ID={face_id!r}   Title={title!r}")

    # 索引表
    entries = []
    for i in range(n):
        base = INDEX_START + i * 16
        idx, tag, _res, off, size = struct.unpack_from("<HHIII", d, base)
        entries.append((idx, tag, off, size))

    # 哨兵
    sent_base = INDEX_START + n * 16
    s_idx, s_tag, _s1, s_off, s_size = struct.unpack_from("<HHIII", d, sent_base)

    ok = True
    expect_first = INDEX_START + (n + 1) * 16

    if entries and entries[0][2] != expect_first:
        print(f"   ✗ 首个文件项偏移 {entries[0][2]} ≠ 预期 {expect_first}"
              f"（索引表 {(n + 1)} 条 × 16B）")
        ok = False
    if data_end_hdr == 0:
        print("   ✗ 头部 [32-35] 数据区结束偏移为 0")
        ok = False

    frames = []
    lua_txt = None
    prev_end = None

    for idx, tag, off, size in entries:
        if tag != 0x0500:
            print(f"   ⚠ 索引 {idx} 的标记为 0x{tag:04x}（预期 0x0500）")
            ok = False

        dsize = _le24(d, off)
        nlen = d[off + 3]
        name = d[off + 20:off + 20 + nlen].decode("ascii", "replace")
        payload = d[off + 20 + nlen:off + 20 + nlen + dsize]

        # 索引表的 size 必须等于 20 + 名长 + 数据大小（不含 padding）
        if size != 20 + nlen + dsize:
            print(f"   ✗ {name}: 索引 size={size} ≠ 20+{nlen}+{dsize}"
                  f"={20 + nlen + dsize}")
            ok = False

        # 连续性：上一项的结尾（含 padding 到 4 字节）应等于本项偏移
        if prev_end is not None and off != prev_end:
            print(f"   ✗ {name}: 起始偏移 {off} ≠ 上一项对齐后结尾 {prev_end}")
            ok = False
        prev_end = off + size + (4 - size % 4) % 4

        if name.endswith(".lua"):
            lua_txt = payload.decode("utf-8", "replace")
        else:
            frames.append((name, dsize))

    # 尾部
    tail = len(d) - prev_end if prev_end is not None else 0
    if tail > 0:
        tw = struct.unpack_from("<H", d, prev_end + 4)[0]
        th = struct.unpack_from("<H", d, prev_end + 6)[0]
        tb = struct.unpack_from("<I", d, prev_end + 8)[0]
        print(f"   尾部位图 {tw}×{th}  {tb:,} B ({tb / 1024:.1f} KB)"
              f"   实测尾部 {tail:,} B")
        if tb != tw * th * 4:
            print(f"   ✗ 位图字节数与 宽×高×4 不符")
            ok = False

    # 帧格式 vs lua 引用
    if frames and lua_txt:
        ext = frames[0][0].rsplit(".", 1)[-1]
        if f".{ext}" not in lua_txt:
            print(f"   ✗ {len(frames)} 帧为 .{ext}，但 main.lua 里没有引用 .{ext} "
                  f"→ 手环会黑屏")
            ok = False
        else:
            print(f"   帧 {len(frames)} 个 · .{ext} · lua 引用一致 ✓")
            sizes = [s for _, s in frames]
            print(f"   帧数据合计 {sum(sizes):,} B "
                  f"(平均 {sum(sizes) // len(sizes):,} B/帧)")

    # period
    if lua_txt:
        m = re.search(r"period\s*=\s*(\d+)", lua_txt)
        if m:
            period = int(m.group(1))
            fps = 1000.0 / period if period else 0
            total = len(frames) * period / 1000.0 if period else 0
            print(f"   period = {period} ms  →  播放 {fps:.1f} fps，"
                  f"{len(frames)} 帧共 {total:.2f} s")
        else:
            print("   ⚠ main.lua 里没找到 period")

    print(f"   结论：{'结构正确 ✓' if ok else '存在问题 ✗'}")
    return ok


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    results = []
    for i, p in enumerate(sys.argv[1:]):
        if i:
            print()
        if not os.path.isfile(p):
            print(f"── {p}\n   文件不存在")
            results.append(False)
            continue
        results.append(parse(p))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
