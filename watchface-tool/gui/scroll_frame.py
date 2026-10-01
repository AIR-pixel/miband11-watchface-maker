# -*- coding: utf-8 -*-
"""可滚动容器。

tkinter 没有现成的 ScrollFrame。这里的实现要点：

- 用 Canvas + 内嵌 Frame + 竖直 Scrollbar；
- 宽度跟随 Canvas 变（`<Configure>` 时改内嵌窗口宽度），这样内部控件能正常
  sticky="ew" 拉伸，而不是被裁掉；
- **height 不跟随**，始终用 `winfo_reqheight()`，否则滚不动；
- 只在内容真的超出时才显示滚动条（否则一个空滚动条很碍眼）；
- **鼠标滚轮绑在整个 Canvas 上**，`bind_all` 会在切页之后继续劫持滚轮，不能用。
"""
import tkinter as tk
from tkinter import ttk


class ScrollFrame(ttk.Frame):
    """把内容放进 `.body`（一个普通 ttk.Frame）。"""

    def __init__(self, parent, dpr=1.0, **kw):
        super().__init__(parent, **kw)
        self.dpr = dpr

        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scroll)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.body = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)

        # 滚轮：只在本控件可见/指针在范围内时生效
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)
        self._wheel_bound = False

    # ---------------------------------------------------------------- 事件

    def _on_scroll(self, first, last):
        # 内容没超出就不显示滚动条（Windows 主题下空滚动条很抢眼）
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.vbar.grid_remove()
        else:
            self.vbar.grid()
        self.vbar.set(first, last)

    def _on_body(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def _bind_wheel(self, _e=None):
        if not self._wheel_bound:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
            self._wheel_bound = True

    def _unbind_wheel(self, _e=None):
        if self._wheel_bound:
            self.canvas.unbind_all("<MouseWheel>")
            self._wheel_bound = False

    def _on_wheel(self, e):
        try:
            self.canvas.yview_scroll(int(-e.delta / 120), "units")
        except Exception:                            # noqa: BLE001
            pass
