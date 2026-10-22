# -*- coding: utf-8 -*-
"""纯代码打包 / 解包 `.face` —— 零第三方依赖，不调用 Compiler.exe。

端口自 `watchface-android/core/face/FaceBuilder.java`（Java 侧与安卓端同源），
布局与坑的完整说明见 `docs/face格式规范.md`。全部小端序，像素一律 BGRA8888
直通（非预乘）alpha。

    布局（无 AOD）
    ┌────────────────────────────────────────────────────┐
    │ [0,172)            头部 + Title                     │
    │ [172,272)          元数据（25 槽）                  │
    │ [272,272+n*16)     索引表（n 条）                   │
    │ [..,+16)           描述块（只剩一条 0x0500 哨兵）   │
    │ [..,filesEnd)      文件数据区（条目起点 4 字节对齐）│
    │ [EOF-440972,EOF)   尾部预览（12 B 头 + 212*520 BGRA）│
    └────────────────────────────────────────────────────┘

    布局（带 AOD）
    ┌────────────────────────────────────────────────────┐
    │ [172,260)          元数据·主屏（22 槽，索引基址 360）│
    │ [260,360)          元数据·AOD 尾部（25 槽）         │
    │ [360,360+n*16)     索引表                           │
    │ [d0,descEnd)       描述块：锚→位图→数组→小件→哨兵   │
    │ [filesEnd,assetsEnd) AOD 素材区（实排：锚→小件→位图→数组）│
    └────────────────────────────────────────────────────┘

⚠️ 两个必须照抄的细节（都是实测踩出来的）：

1. `data[5]` 是 **ID 长度（单字节）**，不是 u16 的一半。Compiler.exe 原生产物写 0，
   旧链路随后靠回写补丁把 ID 与长度改成 10；这里直接写 10，等价（产物与打过补丁的
   编译器产物逐字节相同）。
2. 描述块哨兵的 `idx`：单壁纸时等于 `n-1`，**多壁纸时等于「第一页的帧数」**
   （实测第一页 2 帧 → 2；4 帧 → 4）。设备侧看起来不读它，但要做到逐字节一致就得照抄。
"""
import struct

PREVIEW_W = 212
PREVIEW_H = 520
PREVIEW_BLOCK = 12 + PREVIEW_W * PREVIEW_H * 4     # 440972，尾部固定开销

MAGIC = b"\x5a\xa5\x34\x12"
INDEX_ENTRY_SIZE = 16
ID_LEN = 10
TITLE_LEN = 16

INDEX_START = 272           # 无 AOD 时的索引表起点
INDEX_START_AOD = 360       # 带 AOD 时的索引表起点（元数据多 88 B）

TAG_SENTINEL = 0x0500       # 索引表条目 / 描述块哨兵都用这个
TAG_ANCHOR = 0x0000
TAG_BITMAP = 0x0200
TAG_ARRAY = 0x0300
TAG_WIDGET = 0x0700

# AOD 素材在文件里的实排顺序（注意与描述块内的顺序不同）
ASSET_ORDER = (TAG_ANCHOR, TAG_WIDGET, TAG_BITMAP, TAG_ARRAY)

HDR_FIXED = 0x800           # 头部 [16-19]


def _align4(x):
    return x + ((4 - x % 4) % 4)


def rgba_to_bgra(raw):
    """RGBA8888 → BGRA8888（描述块与尾部预览要的都是 BGRA）。"""
    out = bytearray(raw)
    for i in range(0, len(out) - 3, 4):
        out[i], out[i + 2] = out[i + 2], out[i]
    return bytes(out)


