# -*- coding: utf-8 -*-
"""裁剪预览画布（tkinter 版）：显示素材预览帧，支持拖拽移动 / 角点缩放裁剪框（比例锁定 212:520）。

从 PyQt5 移植到 tkinter 的要点：
- 画的东西一样：暗化遮罩 + 蓝色边框 + 四角标记 + 右下角实心手柄。tk.Canvas 都能画。
  暗化**不能**用 `stipple` 网点 —— 会看出明显的"纱窗"格子。做法是先做一张整体压暗的
  位图（`Image.blend` 压 62%），框外四条边直接贴它的对应裁切区域，等于真 alpha。
- 缩放的坑沿用 PyQt 版的两条结论（这是之前"缩放异常"的根因，别改回去）：
  1. 高度按**绝对位置**推导（当前点到锚点的位移），而不是"初始高度 + 单步增量"——
     后者每步都从按下时刻重算，导致缩放几乎不累积、拖了没反应。
  2. 水平/垂直拖动都能驱动缩放（取两个方向推导值的较大者），不再只认垂直分量。
  另外保留滚轮缩放（以框中心为锚），缩放大改时最好用。
- 高 DPI：Canvas 拿到的宽高是**物理像素**，所以坐标换算全部在物理像素里做完，
  只有"手柄视觉大小 / 命中大小"这类跟手指有关的量乘 dpr。
"""
import tkinter as tk

from PIL import Image, ImageTk

from watchface_tool.constants import ASPECT

try:                                   # Pillow >= 9.1
    _LANCZOS = Image.Resampling.LANCZOS
except AttributeError:                 # 老版本兜底
    _LANCZOS = Image.LANCZOS

BG = "#282828"
ACCENT = "#00beff"


