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
    5. 有几个屏（有 AOD 息屏子工程时是 2）

仅依赖标准库，不需要装任何东西。
"""
import os
import re
import struct
import sys

MAGIC = b"\x5a\xa5\x34\x12"
INDEX_START = 272          # 无 AOD 时
INDEX_START_AOD = 360      # 有 AOD 子工程时，元数据区 +88 字节


def _le24(b, off):
    return b[off] | (b[off + 1] << 8) | (b[off + 2] << 16)


def _table_ok(d, s, n):
    """判断 [s, s+n*16) 是不是一张合法的索引表。

    用格式本身的硬约束，不猜偏移常量：
      - 第 i 条的 index 必须等于 i，标记必须是 0x0500
      - 每条的 size 必须等于 20 + 文件名长 + 数据大小
      - 文件项偏移必须单调不减，且文件名是可打印 ASCII
    这些条件同时成立的概率极低，撞不出误判。
    """
    if n <= 0 or s + (n + 1) * 16 > len(d):
        return False
    prev_end = None
    for i in range(n):
        b = s + i * 16
        idx, tag, _r, off, size = struct.unpack_from("<HHIII", d, b)
        if idx != i or tag != 0x0500 or off + 20 > len(d):
            return False
        nlen = d[off + 3]
        if nlen == 0 or nlen > 120 or off + 20 + nlen > len(d):
            return False
        name = d[off + 20:off + 20 + nlen]
        if not all(32 <= c < 127 for c in name):
            return False
        dsize = _le24(d, off)
        if size != 20 + nlen + dsize or off + size > len(d):
            return False
        if prev_end is not None and off < prev_end:
            return False
        prev_end = off + size + (4 - size % 4) % 4
    return True


def find_index_start(d, n):
    """定位索引表起点。

    没有 AOD 时是 272；带 AOD 息屏子工程时元数据区变长，索引表被推到 360，
    而且索引表和文件数据之间还会多一段 AOD 屏的控件描述
    （所以「首条 off == 起点 + (N+1)*16」这个判据在 AOD 产物上是**不成立**的，
    早先版本照抄它去校验会误报「索引 size 不符」，别再用）。
    """
    for s in (INDEX_START, INDEX_START_AOD):
        if _table_ok(d, s, n):
            return s
    for s in range(240, 720, 4):
        if _table_ok(d, s, n):
            return s
    return None


def parse(path):
    with open(path, "rb") as f:
        d = f.read()

    print(f"── {path}")
    print(f"   大小 {len(d):,} B ({len(d) / 1048576:.2f} MB)")

    if d[0:4] != MAGIC:
        print(f"   ✗ magic 错误：期望 {MAGIC.hex(' ')}，实际 {d[0:4].hex(' ')}")
        return False

    # 文件数是 **u32**（元数据槽 11）。早先按单字节 d[216] 读，
    # 单壁纸 96 帧以内看不出问题，多壁纸一超 255 个文件就会数错。
    n = struct.unpack_from("<I", d, 216)[0]
    face_id = d[40:50].rstrip(b"\x00").decode("ascii", "replace")
    title = d[104:120].rstrip(b"\x00").decode("ascii", "replace")
    data_end_hdr = struct.unpack_from("<I", d, 32)[0]
    screens = struct.unpack_from("<I", d, 28)[0] & 0xFFFF

    index_start = find_index_start(d, n)
    ok = True
    if index_start is None:
        print(f"   ✗ 找不到索引表（N={n}）")
        return False

    print(f"   magic ✓   文件数 N={n}   表盘 ID={face_id!r}   Title={title!r}")
    print(f"   屏数 {screens}" + ("（含 AOD 息屏屏）" if screens > 1 else "")
          + f"   索引表起点 {index_start}"
          + ("（已因 AOD 后移 88 字节）" if index_start != INDEX_START else ""))

    # 索引表
    entries = []
    for i in range(n):
        base = index_start + i * 16
        idx, tag, _res, off, size = struct.unpack_from("<HHIII", d, base)
        entries.append((idx, tag, off, size))

    # 索引表与文件数据之间的「描述块」。
    #
    # 老格式（无 AOD）这里只有 1 条：哨兵（index 重复最后一条，off=size=0）。
    # 带 AOD 时这块会长出多组同长记录，末尾才是哨兵。实测分类（tag 字段）：
    #
    #   0x0000  AOD 控件描述（每条 16 B，条数 = AOD 屏的控件数）
    #   0x0200  预览位图   （一条一个屏；size = 该位图字节数）
    #   0x0300  位图数组   （AOD 的数字位图；size = 图宽×图高×4×张数 ≈ 实测值）
    #   0x0700  小件（冒号这类）
    #   0x0500  哨兵（最后一条，off=size=0）
    #
    # ⚠ 不要再用「首条 off == 起点 + (N+1)*16」当判据 —— 带 AOD 时不成立。
    desc_start = index_start + n * 16
    desc_end = entries[0][2] if entries else desc_start
    kinds = {}
    aod_bitmap_bytes = 0
    pos = desc_start
    while pos + 16 <= desc_end:
        _i, tag, _r, off, size = struct.unpack_from("<HHIII", d, pos)
        kinds[tag] = kinds.get(tag, 0) + 1
        if tag == 0x0300:
            aod_bitmap_bytes += size
        pos += 16
    DESC_NAMES = {0x0500: "哨兵", 0x0000: "AOD 控件", 0x0200: "预览位图",
                  0x0300: "位图数组", 0x0700: "小件"}

    # 描述块紧跟在索引表之后，起点 = index_start + n*16（**不是** (n+1)*16 ——
    # 索引表只有 n 条）。无 AOD 时描述块恰好只有 1 条哨兵 16 B；
    # 带 AOD 时是多条控件/位图记录 + 末尾哨兵，所以首个文件项偏移只会更靠后。
    desc_min = index_start + n * 16 + 16
    if entries and entries[0][2] < desc_min:
        print(f"   ✗ 首个文件项偏移 {entries[0][2]} < 描述块最小结束 {desc_min}")
        ok = False
    elif entries and screens <= 1 and entries[0][2] != desc_min:
        print(f"   ✗ 无 AOD 时首个文件项偏移应为 {desc_min}，实际 {entries[0][2]}")
        ok = False
    if kinds:
        parts = [f"{DESC_NAMES.get(k, hex(k))}×{v}" for k, v in sorted(kinds.items())]
        print(f"   描述块 {desc_end - desc_start} B：" + " · ".join(parts))
        if aod_bitmap_bytes:
            print(f"   AOD 数字位图合计 {aod_bitmap_bytes:,} B "
                  f"({aod_bitmap_bytes / 1024:.0f} KB)")
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

        if off + 20 > len(d) or off + 20 + size > len(d) + 4:
            print(f"   ✗ 索引 {idx} 的文件项偏移 {off} 越界")
            ok = False
            continue

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

    # 尾部（含 AOD 素材 —— AOD 的图片不进索引表，直接躺在数据区之后）
    tail = len(d) - prev_end if prev_end is not None else 0
    if tail > 0:
        bitmap_bytes = 440960            # 212x520 RGBA8888 的固定开销
        n_bmp = tail // bitmap_bytes
        print(f"   尾部/未索引区 {tail:,} B ({tail / 1024:.1f} KB)"
              f"   约合 {n_bmp} 张全屏位图 (212x520 RGBA)")
        if screens > 1:
            print("   （AOD 的素材不打进索引表，就在这一段里 —— 这是正常的，别当损坏）")

    # 帧格式 vs lua 引用
    # 新版 lua 把扩展名抽成了 `local EXT = "png"`，不再是字面量 `.png`，
    # 所以两种写法都要认；认不出来才报错。
    if frames and lua_txt:
        exts = {nm.rsplit(".", 1)[-1] for nm, _ in frames}
        m = re.search(r'EXT\s*=\s*"([A-Za-z0-9]+)"', lua_txt)
        if not m:
            m = re.search(r"(\w+)\.(png|jpg|jpeg)\b", lua_txt)
            declared = {m.group(2)} if m else set()
        else:
            declared = {m.group(1)}
        missing = [e for e in exts if e not in declared]
        if not declared:
            print(f"   ⚠ 没能从 main.lua 里认出扩展名声明，跳过一致性检查"
                  f"（帧文件是 .{'/'.join(sorted(exts))}）")
        elif missing:
            print(f"   ✗ {len(frames)} 个帧文件是 .{'/'.join(sorted(exts))}，"
                  f"但 main.lua 里声明的是 .{'/'.join(sorted(declared))} → 手环会黑屏")
            ok = False
        else:
            print(f"   帧 {len(frames)} 个 · .{sorted(declared)[0]} · lua 引用一致 ✓")
            sizes = [s for _, s in frames]
            print(f"   帧数据合计 {sum(sizes):,} B "
                  f"(平均 {sum(sizes) // len(sizes):,} B/帧)")

    # 壁纸分组（face_01 / w2_01 …）
    if frames:
        groups = {}
        for nm, _ in frames:
            stem = nm.rsplit(".", 1)[0]
            key = stem.rsplit("_", 1)[0]
            groups[key] = groups.get(key, 0) + 1
        if len(groups) > 1:
            print("   壁纸分组：" + " · ".join(f"{k}×{v}" for k, v in sorted(groups.items())))

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
        if "ScreenStateChangedCB" in lua_txt:
            print("   省电钩子 ScreenStateChangedCB ✓（息屏时会停动画）")
        else:
            print("   ⚠ main.lua 里没有 ScreenStateChangedCB —— 进 AOD 时动画可能继续跑")

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