def aod_records(widgets, images):
    """控件表 + 位图像素 → 描述记录列表。

    widgets: 见 `aod.widgets_from_fprj()`，每项是
        {'kind': 30, 'name','x','y','w','h','img'} 或
        {'kind': 32, 'name','x','y','dw','dh','digits','src','list'}
    images: {文件名: (宽, 高, RGBA 字节)}
    返回 [{'idx','tag','payload'}, ...]，顺序即描述块顺序：
        锚 0x0000 → 位图 0x0200 → 数组 0x0300 → 小件 0x0700
    """
    def bgra(name):
        w, h, raw = images[name]
        if len(raw) != w * h * 4:
            raise ValueError(f"{name} 像素长度不符：{len(raw)} != {w}*{h}*4")
        return rgba_to_bgra(raw)

    recs = []
    cls = {TAG_BITMAP: 0, TAG_WIDGET: 0}
    for i, w in enumerate(widgets):                       # 锚
        if w["kind"] == 30:
            tag, ax, ay = TAG_BITMAP, w["x"], w["y"]
        else:
            tag, ax, ay = TAG_WIDGET, w["x"] + w["dw"], w["y"]
        recs.append({"idx": i, "tag": TAG_ANCHOR,
                     "payload": struct.pack("<HHHHII", cls[tag], tag, ax, ay, 0, 0)})
        cls[tag] += 1

    k = 0
    for w in widgets:                                     # 位图
        if w["kind"] != 30:
            continue
        data = bgra(w["img"])
        recs.append({"idx": k, "tag": TAG_BITMAP,
                     "payload": struct.pack("<IHHI", 0, w["w"], w["h"], len(data)) + data})
        k += 1

    seen, k, arr_of = set(), 0, {}
    for w in widgets:                                     # 位图数组（同一 BitmapList 去重）
        if w["kind"] != 32:
            continue
        key = tuple(w["list"])
        if key in seen:
            continue
        seen.add(key)
        dw, dh, n = w["dw"], w["dh"], len(w["list"])
        pix = b"".join(bgra(f) for f in w["list"])
        hdr = struct.pack("<BBHHH", 0, n, 0, dw, dh) + struct.pack("<I", dw * dh * 4 * n)
        recs.append({"idx": k, "tag": TAG_ARRAY, "payload": hdr + pix})
        arr_of[key] = k
        k += 1

    k = 0
    for w in widgets:                                     # 小件（冒号这类数字位图的驱动项）
        if w["kind"] != 32:
            continue
        ai = arr_of[tuple(w["list"])]
        recs.append({"idx": k, "tag": TAG_WIDGET,
                     "payload": bytes.fromhex(w["src"]) + bytes([w["digits"], 0x16])
                                + struct.pack("<I", 0) + struct.pack("<HHII", ai, TAG_ARRAY, 0, 0)})
        k += 1
    return recs


def pack_face(files, preview_bgra, title="", face_id="", recs=(), has_aod=False,
              sentinel_idx=None, id_len=ID_LEN):
    """拼装整份 .face。

    files: [(name, data), ...] —— 顺序必须与 Compiler.exe 一致（按名字升序）。
    preview_bgra: 尾部预览像素，BGRA8888，长度须为 212*520*4。
    recs: `aod_records()` 的输出；无 AOD 时留空。
    sentinel_idx: 描述块哨兵的 idx。单壁纸传 None（= n-1），多壁纸传第一页帧数。
    """
    files = list(files)
    recs = list(recs)
    n = len(files)
    if len(preview_bgra) != PREVIEW_W * PREVIEW_H * 4:
        raise ValueError("预览位图长度必须是 %d，实为 %d"
                         % (PREVIEW_W * PREVIEW_H * 4, len(preview_bgra)))

    idx = INDEX_START_AOD if has_aod else INDEX_START
    d0 = idx + n * INDEX_ENTRY_SIZE                    # 描述块起点
    ndesc = len(recs) + 1                              # + 哨兵
    desc_end = d0 + ndesc * INDEX_ENTRY_SIZE

    # ---- 文件数据区：条目起点 4 字节对齐，末条也要补齐 ----
    layout = []
    cur = desc_end
    for name, data in files:
        nb = name.encode("ascii")
        size = 20 + len(nb) + len(data)                # 索引表里的 size 不含 padding
        layout.append((nb, data, cur, size))
        cur = _align4(cur + size)
    files_end = cur                                    # 已对齐

    # ---- AOD 素材区：实排 锚 → 小件 → 位图 → 数组 ----
    asset_start = files_end
    order = [k for tag in ASSET_ORDER for k in range(len(recs)) if recs[k]["tag"] == tag]
    order += [k for k in range(len(recs)) if k not in order]      # 兜底：不认识的 tag 排队尾
    blob_off = {}
    cur = asset_start
    for k in order:
        blob_off[k] = cur
        cur += len(recs[k]["payload"])
    assets_end = cur
    sentinel_off = d0 + (ndesc - 1) * INDEX_ENTRY_SIZE

    def first_off(tag):
        for k, r in enumerate(recs):
            if r["tag"] == tag:
                return d0 + k * INDEX_ENTRY_SIZE
        return -1

    def cnt(tag):
        return sum(1 for r in recs if r["tag"] == tag)

    first_non_anchor = next((d0 + k * INDEX_ENTRY_SIZE for k, r in enumerate(recs)
                             if r["tag"] != TAG_ANCHOR), -1)
    A = first_off(TAG_BITMAP)
    if A < 0:
        A = first_non_anchor if first_non_anchor >= 0 else sentinel_off
    B = first_off(TAG_ARRAY)
    if B < 0:
        B = sentinel_off
    D = first_off(TAG_WIDGET)
    if D < 0:
        D = sentinel_off

    out = bytearray()
    # ---- 头部 64 B ----
    out += MAGIC
    out += bytes([0, id_len])                          # [4] 保留, [5] ID 长度（两个独立字节）
    out += bytes(10)
    out += struct.pack("<I", HDR_FIXED)                # [16]
    out += bytes(8)
    out += struct.pack("<HH", 2 if has_aod else 1, 4 if has_aod else 0)   # [28] 屏数
    out += struct.pack("<I", assets_end)               # [32] 数据区结束
    out += bytes(4)
    out += _fixed_ascii(str(face_id), ID_LEN)          # [40]
    out += bytes(14)
    # ---- Title 区 ----
    out += bytes(40)
    out += _fixed_ascii(str(title), TITLE_LEN)         # [104]
    out += bytes(52)

    # ---- 元数据 ----
    main_meta = [assets_end, 1, idx - 16, 0,
                 idx, 0, idx, 0, idx, 0, idx,
                 n, idx, 0]
    main_meta += [d0, 0] * 4                           # 4 组 (d0, 0)
    assert len(main_meta) == 22, len(main_meta)
    out += b"".join(struct.pack("<I", v) for v in main_meta)
    if has_aod:
        aod_meta = [0xFFFFFFFF, cnt(TAG_ANCHOR), d0, 0,
                    A, cnt(TAG_BITMAP),
                    A, cnt(TAG_ARRAY),
                    B, 0,
                    D, 0,
                    D, 0,
                    D, cnt(TAG_WIDGET),
                    D, 0,
                    sentinel_off, 0,
                    sentinel_off, 0,
                    0,
                    sentinel_off,
                    INDEX_ENTRY_SIZE]
        assert len(aod_meta) == 25, len(aod_meta)
        out += b"".join(struct.pack("<I", v) for v in aod_meta)
    else:
        out += struct.pack("<III", 0, d0, INDEX_ENTRY_SIZE)

    # ---- 索引表（n 条） ----
    for i, (nb, data, off, size) in enumerate(layout):
        out += struct.pack("<HHIII", i, TAG_SENTINEL, 0, off, size)

    # ---- 描述块（有效记录 + 哨兵） ----
    for k, r in enumerate(recs):
        out += struct.pack("<HHIII", r["idx"], r["tag"], 0, blob_off[k], len(r["payload"]))
    out += struct.pack("<HHIII", n - 1 if sentinel_idx is None else sentinel_idx,
                       TAG_SENTINEL, 0, 0, 0)

    # ---- 文件数据区 ----
    for nb, data, off, size in layout:
        out += len(data).to_bytes(3, "little") + bytes([len(nb)]) + bytes(16) + nb + data
        out += bytes(_align4(off + size) - (off + size))

    # ---- AOD 素材 + 尾部预览 ----
    for k in order:
        out += recs[k]["payload"]
    out += struct.pack("<IHHI", 0, PREVIEW_W, PREVIEW_H, len(preview_bgra))   # 12 B 头：u32 0 + w + h + 长度
    out += preview_bgra
    return bytes(out)


