# -*- coding: utf-8 -*-
"""跨语言差分回归 —— **Python 参考侧**。

跟 JVM 侧（`tools/diff/jvm/DiffMain.java`）用同一份用例表，各跑一遍，逐字节比对。
本模块只服务这个回归，**不参与生产流程**；生产代码是
`watchface-tool/watchface_tool/{lua,aod}.py` 与
`watchface-android/core/face/{LuaGen,AodGen,FaceBuilder}.java`。

⚠️ 三条「两边必须一字不差」的约定，改一边就要同步另一边：

1. **用例表格式** —— `lua_cases.txt`(20 字段) / `aod_cases.txt`(13 字段) /
   `assemble_cases.txt`(5 字段)，解析逻辑与 `DiffMain.rows()`+各 `*Cfg()` 一一对应。
2. **装配素材生成规则** —— `files_for()` / `preview_for()` 与
   `DiffMain.filesFor()` / `previewFor()` 必须给出同样的名字与字节。
3. **规范文本** —— `canon()` 与 `DiffMain.canon()` 输出同样的行。

为什么 AOD 的描述记录要在这里另写一份：Python 侧**没有**生产用的 packer
（Windows 走 Compiler.exe，安卓走 Java），所以这边只能给参考实现。
它照的是 `docs/face格式规范.md` §11.8，不是照抄 Java。
"""
import os
import re
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(_HERE))          # tools/diff -> tools -> repo
sys.path.insert(0, os.path.join(REPO, "watchface-tool"))

TITLE = "DiffDemo"
FACE_ID = "99887766"

PREVIEW_W, PREVIEW_H = 212, 520
SENTINEL = 0x0500


# ------------------------------------------------------------------ 装配素材

def files_for(n_files, extra_last):
    """主文件清单。必须与 DiffMain.filesFor() 完全一致。"""
    out = []
    for k in range(n_files):
        length = 41 + 13 * k + (extra_last if k == n_files - 1 else 0)
        out.append(("lua/f%02d.bin" % k, bytes(((k * 37 + i * 7) & 0xFF) for i in range(length))))
    return out


def preview_for():
    """预览位图像素（212*520*4 BGRA）。必须与 DiffMain.previewFor() 一致。"""
    return bytes(((i * 11 + 7) & 0xFF) for i in range(PREVIEW_W * PREVIEW_H * 4))


def preview_block():
    """尾部预览的**完整块**：12 B 头 + 像素。

    pack() 收的是这个；JVM 的 FaceBuilder.build 收的是裸像素、头由它自己写 ——
    两边最终落到文件里的字节必须一样。
    """
    px = preview_for()
    return struct.pack("<IHHI", 0, PREVIEW_W, PREVIEW_H, len(px)) + px


# ------------------------------------------------------------------ 用例解析

