# -*- coding: utf-8 -*-
"""打包 `.face` —— 纯代码拼字节，**不调用 Compiler.exe**。

链路：`app/lua/` 里的帧与 `main.lua` → 读 `images/preview.png` 当尾部预览 →
（可选）按 AOD 控件表推导描述块 → 按格式拼容器。格式实现见 `facebin.py`，
布局说明见 `docs/face格式规范.md`。

历史：早期这层是 `subprocess` 调 `Compiler.exe -b`，再回写表盘 ID。
格式完整逆向之后就没有必要了 —— 编译器做的只是把已知输入搬成已知输出
（连表盘 ID 都写不对，得事后 patch）。纯代码版的产物已在
`tools/roundtrip_face.py` 里与编译器产物**逐字节对拍**通过。
"""
import os

from PIL import Image

from . import aod as aod_mod
from . import facebin
from .constants import FACE_ID_SIZE, SCREEN_H, SCREEN_W


class BuildError(RuntimeError):
    pass


def collect_files(app_lua_dir):
    """`app/lua/` 下的文件 → [("lua/名字", 字节)]，**按名字升序**。

    Compiler.exe 的顺序就是名字升序（实测 `face_*` → `main.lua` → `w2_*` → `w3_*`），
    照抄才能与它的产物逐字节一致。
    """
    out = []
    for name in sorted(os.listdir(app_lua_dir)):
        path = os.path.join(app_lua_dir, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                out.append(("lua/" + name, f.read()))
    if not out:
        raise BuildError("工程里没有任何帧或脚本，无法打包。")
    return out


def preview_bgra(path):
    """尾部预览位图：读 212x520 预览图 → BGRA8888（alpha 全 255）。

    选择器里显示的就是这张，固定 431 KB，占整份表盘的大头。
    """
    im = Image.open(path).convert("RGBA")
    if im.size != (SCREEN_W, SCREEN_H):
        im = im.resize((SCREEN_W, SCREEN_H), Image.LANCZOS)
    return facebin.rgba_to_bgra(im.tobytes())


def aod_records(aod_dir, widgets):
    """AOD 子工程 → 描述记录列表（顺带把素材实际尺寸与控件表核对一遍）。"""
    images = {}
    img_dir = os.path.join(aod_dir, "images")
    for name, (w, h) in aod_mod.needed_images(widgets).items():
        path = os.path.join(img_dir, name)
        if not os.path.isfile(path):
            raise BuildError(f"AOD 素材缺失：{name}（控件表声明了它）")
        im = Image.open(path).convert("RGBA")
        if im.size != (w, h):
            raise BuildError(f"AOD 素材 {name} 尺寸 {im.size} 与控件声明的 {(w, h)} 不符")
        images[name] = (w, h, im.tobytes())
    return facebin.aod_records(widgets, images)


def build_face(workdir, out_dir, face_name, face_id, first_wall_frames=None, aod_cfg=None):
    """把工程目录打成 `.face`，返回产物绝对路径。

    workdir:      工程根（含 app/lua、images、AOD）
    first_wall_frames: 第一张壁纸的帧数。多壁纸时描述块哨兵的 idx 要用它
                  （单壁纸时它等于 n-1，两种情况下都得显式传，别让默认值背锅）。
    aod_cfg:      息屏配置；enabled 为真才打 AOD 屏
    """
    face_id = str(face_id)
    if not face_id.isdigit():
        raise BuildError(f"表盘 ID 必须是数字: {face_id}")
    if len(face_id) > FACE_ID_SIZE:
        raise BuildError(f"表盘 ID 过长（最多 {FACE_ID_SIZE} 位）: {face_id}")

    files = collect_files(os.path.join(workdir, "app", "lua"))
    preview = preview_bgra(os.path.join(workdir, "images", "preview.png"))

    has_aod = bool(aod_cfg and aod_cfg.get("enabled"))
    recs = []
    if has_aod:
        widgets = aod_mod.plan_aod_widgets(aod_cfg)
        recs = aod_records(os.path.join(workdir, "AOD"), widgets)

    data = facebin.pack_face(
        files=files,
        preview_bgra=preview,
        title=os.path.splitext(face_name)[0],
        face_id=face_id,
        recs=recs,
        has_aod=has_aod,
        sentinel_idx=first_wall_frames,
    )

    os.makedirs(out_dir, exist_ok=True)
    face_path = os.path.abspath(os.path.join(out_dir, face_name))
    with open(face_path, "wb") as f:
        f.write(data)
    return face_path