def _fixed_ascii(s, length):
    """ASCII 定长字段：不足补 0，超长截断。"""
    b = s.encode("ascii", "replace")[:length]
    return b + bytes(length - len(b))


def unpack_face(data):
    """把 .face 拆回 pack_face 的输入，用于往返对拍 / 结构校验。"""
    if data[:4] != MAGIC:
        raise ValueError("magic 不符，不是 .face 文件")
    screens = struct.unpack_from("<H", data, 28)[0]
    has_aod = screens == 2
    n = struct.unpack_from("<I", data, 216)[0]
    idx = INDEX_START_AOD if has_aod else INDEX_START

    entries = [struct.unpack_from("<HHIII", data, idx + i * INDEX_ENTRY_SIZE)
               for i in range(n)]

    d0 = idx + n * INDEX_ENTRY_SIZE
    recs, p = [], d0
    while True:
        ridx, tag, _z, off, size = struct.unpack_from("<HHIII", data, p)
        if tag == TAG_SENTINEL:
            sentinel = {"idx": ridx, "off": off, "size": size}
            break
        recs.append({"idx": ridx, "tag": tag, "payload": data[off:off + size]})
        p += INDEX_ENTRY_SIZE
        if p > len(data):
            raise ValueError("描述块没有哨兵，文件可能已损坏")
    desc_end = p + INDEX_ENTRY_SIZE

    files = []
    for _i, _tag, _z, off, size in entries:
        name_len = data[off + 3]
        name = data[off + 20:off + 20 + name_len].decode("ascii", "replace")
        start = off + 20 + name_len
        files.append((name, data[start:start + size - 20 - name_len]))

    pstart = len(data) - PREVIEW_BLOCK
    _z, pw, ph, plen = struct.unpack_from("<HHHI", data, pstart)
    preview_bgra = data[pstart + 12:pstart + 12 + plen]

    return {
        "title": data[104:104 + TITLE_LEN].split(b"\x00")[0].decode("ascii", "replace"),
        "face_id": data[40:40 + ID_LEN].split(b"\x00")[0].decode("ascii", "replace"),
        "id_len": data[5],
        "has_aod": has_aod,
        "screens": screens,
        "n": n,
        "idx": idx,
        "d0": d0,
        "desc_end": desc_end,
        "sentinel_idx": sentinel["idx"],
        "files": files,
        "recs": recs,
        "preview": (pw, ph, plen),
        "preview_bgra": preview_bgra,
    }