class CropCanvas(tk.Canvas):
    """裁剪画布。on_change(x0, y0, x1, y1) 在裁剪框变化（松手/滚轮/重置）时回调。"""

    _HANDLE_VIS = 8      # 角点手柄视觉半边长（逻辑像素）
    _HANDLE_HIT = 20     # 角点手柄命中半边长（逻辑像素，比视觉大以好抓）
    _MIN_H = 20.0        # 裁剪框最小高度（源像素）

    def __init__(self, master, on_change=None, dpr=1.0, **kw):
        super().__init__(master, bg=BG, highlightthickness=0, bd=0,
                         width=int(260 * dpr), height=int(420 * dpr), **kw)
        self._on_change = on_change
        self._dpr = dpr

        self._src = None            # PIL RGB Image（原始尺寸）
        self._photo = None          # 必须留着引用，否则 Tk 会把图回收成空白
        self._dim_src = None        # 整体压暗版，用于框外遮罩
        self._dim_photos = []       # 同样是引用保活
        self._src_w = 0
        self._src_h = 0
        self._img_rect = None       # 图片在控件内的绘制区域（物理像素）
        self._crop = None           # 裁剪框（源图像素坐标）
        self._mode = None           # "move" / "resize" / None
        self._last = (0.0, 0.0)
        self._origin = None
        self._pending_fit = False

        self.bind("<Configure>", self._on_configure)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)          # Windows / macOS
        self.bind("<Button-4>", lambda e: self._wheel_step(1))   # X11
        self.bind("<Button-5>", lambda e: self._wheel_step(-1))

    # ------------------------------------------------------------------ 对外

    def set_image(self, pil_img):
        """接收 PIL RGB Image 作为预览帧。"""
        self._src = pil_img.convert("RGB")
        self._src_w, self._src_h = self._src.size
        self._recalc_fit()
        # 初始裁剪框：默认 85% 高居中 —— 留出上下移动余地（全高会被 clamp 锁死）
        self._crop = self._default_crop(0.85)
        self._redraw()
        self._emit()

    def reset_crop(self):
        """恢复到默认裁剪框。"""
        if self._src is None:
            return
        self._crop = self._default_crop(0.85)
        self._clamp_crop()
        self._redraw()
        self._emit()

    def fill_crop(self):
        """铺满：尽可能大地取框（会自动吸附比例）。"""
        if self._src is None:
            return
        self._crop = self._default_crop(1.0)
        self._clamp_crop()
        self._redraw()
        self._emit()

    def get_crop(self):
        if self._crop is None:
            return (0, 0, 0, 0)
        return (int(self._crop[0]), int(self._crop[1]),
                int(self._crop[2]), int(self._crop[3]))

    def src_size(self):
        return self._src_w, self._src_h

    # ------------------------------------------------------------------ 几何

    def _default_crop(self, frac=0.85):
        ch = self._src_h * frac
        cw = ch * ASPECT
        if cw > self._src_w:
            cw = float(self._src_w)
            ch = cw / ASPECT
        cx, cy = self._src_w / 2.0, self._src_h / 2.0
        return [cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2]

    def _recalc_fit(self):
        if self._src is None:
            return
        cw, ch = self.winfo_width(), self.winfo_height()
        if cw <= 1 or ch <= 1:          # 还没真正布局完
            self._pending_fit = True
            return
        self._pending_fit = False
        scale = min(cw / self._src_w, ch / self._src_h)
        dw, dh = self._src_w * scale, self._src_h * scale
        ox, oy = (cw - dw) / 2.0, (ch - dh) / 2.0
        self._img_rect = (ox, oy, dw, dh)
        # 预览按适配后的尺寸重采样，Canvas 不做缩放
        disp = self._src.resize((max(int(dw), 1), max(int(dh), 1)), _LANCZOS)
        self._photo = ImageTk.PhotoImage(disp)
        # 再准备一张整体压暗的版本：框外遮罩直接贴它的四条边。
        # （tk 没有 alpha 通道，用 stipple 网点会看出"纱窗"格子，贴位图才干净。）
        self._dim_src = Image.blend(disp, Image.new("RGB", disp.size, (0, 0, 0)), 0.62)

    def _scale(self):
        if self._src is None or self._img_rect is None or self._src_w == 0:
            return 1.0
        return self._img_rect[2] / self._src_w

    def _img_to_widget(self, p):
        s = self._scale()
        return (self._img_rect[0] + p[0] * s, self._img_rect[1] + p[1] * s)

    def _widget_to_img(self, p):
        s = self._scale()
        return ((p[0] - self._img_rect[0]) / s, (p[1] - self._img_rect[1]) / s)

    def _handle_rect(self, hit=False):
        """右下角手柄在控件坐标里的矩形。hit=True 用放大的命中区。"""
        r = (self._HANDLE_HIT if hit else self._HANDLE_VIS) * self._dpr
        br = self._img_to_widget((self._crop[2], self._crop[3]))
        return (br[0] - r, br[1] - r, br[0] + r, br[1] + r)

    def _crop_widget_rect(self):
        tl = self._img_to_widget((self._crop[0], self._crop[1]))
        br = self._img_to_widget((self._crop[2], self._crop[3]))
        return (tl[0], tl[1], br[0], br[1])

    def _clamp_crop(self):
        if self._src is None:
            return
        w = min(self._crop[2] - self._crop[0], float(self._src_w))
        h = w / ASPECT
        if h > self._src_h:
            h = float(self._src_h)
            w = h * ASPECT
        w, h = max(w, self._MIN_H), max(h, self._MIN_H)
        x = min(max(self._crop[0], 0.0), self._src_w - w)
        y = min(max(self._crop[1], 0.0), self._src_h - h)
        self._crop = [x, y, x + w, y + h]

    # ------------------------------------------------------------------ 事件

    def _on_configure(self, _e=None):
        was_pending = self._pending_fit
        self._recalc_fit()
        if was_pending and self._crop is None and self._src is not None:
            self._crop = self._default_crop(0.85)
            self._emit()
        self._redraw()

    def _on_press(self, e):
        if self._src is None or self._img_rect is None:
            return
        pos = (float(e.x), float(e.y))
        if _in_rect(pos, self._handle_rect(hit=True)):
            self._mode = "resize"
            self.configure(cursor="sizing")
        else:
            # 框内、框外都进入移动模式：改为相对拖动，不再把框瞬移到点击点
            self._mode = "move"
            self.configure(cursor="fleur")
        self._last = pos
        self._origin = list(self._crop)

    def _on_drag(self, e):
        if self._mode is None or self._src is None or self._img_rect is None:
            return
        pos = (float(e.x), float(e.y))
        cur = self._widget_to_img(pos)
        last = self._widget_to_img(self._last)

        if self._mode == "move":
            dx, dy = cur[0] - last[0], cur[1] - last[1]
            self._crop[0] += dx
            self._crop[2] += dx
            self._crop[1] += dy
            self._crop[3] += dy
        elif self._mode == "resize":
            # 以按下时刻的左上角为锚，用当前点的绝对位移推导高度（横/竖拖都响应）
            ax, ay = self._origin[0], self._origin[1]
            h_from_y = cur[1] - ay
            h_from_x = (cur[0] - ax) / ASPECT
            new_h = max(self._MIN_H, max(h_from_y, h_from_x))
            new_w = new_h * ASPECT
            self._crop = [ax, ay, ax + new_w, ay + new_h]

        self._clamp_crop()
        self._last = pos
        self._redraw()

    def _on_release(self, _e=None):
        if self._mode is None:
            return
        self._mode = None
        self.configure(cursor="")
        self._clamp_crop()
        self._redraw()
        self._emit()

    def _on_wheel(self, e):
        self._wheel_step(1 if e.delta > 0 else -1)

    def _wheel_step(self, direction):
        """滚轮缩放：以框中心为锚。缩放大改时比拖手柄顺手。"""
        if self._src is None or self._crop is None:
            return
        factor = 1.12 if direction > 0 else 1 / 1.12
        cx = (self._crop[0] + self._crop[2]) / 2.0
        cy = (self._crop[1] + self._crop[3]) / 2.0
        new_h = max(self._MIN_H, (self._crop[3] - self._crop[1]) * factor)
        new_w = new_h * ASPECT
        if new_w > self._src_w:
            new_w = float(self._src_w)
            new_h = new_w / ASPECT
        if new_h > self._src_h:
            new_h = float(self._src_h)
            new_w = new_h * ASPECT
        self._crop = [cx - new_w / 2, cy - new_h / 2, cx + new_w / 2, cy + new_h / 2]
        self._clamp_crop()
        self._redraw()
        self._emit()

    def _emit(self):
        if self._on_change is not None and self._crop is not None:
            self._on_change(*self.get_crop())

    # ------------------------------------------------------------------ 绘制

    def _redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if self._src is None or self._img_rect is None:
            self.create_text(w / 2, h / 2, fill="#a0a0a0",
                             text="拖入视频 / GIF 后在此框选裁剪区域")
            return

        ir = self._img_rect
        self.create_image(ir[0], ir[1], anchor="nw", image=self._photo)

        cr = self._crop_widget_rect()
        # 暗化裁剪框外区域：贴压暗位图的四条边（tk 无 alpha，stipple 会有"纱窗"格子）
        self._dim_photos = []
        if self._dim_src is not None:
            for box in (
                (ir[0], ir[1], ir[0] + ir[2], cr[1]),                      # 上
                (ir[0], cr[3], ir[0] + ir[2], ir[1] + ir[3]),              # 下
                (ir[0], cr[1], cr[0], cr[3]),                              # 左
                (cr[2], cr[1], ir[0] + ir[2], cr[3]),                      # 右
            ):
                x0 = int(round(box[0] - ir[0]))
                y0 = int(round(box[1] - ir[1]))
                x1 = int(round(box[2] - ir[0]))
                y1 = int(round(box[3] - ir[1]))
                if x1 - x0 < 1 or y1 - y0 < 1:
                    continue
                strip = self._dim_src.crop((x0, y0, x1, y1))
                ph = ImageTk.PhotoImage(strip)
                self._dim_photos.append(ph)
                self.create_image(box[0], box[1], anchor="nw", image=ph)

        # 裁剪框边框
        self.create_rectangle(cr[0], cr[1], cr[2], cr[3],
                              outline=ACCENT, width=max(1, int(2 * self._dpr)))

        # 四角标记（白）—— 左上 / 右上 / 左下，右下留给手柄
        ln = 14 * self._dpr
        lw = max(1, int(3 * self._dpr))
        for cx, cy, dx, dy in ((cr[0], cr[1], 1, 1),
                               (cr[2], cr[1], -1, 1),
                               (cr[0], cr[3], 1, -1)):
            self.create_line(cx, cy, cx + ln * dx, cy, fill="#ffffff", width=lw)
            self.create_line(cx, cy, cx, cy + ln * dy, fill="#ffffff", width=lw)

        # 右下角手柄（实心方块 + 白边，容易被找到）
        hb = self._handle_rect(hit=False)
        self.create_rectangle(*hb, fill=ACCENT, outline="#ffffff",
                              width=max(1, int(2 * self._dpr)))


def _in_rect(p, r):
    return r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]
