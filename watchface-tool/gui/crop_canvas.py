# -*- coding: utf-8 -*-
"""裁剪预览画布：显示素材预览帧，支持拖拽移动 / 角点缩放裁剪框（比例锁定 212:520）。

缩放的两个关键修正（此前"缩放异常"的原因）：
1. 高度按**绝对位置**推导（当前点到锚点的位移），而不是"初始高度 + 单步增量"——
   后者每步都从按下时刻重算，导致缩放几乎不累积、拖了没反应。
2. 水平/垂直拖动都能驱动缩放（取两个方向推导值的较大者），不再只认垂直分量。
另外补充滚轮缩放（以框中心为锚），缩放大改时最好用。
"""
from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QWidget

from watchface_tool.constants import ASPECT


class CropCanvas(QWidget):
    cropChanged = pyqtSignal(tuple)   # (x0, y0, x1, y1) 源像素坐标

    _HANDLE_VIS = 8    # 角点手柄视觉半边长（屏幕像素）
    _HANDLE_HIT = 20   # 角点手柄命中半边长（屏幕像素，比视觉大以好抓）
    _MIN_H = 20.0      # 裁剪框最小高度（源像素）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None          # 预览 QPixmap
        self._src_w = 0
        self._src_h = 0
        self._img_rect = QRectF()    # 图片在控件内的绘制区域
        self._crop = QRectF()        # 裁剪框（图片像素坐标）
        self._mode = None            # "move" / "resize" / None
        self._last = QPointF()
        self._origin = QRectF()
        self.setMinimumSize(260, 420)
        self.setMouseTracking(True)

    # ---------- 对外 ----------
    def set_image(self, pil_img):
        """接收 PIL RGB Image 作为预览帧。"""
        self._src_w, self._src_h = pil_img.size
        data = pil_img.convert("RGB").tobytes("raw", "RGB")
        qimg = QImage(data, self._src_w, self._src_h, self._src_w * 3, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qimg)
        self._recalc_fit()
        # 初始裁剪框：默认 85% 高居中 —— 留出上下移动余地（全高会被 clamp 锁死）
        self._crop = self._default_crop(0.85)
        self.update()
        self._emit()

    def _default_crop(self, frac=0.85):
        ch = self._src_h * frac
        cw = ch * ASPECT
        if cw > self._src_w:
            cw = float(self._src_w)
            ch = cw / ASPECT
        cx, cy = self._src_w / 2.0, self._src_h / 2.0
        return QRectF(cx - cw / 2, cy - ch / 2, cw, ch)

    def reset_crop(self):
        """恢复到默认裁剪框。"""
        if not self._pixmap:
            return
        self._crop = self._default_crop(0.85)
        self._clamp_crop()
        self._emit()
        self.update()

    def fill_crop(self):
        """铺满：尽可能大地取框（会自动吸附比例）。"""
        if not self._pixmap:
            return
        self._crop = self._default_crop(1.0)
        self._clamp_crop()
        self._emit()
        self.update()

    def get_crop(self):
        return (int(self._crop.x()), int(self._crop.y()),
                int(self._crop.x() + self._crop.width()),
                int(self._crop.y() + self._crop.height()))

    def src_size(self):
        return self._src_w, self._src_h

    # ---------- 坐标换算 ----------
    def _recalc_fit(self):
        if not self._pixmap:
            return
        pw, ph = self._pixmap.width(), self._pixmap.height()
        cw, ch = self.width(), self.height()
        scale = min(cw / pw, ch / ph)
        dw, dh = pw * scale, ph * scale
        ox = (cw - dw) / 2.0
        oy = (ch - dh) / 2.0
        self._img_rect = QRectF(ox, oy, dw, dh)

    def _img_to_widget(self, p):
        s = self._scale()
        return QPointF(self._img_rect.x() + p.x() * s, self._img_rect.y() + p.y() * s)

    def _widget_to_img(self, p):
        s = self._scale()
        return QPointF((p.x() - self._img_rect.x()) / s, (p.y() - self._img_rect.y()) / s)

    def _scale(self):
        if not self._pixmap:
            return 1.0
        return self._img_rect.width() / self._pixmap.width()

    def _handle_rect(self, hit=False):
        """右下角手柄在控件坐标里的矩形。hit=True 用放大的命中区。"""
        r = self._HANDLE_HIT if hit else self._HANDLE_VIS
        br = self._img_to_widget(self._crop.bottomRight())
        return QRectF(br.x() - r, br.y() - r, r * 2, r * 2)

    # ---------- 交互 ----------
    def mousePressEvent(self, e):
        if not self._pixmap:
            return
        pos = e.pos()
        if self._handle_rect(hit=True).contains(pos):
            self._mode = "resize"
        else:
            # 框内、框外都进入移动模式：改为相对拖动，不再把框瞬移到点击点
            self._mode = "move"
        self._last = QPointF(pos)
        self._origin = QRectF(self._crop)
        self.update()

    def mouseMoveEvent(self, e):
        if self._mode is None or not self._pixmap:
            return
        pos = e.pos()
        cur = self._widget_to_img(QPointF(pos))
        last = self._widget_to_img(self._last)

        if self._mode == "move":
            self._crop.translate(cur.x() - last.x(), cur.y() - last.y())
        elif self._mode == "resize":
            # 以按下时刻的左上角为锚，用当前点的绝对位移推导高度（横/竖拖都响应）
            anchor = self._origin.topLeft()
            h_from_y = cur.y() - anchor.y()
            h_from_x = (cur.x() - anchor.x()) / ASPECT
            new_h = max(self._MIN_H, max(h_from_y, h_from_x))
            new_w = new_h * ASPECT
            self._crop = QRectF(anchor.x(), anchor.y(), new_w, new_h)

        self._clamp_crop()
        self._last = QPointF(pos)
        self.update()

    def mouseReleaseEvent(self, e):
        self._mode = None
        self._clamp_crop()
        self._emit()
        self.update()

    def wheelEvent(self, e):
        """滚轮缩放：以框中心为锚。缩放大改时比拖手柄顺手。"""
        if not self._pixmap:
            return
        d = e.angleDelta().y()
        if d == 0:
            return
        factor = 1.12 if d > 0 else 1 / 1.12
        c = self._crop.center()
        new_h = max(self._MIN_H, self._crop.height() * factor)
        new_w = new_h * ASPECT
        if new_w > self._src_w:
            new_w = float(self._src_w)
            new_h = new_w / ASPECT
        if new_h > self._src_h:
            new_h = float(self._src_h)
            new_w = new_h * ASPECT
        self._crop = QRectF(c.x() - new_w / 2, c.y() - new_h / 2, new_w, new_h)
        self._clamp_crop()
        self._emit()
        self.update()

    def _crop_widget_rect(self):
        tl = self._img_to_widget(self._crop.topLeft())
        br = self._img_to_widget(self._crop.bottomRight())
        return QRectF(tl, br)

    def _clamp_crop(self):
        if not self._pixmap:
            return
        w = min(self._crop.width(), float(self._src_w))
        h = w / ASPECT
        if h > self._src_h:
            h = float(self._src_h)
            w = h * ASPECT
        w, h = max(w, self._MIN_H), max(h, self._MIN_H)
        self._crop.setWidth(w)
        self._crop.setHeight(h)
        x = min(max(self._crop.x(), 0.0), self._src_w - w)
        y = min(max(self._crop.y(), 0.0), self._src_h - h)
        self._crop.moveTo(x, y)

    def _emit(self):
        self.cropChanged.emit(self.get_crop())

    # ---------- 绘制 ----------
    def resizeEvent(self, e):
        self._recalc_fit()
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(40, 40, 40))
        if not self._pixmap:
            p.setPen(QColor(160, 160, 160))
            p.drawText(self.rect(), Qt.AlignCenter, "拖入视频 / GIF 后在此框选裁剪区域")
            return
        p.drawPixmap(self._img_rect.toRect(), self._pixmap)

        # 暗化裁剪框外区域
        full = self._img_rect
        cr = self._crop_widget_rect()
        dim = QColor(0, 0, 0, 150)
        p.fillRect(QRectF(full.x(), full.y(), full.width(), cr.y() - full.y()), dim)
        p.fillRect(QRectF(full.x(), cr.y() + cr.height(), full.width(),
                          full.height() - (cr.y() + cr.height() - full.y())), dim)
        p.fillRect(QRectF(full.x(), cr.y(), cr.x() - full.x(), cr.height()), dim)
        p.fillRect(QRectF(cr.x() + cr.width(), cr.y(),
                          full.x() + full.width() - (cr.x() + cr.width()), cr.height()), dim)

        # 裁剪框边框 + 四角标记 + 右下角缩放手柄
        p.setPen(QPen(QColor(0, 190, 255), 2))
        p.drawRect(cr)
        p.setPen(QPen(QColor(255, 255, 255, 220), 3))
        L = 14
        for cx, cy, dx, dy in ((cr.left(), cr.top(), 1, 1),
                               (cr.right(), cr.top(), -1, 1),
                               (cr.left(), cr.bottom(), 1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + L * dx, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + L * dy))
        # 右下角手柄（实心方块 + 白边，容易被找到）
        h = QRectF(self._handle_rect(hit=False))
        p.fillRect(h, QColor(0, 190, 255))
        p.setPen(QPen(QColor(255, 255, 255, 220), 2))
        p.drawRect(h)
        p.end()