def _rows(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            t = raw.strip()
            if not t or t.startswith("#"):
                continue
            out.append(raw.rstrip("\n").split("|"))
    return out


def load_lua_cases(path):
    cases = []
    for p in _rows(path):
        assert len(p) == 20, (len(p), p)
        walls = []
        if p[1]:
            for w in p[1].split(","):
                pre, cnt, per = w.split(":")
                walls.append({"prefix": pre, "count": int(cnt), "period_ms": int(per)})
        cases.append(dict(
            name=p[0], walls=walls, period_ms=int(p[2]), ext=p[3],
            show_time=p[4] == "1", show_date=p[5] == "1",
            time_align=p[6], time_ofs=(int(p[7]), int(p[8])), time_size=int(p[9]),
            time_color=int(p[10], 16), time_fmt=p[11],
            date_align=p[12], date_ofs=(int(p[13]), int(p[14])), date_size=int(p[15]),
            date_color=int(p[16], 16), date_fmt=p[17],
            tap_action=p[18], fps_desc=(p[19] or None)))
    return cases


def load_aod_cases(path):
    cases = []
    for p in _rows(path):
        assert len(p) == 13, (len(p), p)
        cases.append(dict(
            name=p[0], enabled=p[1] == "1", bg_mode=p[2], custom_bg=p[3] == "1",
            time_mode=p[4], time_y=int(p[5]), date_y=int(p[6]), color=p[7],
            tw=int(p[8]), th=int(p[9]), dw=int(p[10]), dh=int(p[11]), cw=int(p[12])))
    return cases


def load_asm_cases(path):
    cases = []
    for p in _rows(path):
        assert len(p) == 5, (len(p), p)
        cases.append(dict(name=p[0], has_aod=p[1] == "1", aod_case=p[2],
                          n_files=int(p[3]), extra_last=int(p[4])))
    return cases


# ------------------------------------------------------------------ AOD：生产路径

def widgets_from_fprj(path):
    """把生产代码写出的 AOD.fprj 解析成控件表（与 Java AodGen.Widget 同构）。

    这里**刻意回读 fprj**，而不是另写一份布局算法 —— 那样测的才是生产路径。
    """
    xml = open(path, encoding="utf-16").read()
    ws = []
    for m in re.finditer(r"<Widget\s+([^>]*?)/>", xml):
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        shape = int(a["Shape"])
        if shape == 30:
            ws.append(dict(kind=30, name=a["Name"], x=int(a["X"]), y=int(a["Y"]),
                           w=int(a["Width"]), h=int(a["Height"]), img=a["Bitmap"]))
        elif shape == 32:
            digits = int(a["Digits"])
            ws.append(dict(kind=32, name=a["Name"], x=int(a["X"]), y=int(a["Y"]),
                           dw=int(a["Width"]) // digits, dh=int(a["Height"]), digits=digits,
                           src=a["Value_Src"], list=a["BitmapList"].split("|")))
    return ws


def python_widgets_for(case, workdir, aod_mod):
    """跑**生产**的 aod.build_aod()，再回读它写出的 fprj。返回 None 表示没有 AOD 子工程。"""
    from PIL import Image

    # 尺寸常量按用例打补丁（aod.py 直接 import 了这些名字，改模块属性即生效）
    aod_mod.AOD_TIME_DIGIT_W = case["tw"]
    aod_mod.AOD_TIME_DIGIT_H = case["th"]
    aod_mod.AOD_DATE_DIGIT_W = case["dw"]
    aod_mod.AOD_DATE_DIGIT_H = case["dh"]
    aod_mod.AOD_COLON_W = case["cw"]

    os.makedirs(os.path.join(workdir, "images"), exist_ok=True)

    bg_img = None
    if case["custom_bg"]:
        bg_img = os.path.join(workdir, "custom_src.png")
        im = Image.new("RGB", (300, 700))
        px = im.load()
        for y in range(700):
            for x in range(300):
                px[x, y] = ((x * 255) // 300, 40, (y * 255) // 700)
        im.save(bg_img)

    aod_mod.build_aod(workdir, dict(
        enabled=case["enabled"], bg_mode=case["bg_mode"], bg_image=bg_img,
        time_mode=case["time_mode"], time_y=case["time_y"], date_y=case["date_y"],
        color=case["color"], font_path=None))

    fprj = os.path.join(workdir, "AOD", "AOD.fprj")
    return widgets_from_fprj(fprj) if os.path.isfile(fprj) else None


# ------------------------------------------------------------------ AOD：描述记录

def needed(ws):
    """控件表 → {文件名: (宽, 高)}。"""
    m = {}
    for w in ws:
        if w["kind"] == 30:
            m[w["img"]] = (w["w"], w["h"])
        else:
            for f in w["list"]:
                m[f] = (w["dw"], w["dh"])
    return m


def zero_images(ws):
    """零像素素材。两边都不需要真像素 —— 尺寸对上，剩下的搬运是平凡逻辑。"""
    return {name: (w, h, bytes(w * h * 4)) for name, (w, h) in needed(ws).items()}


def records_from_spec(images, widgets):
    """按 docs/face格式规范.md §11.8 算出 AOD 描述块。

    记录 = u16 idx, u16 tag, u32 0, u32 off, u32 size（off 由 pack() 填，这里只管 size/payload）。
    块内顺序：锚(0x0000) → 位图(0x0200) → 数组(0x0300) → 小件(0x0700)；
    idx 是**按类各自的计数器**，只有 0x0000 用的是控件序号。
    """
    def bgra_of(fname):
        raw = bytearray(images[fname][2])               # 存的是 RGBA，记录里要 BGRA
        for i in range(0, len(raw), 4):
            raw[i], raw[i + 2] = raw[i + 2], raw[i]
        return bytes(raw)

    recs = []
    cls = {0x0200: 0, 0x0700: 0}
    for i, w in enumerate(widgets):                      # 锚
        if w["kind"] == 30:
            tag, ax, ay = 0x0200, w["x"], w["y"]
        else:
            tag, ax, ay = 0x0700, w["x"] + w["dw"], w["y"]
        recs.append(dict(idx=i, tag=0x0000, size=16,
                         payload=struct.pack("<HHHHII", cls[tag], tag, ax, ay, 0, 0)))
        cls[tag] += 1

    k = 0
    for w in widgets:                                    # 位图
        if w["kind"] != 30:
            continue
        data = bgra_of(w["img"])
        recs.append(dict(idx=k, tag=0x0200, size=12 + len(data),
                         payload=struct.pack("<IHHI", 0, w["w"], w["h"], len(data)) + data))
        k += 1

    seen, k, arr_of = set(), 0, {}
    for w in widgets:                                    # 位图数组（同一 BitmapList 去重）
        if w["kind"] != 32:
            continue
        key = tuple(w["list"])
        if key in seen:
            continue
        seen.add(key)
        dw, dh, n = w["dw"], w["dh"], len(w["list"])
        pix = b"".join(bgra_of(f) for f in w["list"])
        hdr = struct.pack("<BBHHH", 0, n, 0, dw, dh) + struct.pack("<I", dw * dh * 4 * n)
        recs.append(dict(idx=k, tag=0x0300, size=len(hdr) + len(pix), payload=hdr + pix))
        arr_of[key] = k
        k += 1

    k = 0
    for w in widgets:                                    # 小件（冒号这类）
        if w["kind"] != 32:
            continue
        ai = arr_of[tuple(w["list"])]
        recs.append(dict(idx=k, tag=0x0700, size=20,
                         payload=bytes.fromhex(w["src"]) + bytes([w["digits"], 0x16])
                                 + struct.pack("<I", 0) + struct.pack("<HHII", ai, 0x0300, 0, 0)))
        k += 1
    return recs


def canon(widgets, recs):
    """控件表 + 描述记录的规范文本。必须与 DiffMain.canon() 逐字符一致。"""
    lines = []
    for w in widgets:
        if w["kind"] == 30:
            lines.append("W|30|%s|%d|%d|%d|%d||||%s" % (
                w["name"], w["x"], w["y"], w["w"], w["h"], w["img"]))
        else:
            lines.append("W|32|%s|%d|%d|%d|%d|%d|%s||%s" % (
                w["name"], w["x"], w["y"], w["dw"] * w["digits"], w["dh"],
                w["digits"], w["src"], ",".join(w["list"])))
    for r in recs:
        lines.append("R|%d|%d|%d|%s" % (r["idx"], r["tag"], r["size"], r["payload"].hex()))
    return ("\n".join(lines) + "\n") if lines else ""


# ------------------------------------------------------------------ 装配（参考 packer）

def _align4(x):
    return x + ((4 - x % 4) % 4)


def pack(files, records, title, face_id, preview, has_aod):
    """按 docs/face格式规范.md §11.8 拼出整份 .face。

    参考实现，只为差分而存在。布局：
      [0,172) 头部+Title · [172,360) 元数据（有 AOD 时尾部多 88B）·
      索引表 · 描述块 · 主文件数据区 · [AOD 素材区] · 尾部预览

    preview 是**含 12 B 头**的完整尾块（见 preview_block()）。
    """
    n = len(files)
    idx = 360 if has_aod else 272
    d0 = idx + n * 16
    desc_end = d0 + (len(records) + 1) * 16             # +1 = 哨兵

    # 1) 主文件数据区：每条 4 字节对齐（**末尾那条也要补**）
    cur = desc_end
    layout = []
    for name, data in files:
        size = 20 + len(name) + len(data)
        layout.append((cur, size))
        cur = _align4(cur + size)
    files_end = cur

    # 2) 素材区：实排顺序 锚 → 小件 → 位图 → 数组（与描述块内的顺序不同）
    order = {0x0000: 0, 0x0700: 1, 0x0200: 2, 0x0300: 3}
    seq = sorted(range(len(records)), key=lambda i: (order[records[i]["tag"]], i))
    asset = bytearray()
    blob_off = {}
    asset_start = files_end                              # files_end 已 4 字节对齐
    for i in seq:
        blob_off[i] = asset_start + len(asset)
        asset += records[i]["payload"]
    assets_end = asset_start + len(asset)

    # 3) 元数据
    sent_off = d0 + len(records) * 16

    def rec_off(tag):
        for k, r in enumerate(records):
            if r["tag"] == tag:
                return d0 + k * 16
        return None

    def rec_cnt(tag):
        return sum(1 for r in records if r["tag"] == tag)

    off_first_nonanchor = None
    for k, r in enumerate(records):
        if r["tag"] != 0x0000:
            off_first_nonanchor = d0 + k * 16
            break
    if off_first_nonanchor is None:
        off_first_nonanchor = sent_off

    A = rec_off(0x0200)
    if A is None:
        A = off_first_nonanchor
    B = rec_off(0x0300)
    if B is None:
        B = sent_off
    D = rec_off(0x0700)
    if D is None:
        D = sent_off
    aod_meta = [0xFFFFFFFF, rec_cnt(0x0000), d0, 0, A, rec_cnt(0x0200), A, rec_cnt(0x0300),
                B, 0, D, 0, D, 0, D, rec_cnt(0x0700), D, 0, sent_off, 0, sent_off, 0, 0,
                sent_off, 16]

    out = bytearray()
    # 头部 64B
    out += b"\x5a\xa5\x34\x12"
    out += bytes([0, 0])
    out += bytes(10)
    out += struct.pack("<I", 0x800)
    out += bytes(8)
    out += struct.pack("<HH", 2 if has_aod else 1, 4 if has_aod else 0)   # [28] 屏数
    out += struct.pack("<I", assets_end)                                  # [32] 数据区结束
    out += bytes(4)
    out += (face_id.encode("ascii") + bytes(10))[:10]
    out += bytes(14)
    # Title 区
    out += bytes(40)
    out += (title.encode("ascii") + bytes(16))[:16]
    out += bytes(52)
    # 元数据主屏段 [172,260) = 22 槽
    main_meta = [assets_end, 1, idx - 16, 0,
                 idx, 0, idx, 0, idx, 0, idx,
                 n, idx, 0,
                 d0, 0, d0, 0, d0, 0, d0, 0]
    assert len(main_meta) == 22, len(main_meta)
    out += b"".join(struct.pack("<I", v) for v in main_meta)
    if has_aod:
        out += b"".join(struct.pack("<I", v) for v in aod_meta)
    else:
        out += struct.pack("<III", 0, d0, 16)            # 无 AOD 只有 3 槽
    # 索引表（n 条）
    for i, (name, data) in enumerate(files):
        o, sz = layout[i]
        out += struct.pack("<HHIII", i, SENTINEL, 0, o, sz)
    # 描述块（含末尾哨兵）
    for k, r in enumerate(records):
        out += struct.pack("<HHIII", r["idx"], r["tag"], 0, blob_off[k], r["size"])
    out += struct.pack("<HHIII", n - 1, SENTINEL, 0, 0, 0)
    # 文件数据区
    for i, (name, data) in enumerate(files):
        o, sz = layout[i]
        nb = name.encode("ascii")
        out += len(data).to_bytes(3, "little") + bytes([len(nb)]) + bytes(16) + nb + data
        out += bytes(_align4(o + sz) - (o + sz))
    # 素材 + 预览
    out += asset
    out += preview
    return bytes(out)
