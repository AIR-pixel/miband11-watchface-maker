# -*- coding: utf-8 -*-
"""主窗口（tkinter 版）：两个页面。

- **页面 1「动态壁纸」**：导入素材 → 框选 → 选压缩/帧率 → 生成 .face
- **页面 2「功能自定义」**：息屏显示（AOD）、主屏时间/日期元素、点击交互、多壁纸

设计要点（踩过的坑都记在这）：
- **高 DPI**：必须显式声明进程 DPI 感知，否则 150%/200% 缩放下整个界面是糊的。
- **没有 QThread**：用 threading.Thread + `root.after(0, ...)` 回主线程改 UI。
- **「生成」按钮必须放在 Notebook 外面**（固定贴底）。放进页面里就会被
  参数区顶到窗口外，而且切页后按钮跟着消失。
- 页面 2 内容比页面 1 长得多，装进 ScrollFrame，避免在高 DPI 小屏上被切掉。
"""
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from watchface_tool import aod as aod_mod
from watchface_tool import crop as crop_mod
from watchface_tool import extract as extract_mod
from watchface_tool import pipeline
from watchface_tool import quantize as quantize_mod
from watchface_tool.constants import (
    ALIGN_KEYS, ALIGN_LABELS, AOD_BG_MODES, AOD_TIME_MODES, COMPRESS_LEVELS,
    DEFAULT_BUDGET_MB, DEFAULT_FPS, DEFAULT_MAX_FRAMES, ENCODE_FORMATS,
    FPS_OPTIONS, JPG_QUALITY, JPG_QUALITY_OPTIONS, TAP_ACTIONS,
)

from .crop_canvas import CropCanvas
from .scroll_frame import ScrollFrame

CONFIG_PATH = os.path.expanduser("~/.watchface_tool.json")

_COMPILER_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "..", "assets", "Compiler.exe"),
    os.path.join(os.path.dirname(__file__), "..", "Compiler.exe"),
]

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except Exception:                                    # noqa: BLE001
    DND_FILES = None
    TkinterDnD = None
    _HAS_DND = False


# ---------------------------------------------------------------------- 配置

def _load_config():
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:                            # noqa: BLE001
            pass
    return {}


def _save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:                                # noqa: BLE001
        pass


# ---------------------------------------------------------------------- 高 DPI

def _system_dpi():
    """声明进程 DPI 感知并返回系统 DPI。必须在建窗口之前调用。"""
    if sys.platform != "win32":
        return 96
    try:
        import ctypes
    except Exception:                                # noqa: BLE001
        return 96
    for fn in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1),
               lambda: ctypes.windll.user32.SetProcessDPIAware()):
        try:
            fn()
            break
        except Exception:                            # noqa: BLE001
            continue
    try:
        return int(ctypes.windll.user32.GetDpiForSystem())
    except Exception:                                # noqa: BLE001
        return 96


def _apply_scaling(root, dpi):
    try:
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:                                # noqa: BLE001
        pass


def _short(path, limit=48):
    if not path or len(path) <= limit:
        return path
    head = path[: max(8, limit // 3)]
    tail = path[-(limit - len(head) - 1):]
    return f"{head}…{tail}"


def _hex_to_int(s):
    try:
        return int((s or "#FFFFFF").lstrip("#"), 16)
    except Exception:                                # noqa: BLE001
        return 0xFFFFFF


# ---------------------------------------------------------------------- 主窗口

class MainWindow:
    def __init__(self, root, dpr=1.0):
        self.root = root
        self.dpr = dpr

        self._source_path = None
        self._meta = None
        self._preview_img = None
        self._est_job = None
        self._aod_job = None
        self._building = False
        self._extra_walls = []       # [(path, crop_box 或 None)]
        self._aod_photo = None       # 保持引用，否则被 GC 掉图就没了

        cfg = _load_config()
        self._compiler = cfg.get("compiler") or self._find_compiler()

        root.title("手环 11 动态表盘制作工具")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self._build_ui()
        self._apply_compiler_state()
        self._on_fmt_changed()
        self._fit_window()
        self._setup_dnd()
        self._refresh_wall_list()
        self._schedule_aod_preview()

    # ------------------------------------------------------------------ 骨架

    def _build_ui(self):
        pad = int(10 * self.dpr)
        main = ttk.Frame(self.root, padding=pad)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        self.nb = ttk.Notebook(main)
        self.nb.grid(row=0, column=0, sticky="nsew")

        self.tab_wall = ttk.Frame(self.nb, padding=pad)
        self.tab_func = ScrollFrame(self.nb, dpr=self.dpr, padding=pad)
        self.nb.add(self.tab_wall, text="  1. 动态壁纸  ")
        self.nb.add(self.tab_func, text="  2. 功能自定义  ")

        self._build_tab_wall()
        self._build_tab_func(self.tab_func.body)

        # ---- 固定在底部的生成区（不随页面切换消失）----
        bottom = ttk.Frame(main)
        bottom.grid(row=1, column=0, sticky="ew", pady=(int(8 * self.dpr), 0))
        bottom.columnconfigure(0, weight=1)
        brow = ttk.Frame(bottom)
        brow.grid(row=0, column=0, sticky="ew")
        brow.columnconfigure(0, weight=0)
        brow.columnconfigure(1, weight=1)
        brow.columnconfigure(2, weight=0)
        self.build_btn = ttk.Button(brow, text="生成 .face", command=self._start_build)
        self.build_btn.grid(row=0, column=0)
        self.progress = ttk.Progressbar(brow, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=1, sticky="ew", padx=int(8 * self.dpr))
        ttk.Label(brow, text="输出到素材同级的 watchface_out/").grid(row=0, column=2)
        self.status = self._note(bottom, "就绪", color=None, group_pad=0)
        self.status.grid(row=1, column=0, sticky="w", pady=(int(4 * self.dpr), 0))

    def _wrap(self, px=330):
        return int(px * self.dpr)

    def _note(self, parent, text, color="#666", group_pad=6):
        """创建一条「跟着栏目宽度自动换行」的说明文字。``color=None`` 用主题默认色。

        tkinter 的 ``wraplength`` 是**像素常量**，写死一个值时窗口一变宽就会
        出现「一行只塞得下十来个字」的锯齿排版 —— 而这几段说明恰好是页面 2 上
        最需要读顺的部分。这里绑父容器的 ``<Configure>`` 动态改。

        不会自激的原因：父容器（LabelFrame）的宽度由外层 grid 列的 weight 撑开，
        而这里的 ``wraplength`` 恒小于父宽度 ⇒ 标签的请求宽度永远撑不大父容器。
        """
        lb = ttk.Label(parent, text=text, justify="left", anchor="w",
                       wraplength=self._wrap(330))
        if color:
            lb.configure(foreground=color)
        pad = int((group_pad + 8) * self.dpr)
        state = {"w": 0}

        def _follow(e):
            w = max(int(180 * self.dpr), e.width - pad)
            if abs(w - state["w"]) >= 6:          # 阈值挡住 Configure 自激
                state["w"] = w
                lb.configure(wraplength=w)

        parent.bind("<Configure>", _follow, add="+")
        return lb

    # ------------------------------------------------------------ 页面 1

    def _build_tab_wall(self):
        t = self.tab_wall
        t.columnconfigure(0, weight=1, minsize=int(300 * self.dpr))
        t.columnconfigure(1, weight=0)
        t.rowconfigure(0, weight=1)

        left = ttk.Frame(t)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, int(10 * self.dpr)))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.canvas = CropCanvas(left, on_change=self._on_crop_changed, dpr=self.dpr)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.crop_label = ttk.Label(left, text="裁剪区域：未加载", anchor="center")
        self.crop_label.grid(row=1, column=0, sticky="ew", pady=(int(4 * self.dpr), 0))

        brow = ttk.Frame(left)
        brow.grid(row=2, column=0, sticky="ew", pady=(int(4 * self.dpr), 0))
        brow.columnconfigure(0, weight=1)
        brow.columnconfigure(1, weight=1)
        ttk.Button(brow, text="重置裁剪框",
                   command=self.canvas.reset_crop).grid(row=0, column=0, sticky="ew",
                                                        padx=(0, int(4 * self.dpr)))
        ttk.Button(brow, text="铺满画面",
                   command=self.canvas.fill_crop).grid(row=0, column=1, sticky="ew")

        right = ttk.Frame(t)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        row = 0

        # ---- 1. 素材 ----
        g = ttk.LabelFrame(right, text="1. 素材（第 1 张壁纸）", padding=int(6 * self.dpr))
        g.grid(row=row, column=0, sticky="ew")
        g.columnconfigure(0, weight=1)
        row += 1
        btn_txt = "选择视频 / GIF / 图片（或拖入窗口）" if _HAS_DND else "选择视频 / GIF / 图片"
        ttk.Button(g, text=btn_txt, command=self._pick_source).grid(row=0, column=0, sticky="ew")
        self.src_label = ttk.Label(g, text="未选择", justify="left", wraplength=self._wrap())
        self.src_label.grid(row=1, column=0, sticky="w", pady=(int(4 * self.dpr), 0))

        # ---- 2. 参数 ----
        g = ttk.LabelFrame(right, text="2. 参数（体积第一杠杆是帧数，其次才是色深）",
                           padding=int(6 * self.dpr))
        g.grid(row=row, column=0, sticky="ew", pady=(int(8 * self.dpr), 0))
        g.columnconfigure(1, weight=1)
        row += 1
        r = 0

        def add_label(text, rr):
            ttk.Label(g, text=text).grid(row=rr, column=0, sticky="w",
                                         pady=int(2 * self.dpr), padx=(0, int(6 * self.dpr)))

        add_label("压缩等级", r)
        self.level_combo = ttk.Combobox(g, state="readonly",
                                        values=[c["label"] for c in COMPRESS_LEVELS.values()])
        self.level_combo.current(1)
        self.level_combo.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.level_combo.bind("<<ComboboxSelected>>", self._on_param_changed)
        r += 1

        add_label("编码格式", r)
        self.fmt_combo = ttk.Combobox(g, state="readonly",
                                      values=[c["label"] for c in ENCODE_FORMATS.values()])
        self.fmt_combo.current(0)
        self.fmt_combo.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.fmt_combo.bind("<<ComboboxSelected>>", self._on_fmt_changed)
        r += 1

        add_label("帧率", r)
        self._fps_labels = ["源素材帧率"] + [f"{f} FPS" for f in FPS_OPTIONS]
        self.fps_combo = ttk.Combobox(g, state="readonly", values=self._fps_labels)
        self.fps_combo.current(FPS_OPTIONS.index(DEFAULT_FPS) + 1)
        self.fps_combo.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.fps_combo.bind("<<ComboboxSelected>>", self._on_param_changed)
        r += 1

        add_label("截取区间", r)
        clip = ttk.Frame(g)
        clip.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        clip.columnconfigure(0, weight=1)
        clip.columnconfigure(1, weight=1)
        self.start_var = tk.StringVar(value="0.0")
        self.dur_var = tk.StringVar(value="")
        ttk.Spinbox(clip, from_=0, to=3600, increment=0.5, textvariable=self.start_var,
                    width=6, command=self._on_param_changed
                    ).grid(row=0, column=0, sticky="ew", padx=(0, int(4 * self.dpr)))
        ttk.Spinbox(clip, from_=0, to=3600, increment=0.5, textvariable=self.dur_var,
                    width=6, command=self._on_param_changed
                    ).grid(row=0, column=1, sticky="ew")
        self.start_var.trace_add("write", lambda *_: self._on_param_changed())
        self.dur_var.trace_add("write", lambda *_: self._on_param_changed())
        r += 1
        add_label("", r)
        ttk.Label(g, text="起始秒 / 时长秒（时长留空 = 全片）",
                  foreground="#666").grid(row=r, column=1, sticky="w")
        r += 1

        add_label("帧数上限", r)
        self.maxframes_var = tk.IntVar(value=DEFAULT_MAX_FRAMES)
        ttk.Spinbox(g, from_=1, to=240, textvariable=self.maxframes_var,
                    command=self._on_param_changed
                    ).grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.maxframes_var.trace_add("write", lambda *_: self._on_param_changed())
        r += 1

        self.speedup_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(g, text="保持帧率、压缩时长（快放）", variable=self.speedup_var,
                        command=self._on_param_changed
                        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=int(2 * self.dpr))
        r += 1

        add_label("JPEG 质量", r)
        self.jpgq_combo = ttk.Combobox(g, state="readonly",
                                       values=[f"q{q}" for q in JPG_QUALITY_OPTIONS])
        self.jpgq_combo.current(JPG_QUALITY_OPTIONS.index(JPG_QUALITY))
        self.jpgq_combo.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.jpgq_combo.bind("<<ComboboxSelected>>", self._on_param_changed)
        r += 1

        add_label("表盘名称", r)
        self.name_var = tk.StringVar(value="MyWatchface")
        ttk.Entry(g, textvariable=self.name_var).grid(row=r, column=1, sticky="ew",
                                                      pady=int(2 * self.dpr))
        r += 1

        add_label("表盘 ID", r)
        idrow = ttk.Frame(g)
        idrow.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        idrow.columnconfigure(0, weight=1)
        self.id_var = tk.StringVar(value=self._gen_id())
        ttk.Entry(idrow, textvariable=self.id_var).grid(row=0, column=0, sticky="ew",
                                                        padx=(0, int(4 * self.dpr)))
        ttk.Button(idrow, text="随机", width=6, command=lambda: self.id_var.set(self._gen_id())
                   ).grid(row=0, column=1)
        r += 1

        add_label("体积预算", r)
        self.budget_var = tk.IntVar(value=int(DEFAULT_BUDGET_MB))
        ttk.Spinbox(g, from_=1, to=20, textvariable=self.budget_var,
                    command=self._on_param_changed
                    ).grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.budget_var.trace_add("write", lambda *_: self._on_param_changed())
        r += 1

        self.est_label = ttk.Label(g, text="预估：—", foreground="#00806a", justify="left",
                                   wraplength=self._wrap())
        self.est_label.grid(row=r, column=0, columnspan=2, sticky="ew",
                            pady=(int(6 * self.dpr), 0))
        r += 1

        # ---- 3. Compiler.exe ----
        g = ttk.LabelFrame(right, text="3. Compiler.exe（自备，见 README）",
                           padding=int(6 * self.dpr))
        g.grid(row=row, column=0, sticky="ew", pady=(int(8 * self.dpr), 0))
        g.columnconfigure(0, weight=1)
        row += 1
        crow = ttk.Frame(g)
        crow.grid(row=0, column=0, sticky="ew")
        crow.columnconfigure(0, weight=1)
        self.comp_var = tk.StringVar(value=self._compiler or "")
        ttk.Entry(crow, textvariable=self.comp_var).grid(row=0, column=0, sticky="ew",
                                                         padx=(0, int(4 * self.dpr)))
        ttk.Button(crow, text="浏览", width=6, command=self._pick_compiler).grid(row=0, column=1)
        self.comp_status = ttk.Label(g, text="", justify="left", wraplength=self._wrap())
        self.comp_status.grid(row=1, column=0, sticky="w", pady=(int(4 * self.dpr), 0))

    # ------------------------------------------------------------ 页面 2

    def _build_tab_func(self, body):
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        col_l = ttk.Frame(body)
        col_l.grid(row=0, column=0, sticky="nsew", padx=(0, int(8 * self.dpr)))
        col_l.columnconfigure(0, weight=1)
        col_r = ttk.Frame(body)
        col_r.grid(row=0, column=1, sticky="nsew")
        col_r.columnconfigure(0, weight=1)

        self._build_aod_group(col_l)
        self._build_walls_group(col_l)
        self._build_info_group(col_r)
        self._build_tap_group(col_r)

    # ---- 息屏显示 ----
    def _build_aod_group(self, parent):
        g = ttk.LabelFrame(parent, text="A. 息屏显示（AOD）", padding=int(6 * self.dpr))
        g.grid(row=0, column=0, sticky="ew")
        g.columnconfigure(1, weight=1)
        r = 0

        self.aod_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(g, text="启用息屏显示（不做的话息屏会停在动画最后一帧）",
                        variable=self.aod_on, command=self._on_aod_changed
                        ).grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1

        self.aod_bg = tk.StringVar(value="none")
        self.aod_bg_labels = [v["label"] for v in AOD_BG_MODES.values()]
        ttk.Label(g, text="底图").grid(row=r, column=0, sticky="w", pady=int(2 * self.dpr))
        self.aod_bg_combo = ttk.Combobox(g, state="readonly", values=self.aod_bg_labels)
        self.aod_bg_combo.current(0)
        self.aod_bg_combo.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.aod_bg_combo.bind("<<ComboboxSelected>>", self._on_aod_changed)
        r += 1

        self.aod_bg_path = tk.StringVar(value="")
        row = ttk.Frame(g)
        row.grid(row=r, column=0, columnspan=3, sticky="ew", pady=int(2 * self.dpr))
        row.columnconfigure(0, weight=1)
        self.aod_bg_entry = ttk.Entry(row, textvariable=self.aod_bg_path)
        self.aod_bg_entry.grid(row=0, column=0, sticky="ew", padx=(0, int(4 * self.dpr)))
        self.aod_bg_btn = ttk.Button(row, text="选图", width=6, command=self._pick_aod_bg)
        self.aod_bg_btn.grid(row=0, column=1)
        r += 1

        self.aod_tmode = tk.StringVar(value="time")
        self.aod_tmode_labels = [v["label"] for v in AOD_TIME_MODES.values()]
        ttk.Label(g, text="显示内容").grid(row=r, column=0, sticky="w", pady=int(2 * self.dpr))
        self.aod_tmode_combo = ttk.Combobox(g, state="readonly", values=self.aod_tmode_labels)
        self.aod_tmode_combo.current(1)
        self.aod_tmode_combo.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.aod_tmode_combo.bind("<<ComboboxSelected>>", self._on_aod_changed)
        r += 1

        self.aod_time_y = tk.IntVar(value=200)
        self.aod_date_y = tk.IntVar(value=300)
        ttk.Label(g, text="时间 Y").grid(row=r, column=0, sticky="w", pady=int(2 * self.dpr))
        ttk.Spinbox(g, from_=0, to=454, textvariable=self.aod_time_y, command=self._on_aod_changed
                    ).grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        r += 1
        ttk.Label(g, text="日期 Y").grid(row=r, column=0, sticky="w", pady=int(2 * self.dpr))
        ttk.Spinbox(g, from_=0, to=492, textvariable=self.aod_date_y, command=self._on_aod_changed
                    ).grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        r += 1
        self.aod_time_y.trace_add("write", lambda *_: self._on_aod_changed())
        self.aod_date_y.trace_add("write", lambda *_: self._on_aod_changed())

        self.aod_color = tk.StringVar(value="#FFFFFF")
        ttk.Label(g, text="颜色").grid(row=r, column=0, sticky="w", pady=int(2 * self.dpr))
        crow = ttk.Frame(g)
        crow.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        crow.columnconfigure(0, weight=1)
        ttk.Entry(crow, textvariable=self.aod_color).grid(row=0, column=0, sticky="ew",
                                                          padx=(0, int(4 * self.dpr)))
        ttk.Button(crow, text="选色", width=6, command=lambda: self._pick_color(self.aod_color)
                   ).grid(row=0, column=1)
        self.aod_color.trace_add("write", lambda *_: self._on_aod_changed())
        r += 1

        self.aod_font = tk.StringVar(value="")
        ttk.Label(g, text="数字字体").grid(row=r, column=0, sticky="w", pady=int(2 * self.dpr))
        frow = ttk.Frame(g)
        frow.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        frow.columnconfigure(0, weight=1)
        ttk.Entry(frow, textvariable=self.aod_font).grid(row=0, column=0, sticky="ew",
                                                         padx=(0, int(4 * self.dpr)))
        ttk.Button(frow, text="TTF", width=5, command=self._pick_aod_font).grid(row=0, column=1)
        r += 1

        self._note(g, "AOD 用的是系统数据源（时/分/月/日），不走 Lua —— "
                      "实测 AOD 屏不支持 Lua。\n"
                      "总量约 160 KB（不含底图）；纯黑底图另加 431 KB。"
                 ).grid(row=r, column=0, columnspan=3, sticky="w",
                        pady=(int(4 * self.dpr), 0))
        r += 1

        # 预览
        self.aod_preview = ttk.Label(g, text="预览", anchor="center",
                                     relief="solid", borderwidth=1)
        self.aod_preview.grid(row=r, column=0, columnspan=3, pady=(int(6 * self.dpr), 0))
        r += 1
        self.aod_est = self._note(g, "", color="#00806a")
        self.aod_est.grid(row=r, column=0, columnspan=3, sticky="w")
        self._on_aod_changed()

    # ---- 多壁纸 ----
    def _build_walls_group(self, parent):
        g = ttk.LabelFrame(parent, text="B. 壁纸（多张，点击可轮换）", padding=int(6 * self.dpr))
        g.grid(row=1, column=0, sticky="ew", pady=(int(8 * self.dpr), 0))
        g.columnconfigure(0, weight=1)

        self._note(g, "第 1 张壁纸 = 页面 1 里选的素材。这里再加的是第 2、3… 张，\n"
                      "它们沿用页面 1 的压缩/帧率/时长参数（各自单独应用一次帧数上限）。"
                 ).grid(row=0, column=0, sticky="w")

        self.wall_list = tk.Listbox(g, height=5, activestyle="none",
                                    exportselection=False)
        self.wall_list.grid(row=1, column=0, sticky="ew", pady=(int(4 * self.dpr), 0))

        brow = ttk.Frame(g)
        brow.grid(row=2, column=0, sticky="ew", pady=(int(4 * self.dpr), 0))
        brow.columnconfigure(0, weight=1)
        brow.columnconfigure(1, weight=1)
        ttk.Button(brow, text="添加壁纸…", command=self._add_wall
                   ).grid(row=0, column=0, sticky="ew", padx=(0, int(4 * self.dpr)))
        ttk.Button(brow, text="移除选中", command=self._remove_wall
                   ).grid(row=0, column=1, sticky="ew")

        self._note(g, "注意：每张壁纸都会独立占体积（帧数 × 每帧字节）。"
                      "两张 12fps 的壁纸 ≈ 双倍体积。", color="#c00000"
                 ).grid(row=3, column=0, sticky="w", pady=(int(4 * self.dpr), 0))

    # ---- 主屏元素 ----
    def _build_info_group(self, parent):
        g = ttk.LabelFrame(parent, text="C. 主屏显示元素（Lua 层，位置精确可调）",
                           padding=int(6 * self.dpr))
        g.grid(row=0, column=0, sticky="ew")
        g.columnconfigure(1, weight=1)
        r = 0

        self.show_time = tk.BooleanVar(value=True)
        self.show_date = tk.BooleanVar(value=False)
        ttk.Checkbutton(g, text="显示时间", variable=self.show_time
                        ).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        self._align_row(g, r, "时间位置", "time_align", "TOP_MID", "time_x", 0, "time_y", 30)
        r += 1
        self._num_row(g, r, "时间字号", "time_size", 48)
        r += 1
        self._format_row(g, r, "时间格式", "time_fmt", "%H:%M")
        r += 1
        self._color_row(g, r, "时间颜色", "time_color", "#FFFFFF")
        r += 1

        ttk.Separator(g, orient="horizontal").grid(row=r, column=0, columnspan=5,
                                                   sticky="ew", pady=int(4 * self.dpr))
        r += 1

        ttk.Checkbutton(g, text="显示日期", variable=self.show_date
                        ).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        self._align_row(g, r, "日期位置", "date_align", "TOP_MID", "date_x", 0, "date_y", 86)
        r += 1
        self._num_row(g, r, "日期字号", "date_size", 16)
        r += 1
        self._format_row(g, r, "日期格式", "date_fmt", "%m/%d")
        r += 1
        self._color_row(g, r, "日期颜色", "date_color", "#EEEEEE")
        r += 1

        self._note(g, "格式用系统 strftime：%H:%M 时:分 · %m/%d 月/日 · %Y/%m/%d 年月日"
                 ).grid(row=r, column=0, columnspan=5, sticky="w")
        r += 1
        self._note(g, "位置 = 9 宫格锚点 + 像素偏移；偏移为正向右/下。"
                 ).grid(row=r, column=0, columnspan=5, sticky="w")
        r += 1

        for var in (self.show_time, self.show_date):
            var.trace_add("write", lambda *_: self._on_param_changed())

    # ---- 点击交互 ----
    def _build_tap_group(self, parent):
        g = ttk.LabelFrame(parent, text="D. 点击交互", padding=int(6 * self.dpr))
        g.grid(row=1, column=0, sticky="ew", pady=(int(8 * self.dpr), 0))
        g.columnconfigure(1, weight=1)

        self.tap_action = tk.StringVar(value="none")
        self._tap_keys = list(TAP_ACTIONS.keys())
        ttk.Label(g, text="短按表盘").grid(row=0, column=0, sticky="w", pady=int(2 * self.dpr))
        self.tap_combo = ttk.Combobox(g, state="readonly",
                                      values=[v["label"] for v in TAP_ACTIONS.values()])
        self.tap_combo.current(0)
        self.tap_combo.grid(row=0, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.tap_combo.bind("<<ComboboxSelected>>", self._on_tap_changed)


    # ---- 小控件工厂 ----
    def _align_row(self, g, r, label, var_prefix, default, xname, xdef, yname, ydef):
        setattr(self, var_prefix, tk.StringVar(value=default))
        setattr(self, xname, tk.IntVar(value=xdef))
        setattr(self, yname, tk.IntVar(value=ydef))
        ttk.Label(g, text=label).grid(row=r, column=0, sticky="w", pady=int(2 * self.dpr))
        box = ttk.Frame(g)
        box.grid(row=r, column=1, columnspan=2, sticky="ew", pady=int(2 * self.dpr))
        box.columnconfigure(0, weight=1)
        cb = ttk.Combobox(box, state="readonly",
                          values=[ALIGN_LABELS[k] for k in ALIGN_KEYS], width=6)
        cb.current(ALIGN_KEYS.index(default))
        cb.grid(row=0, column=0, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e, p=var_prefix: self._on_align(p))
        setattr(self, var_prefix + "_combo", cb)
        ttk.Label(box, text="±X").grid(row=0, column=1, padx=(int(6 * self.dpr), 2))
        ttk.Spinbox(box, from_=-200, to=200, width=5, textvariable=getattr(self, xname),
                    command=self._on_param_changed).grid(row=0, column=2)
        ttk.Label(box, text="±Y").grid(row=0, column=3, padx=(int(6 * self.dpr), 2))
        ttk.Spinbox(box, from_=-260, to=260, width=5, textvariable=getattr(self, yname),
                    command=self._on_param_changed).grid(row=0, column=4)
        getattr(self, xname).trace_add("write", lambda *_: self._on_param_changed())
        getattr(self, yname).trace_add("write", lambda *_: self._on_param_changed())

    def _num_row(self, g, r, label, name, default):
        setattr(self, name, tk.IntVar(value=default))
        ttk.Label(g, text=label).grid(row=r, column=0, sticky="w", pady=int(2 * self.dpr))
        ttk.Spinbox(g, from_=8, to=200, textvariable=getattr(self, name),
                    command=self._on_param_changed
                    ).grid(row=r, column=1, columnspan=2, sticky="ew", pady=int(2 * self.dpr))
        getattr(self, name).trace_add("write", lambda *_: self._on_param_changed())

    def _format_row(self, g, r, label, name, default):
        setattr(self, name, tk.StringVar(value=default))
        ttk.Label(g, text=label).grid(row=r, column=0, sticky="w", pady=int(2 * self.dpr))
        ttk.Entry(g, textvariable=getattr(self, name)
                  ).grid(row=r, column=1, columnspan=2, sticky="ew", pady=int(2 * self.dpr))
        getattr(self, name).trace_add("write", lambda *_: self._on_param_changed())

    def _color_row(self, g, r, label, name, default):
        setattr(self, name, tk.StringVar(value=default))
        ttk.Label(g, text=label).grid(row=r, column=0, sticky="w", pady=int(2 * self.dpr))
        box = ttk.Frame(g)
        box.grid(row=r, column=1, columnspan=2, sticky="ew", pady=int(2 * self.dpr))
        box.columnconfigure(0, weight=1)
        var = getattr(self, name)
        ttk.Entry(box, textvariable=var).grid(row=0, column=0, sticky="ew",
                                              padx=(0, int(4 * self.dpr)))
        ttk.Button(box, text="选色", width=6,
                   command=lambda v=var: self._pick_color(v)).grid(row=0, column=1)
        var.trace_add("write", lambda *_: self._on_param_changed())

    # ------------------------------------------------------------------ 事件

    def _on_align(self, prefix):
        # 注意：值存在 StringVar 里，不能直接把 self.<prefix> 换成 str ——
        # _start_build 会调 .get()，换成 str 就 AttributeError。
        cb = getattr(self, prefix + "_combo")
        getattr(self, prefix).set(ALIGN_KEYS[max(0, cb.current())])
        self._on_param_changed()

    def _on_tap_changed(self, *_a):
        self.tap_action.set(self._tap_keys[max(0, self.tap_combo.current())])

    def _on_fmt_changed(self, *_a):
        is_jpg = self._fmt_key() == "jpg"
        self.jpgq_combo.config(state="readonly" if is_jpg else "disabled")
        self._schedule_estimate()

    def _on_param_changed(self, *_a):
        self._schedule_estimate()

    def _on_aod_changed(self, *_a):
        on = self.aod_on.get()
        bg_keys = list(AOD_BG_MODES.keys())
        bg_labels = [AOD_BG_MODES[k]["label"] for k in bg_keys]
        if self.aod_bg_combo.get() in bg_labels:
            self.aod_bg.set(bg_keys[bg_labels.index(self.aod_bg_combo.get())])
        tm_keys = list(AOD_TIME_MODES.keys())
        tm_labels = [AOD_TIME_MODES[k]["label"] for k in tm_keys]
        if self.aod_tmode_combo.get() in tm_labels:
            self.aod_tmode.set(tm_keys[tm_labels.index(self.aod_tmode_combo.get())])

        # 未启用 AOD 时把整组控件灰掉，避免用户改了却以为生效
        self.aod_bg_combo.config(state="readonly" if on else "disabled")
        self.aod_tmode_combo.config(state="readonly" if on else "disabled")
        for w in (self.aod_bg_entry, self.aod_bg_btn):
            w.config(state="normal" if on else "disabled")
        self.aod_est.config(text=self._aod_estimate_text())
        self._schedule_aod_preview()
        self._schedule_estimate()

    def _on_crop_changed(self, x0, y0, x1, y1):
        if self._preview_img:
            self.crop_label.config(text=f"裁剪区域：({x0}, {y0}) → ({x1}, {y1})")
        self._schedule_estimate()

    def _schedule_aod_preview(self):
        if self._aod_job is not None:
            try:
                self.root.after_cancel(self._aod_job)
            except Exception:                        # noqa: BLE001
                pass
        self._aod_job = self.root.after(300, self._update_aod_preview)

    def _update_aod_preview(self):
        self._aod_job = None
        try:
            cfg = self._aod_cfg()
            scale = max(1, int(round(0.42 * self.dpr * 2)))   # 212 -> ~178 px 宽
            im = aod_mod.render_preview(cfg)
            im = im.resize((212 * scale // 2, 520 * scale // 2), 1)
            from PIL import ImageTk
            self._aod_photo = ImageTk.PhotoImage(im)
            self.aod_preview.config(image=self._aod_photo, text="")
        except Exception as e:                       # noqa: BLE001
            self.aod_preview.config(image="", text=f"预览不可用：{e}")

    def _schedule_estimate(self):
        if self._est_job is not None:
            try:
                self.root.after_cancel(self._est_job)
            except Exception:                        # noqa: BLE001
                pass
        self._est_job = self.root.after(250, self._update_estimate)

    # ------------------------------------------------------------------ 取值

    def _level_key(self):
        return list(COMPRESS_LEVELS.keys())[self.level_combo.current()]

    def _fmt_key(self):
        return list(ENCODE_FORMATS.keys())[self.fmt_combo.current()]

    def _fps_value(self):
        i = self.fps_combo.current()
        return None if i <= 0 else FPS_OPTIONS[i - 1]

    def _jpg_quality(self):
        return JPG_QUALITY_OPTIONS[max(0, self.jpgq_combo.current())]

    def _float(self, var, default):
        try:
            s = var.get()
            return float(s) if str(s).strip() else default
        except (tk.TclError, ValueError):
            return default

    def _int(self, var, default):
        try:
            return int(var.get())
        except (tk.TclError, ValueError):
            return default

    def _aod_cfg(self):
        return {
            "enabled": bool(self.aod_on.get()),
            "bg_mode": self.aod_bg.get() or "none",
            "bg_image": self.aod_bg_path.get().strip(),
            "time_mode": self.aod_tmode.get() or "none",
            "time_y": self._int(self.aod_time_y, 200),
            "date_y": self._int(self.aod_date_y, 300),
            "color": self.aod_color.get().strip() or "#FFFFFF",
            "font_path": self.aod_font.get().strip() or None,
        }

    def _aod_estimate_text(self):
        if not self.aod_on.get():
            return "AOD 未启用。"
        n = aod_mod.estimate_aod_bytes(self._aod_cfg())
        return f"AOD 预计增加 {n / 1024:.0f} KB。"

    # ------------------------------------------------------------------ 素材

    def _pick_source(self):
        path = filedialog.askopenfilename(
            title="选择素材",
            filetypes=[("素材", "*.gif *.mp4 *.mov *.webm *.mkv *.avi *.png *.jpg *.jpeg *.bmp *.webp"),
                       ("所有文件", "*.*")])
        if path:
            self._load_source(path)

    def _on_drop(self, event):
        raw = self.root.tk.splitlist(event.data)
        for p in raw:
            p = str(p)
            if p and os.path.isfile(p):
                self._load_source(p)
                return

    def _load_source(self, path):
        try:
            img, meta = extract_mod.extract_preview(path)
        except Exception as e:                       # noqa: BLE001
            messagebox.showwarning("无法读取素材", str(e), parent=self.root)
            return
        self._source_path = path
        self._meta = meta
        self._preview_img = img
        dur_ms = meta.get("duration_ms") or 0
        dur_txt = f"  ·  {dur_ms / 1000:.1f}s" if dur_ms else ""
        self.src_label.config(text=f"{os.path.basename(path)}\n"
                                   f"尺寸 {meta['size'][0]}x{meta['size'][1]}  ·  "
                                   f"类型 {meta['type']}{dur_txt}")
        self.canvas.set_image(img)
        self.status.config(text="已加载，请在左侧框选裁剪区域")
        self._update_estimate()
        self._ensure_room()

    # ---- 额外壁纸 ----
    def _add_wall(self):
        paths = filedialog.askopenfilenames(
            title="添加壁纸（可多选）",
            filetypes=[("素材", "*.gif *.mp4 *.mov *.webm *.mkv *.avi *.png *.jpg *.jpeg *.bmp *.webp"),
                       ("所有文件", "*.*")], parent=self.root)
        for p in paths:
            try:
                meta = extract_mod.load_source_meta(p)
            except Exception as e:                   # noqa: BLE001
                messagebox.showwarning("无法读取", f"{os.path.basename(p)}\n{e}",
                                       parent=self.root)
                continue
            self._extra_walls.append((p, crop_mod.default_crop(*meta["size"])))
        self._refresh_wall_list()
        self._schedule_estimate()

    def _remove_wall(self):
        sel = list(self.wall_list.curselection())
        for i in reversed(sel):
            if 0 <= i < len(self._extra_walls):
                self._extra_walls.pop(i)
        self._refresh_wall_list()
        self._schedule_estimate()

    def _refresh_wall_list(self):
        self.wall_list.delete(0, tk.END)
        first = os.path.basename(self._source_path) if self._source_path else "（未选择）"
        self.wall_list.insert(tk.END, f"1. {first}")
        for i, (p, _c) in enumerate(self._extra_walls):
            self.wall_list.insert(tk.END, f"{i + 2}. {os.path.basename(p)}")
        try:
            self.wall_list.itemconfig(0, foreground="#00806a")
        except Exception:                            # noqa: BLE001
            pass
        # 已经有多张壁纸、但交互还是"无"时，默认切到"轮换壁纸"（用户仍可改）
        if self._extra_walls and self.tap_action.get() == "none":
            self.tap_combo.current(self._tap_keys.index("cycle"))
            self.tap_action.set("cycle")

    # ------------------------------------------------------------------ 预估

    def _update_estimate(self):
        self._est_job = None
        if not (self._source_path and self._meta and self._preview_img):
            self.est_label.config(text="预估：—")
            return
        try:
            clip_dur = self._float(self.dur_var, 0.0) or None
            maxf = self._int(self.maxframes_var, DEFAULT_MAX_FRAMES)
            plan = extract_mod.plan_frames(
                self._meta, self._fps_value(), maxf,
                self._float(self.start_var, 0.0), clip_dur, self.speedup_var.get())
            W, H = self._meta["size"]
            cropped = crop_mod.apply_crop(self._preview_img, self.canvas.get_crop(), W, H)
            total = quantize_mod.estimate_total_bytes(
                cropped, self._level_key(), self._fmt_key(), plan.n,
                jpg_quality=self._jpg_quality())
            n_walls = 1 + len(self._extra_walls)
            aod_b = aod_mod.estimate_aod_bytes(self._aod_cfg())
            mb = (total * n_walls + aod_b) / 1048576.0
            budget = self._int(self.budget_var, DEFAULT_BUDGET_MB)

            play_s = plan.n * plan.period_ms / 1000.0 if plan.period_ms else 0.0
            note = f"预计 {plan.n} 帧 × {n_walls} 张壁纸 · 约 {mb:.2f} MB"
            if self._fmt_key() == "jpg":
                note += f"（JPEG q{self._jpg_quality()}）"
            if aod_b:
                note += f"\n其中 AOD +{aod_b / 1024:.0f} KB"
            if plan.span > 0:
                if plan.speedup:
                    mult = plan.play_fps / plan.sample_fps if plan.sample_fps else 1.0
                    note += (f"（覆盖 {plan.span:.1f}s，播放 {play_s:.1f}s"
                             f" @ {plan.play_fps:.0f}fps ≈ {mult:.1f}× 快放）")
                else:
                    note += (f"（时长 {plan.span:.1f}s @ {plan.play_fps:.1f}fps"
                             f" ≈ {play_s:.1f}s）")
            if mb > budget:
                self.est_label.config(
                    text=note + f"\n← 超出预算 {budget}MB，截短时长 / 降色深 / 减壁纸",
                    foreground="#c00000")
            else:
                self.est_label.config(text=note, foreground="#00806a")
            self._ensure_room()
        except Exception as e:                       # noqa: BLE001
            self.est_label.config(text=f"预估失败：{e}", foreground="#c00000")

    # ------------------------------------------------------------------ 选择器

    def _pick_color(self, var):
        rgb, hx = colorchooser.askcolor(color=var.get() or "#FFFFFF", parent=self.root)
        if hx:
            var.set(hx.upper())

    def _pick_aod_bg(self):
        p = filedialog.askopenfilename(
            title="选择 AOD 底图（会被缩放到 212x520）", parent=self.root,
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp"), ("所有文件", "*.*")])
        if p:
            self.aod_bg_path.set(p)
            idx = list(AOD_BG_MODES.keys()).index("custom")
            self.aod_bg_combo.current(idx)
            self._on_aod_changed()

    def _pick_aod_font(self):
        p = filedialog.askopenfilename(
            title="选择数字字体（TTF）", parent=self.root,
            filetypes=[("字体", "*.ttf *.otf"), ("所有文件", "*.*")])
        if p:
            self.aod_font.set(p)
            self._on_aod_changed()

    # ------------------------------------------------------------------ Compiler

    def _find_compiler(self):
        for c in _COMPILER_CANDIDATES:
            c = os.path.normpath(os.path.abspath(c))
            if os.path.isfile(c):
                return c
        return None

    def _pick_compiler(self):
        path = filedialog.askopenfilename(
            title="选择 Compiler.exe", parent=self.root,
            filetypes=[("Compiler.exe", "*.exe"), ("所有文件", "*.*")])
        if path:
            self._compiler = path
            self.comp_var.set(path)
            self._apply_compiler_state()

    def _apply_compiler_state(self):
        comp = self.comp_var.get().strip()
        if comp and os.path.isfile(comp):
            self._compiler = comp
            self.comp_status.config(text=f"已就绪：{_short(comp, 34)}", foreground="#008000")
        else:
            self.comp_status.config(
                text="未找到 Compiler.exe。请从 EasyFace 工具目录复制 Compiler.exe 并在上方指定路径。",
                foreground="#c00000")

    # ------------------------------------------------------------------ 窗口尺寸

    def _fit_window(self):
        self.root.update_idletasks()
        # 尺寸取「两页里更宽/更高的那个」。页面 2 在 ScrollFrame 里，其内部尺寸
        # 不会向上传播（Canvas 窗口不参与几何传播），所以这里用经验下限兜住 ——
        # 否则默认开窗偏小，一切到页面 2 就得先滚动才看得全。
        need_w = max(self.root.winfo_reqwidth(), int(1180 * self.dpr))
        need_h = max(self.root.winfo_reqheight(), int(830 * self.dpr))
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(need_w, int(sw * 0.94)), min(need_h, int(sh * 0.92))
        x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 4)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(min(int(860 * self.dpr), int(sw * 0.94)),
                          min(int(520 * self.dpr), int(sh * 0.92)))

    def _ensure_room(self):
        try:
            self.root.update_idletasks()
            need_h = self.root.winfo_reqheight()
            if need_h > self.root.winfo_height():
                sh = self.root.winfo_screenheight()
                self.root.geometry(f"{self.root.winfo_width()}x{min(need_h, int(sh * 0.95))}")
        except Exception:                            # noqa: BLE001
            pass

    def _setup_dnd(self):
        if not _HAS_DND:
            return
        try:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:                            # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 生成

    def _gen_id(self):
        import time
        return str(int(time.time()))[-8:]

    def _start_build(self):
        if not self._source_path:
            messagebox.showinfo("提示", "请先选择或拖入素材。", parent=self.root)
            self.nb.select(0)
            return
        comp = self.comp_var.get().strip()
        if not (comp and os.path.isfile(comp)):
            messagebox.showwarning("缺少 Compiler.exe",
                                   "请先在页面 1 下方指定 Compiler.exe 路径。", parent=self.root)
            self.nb.select(0)
            return
        name = self.name_var.get().strip() or "MyWatchface"
        face_id = self.id_var.get().strip() or self._gen_id()
        if not face_id.isdigit():
            messagebox.showwarning("表盘 ID 无效", "表盘 ID 必须是数字。", parent=self.root)
            return
        if self._extra_walls and self._int(self.maxframes_var, DEFAULT_MAX_FRAMES) > 60:
            if not messagebox.askyesno(
                    "多壁纸体积提醒",
                    f"当前有 {1 + len(self._extra_walls)} 张壁纸，帧数上限 "
                    f"{self._int(self.maxframes_var, DEFAULT_MAX_FRAMES)}。\n"
                    "每张壁纸都会独立占体积，容易超出预算。继续吗？",
                    parent=self.root):
                return

        params = dict(
            source_path=self._source_path,
            crop_box=self.canvas.get_crop(),
            level=self._level_key(),
            target_fps=self._fps_value(),
            face_name=name,
            face_id=face_id,
            compiler_exe=comp,
            show_time=self.show_time.get(),
            show_date=self.show_date.get(),
            time_align=self.time_align.get(),
            time_ofs=(self._int(self.time_x, 0), self._int(self.time_y, 30)),
            time_size=self._int(self.time_size, 48),
            time_color=_hex_to_int(self.time_color.get()),
            time_fmt=self.time_fmt.get().strip() or "%H:%M",
            date_align=self.date_align.get(),
            date_ofs=(self._int(self.date_x, 0), self._int(self.date_y, 86)),
            date_size=self._int(self.date_size, 16),
            date_color=_hex_to_int(self.date_color.get()),
            date_fmt=self.date_fmt.get().strip() or "%m/%d",
            tap_action=self.tap_action.get(),
            extra_walls=list(self._extra_walls),
            aod=self._aod_cfg(),
            output_dir=os.path.join(os.path.dirname(self._source_path), "watchface_out"),
            clip_start=self._float(self.start_var, 0.0),
            clip_dur=self._float(self.dur_var, 0.0) or None,
            max_frames=self._int(self.maxframes_var, DEFAULT_MAX_FRAMES),
            fmt=self._fmt_key(),
            speedup=self.speedup_var.get(),
            jpg_quality=self._jpg_quality(),
        )

        cfg = _load_config()
        cfg["compiler"] = comp
        _save_config(cfg)

        self._building = True
        self.build_btn.config(state="disabled")
        self.progress["value"] = 0
        threading.Thread(target=self._build_worker, args=(params,), daemon=True).start()

    def _build_worker(self, params):
        try:
            r = pipeline.generate_face(progress=self._on_bg_progress, **params)
            self.root.after(0, self._on_done, r)
        except Exception as e:                       # noqa: BLE001
            self.root.after(0, self._on_failed, str(e))

    def _on_bg_progress(self, frac, msg):
        self.root.after(0, self._on_progress, frac, msg)

    def _on_progress(self, frac, msg):
        if not self._building:
            return
        self.progress["value"] = int(frac * 100)
        self.status.config(text=msg)

    def _on_done(self, r):
        self._building = False
        self.build_btn.config(state="normal")
        self.progress["value"] = 100
        size_mb = r.face_size / 1048576.0
        budget = self._int(self.budget_var, DEFAULT_BUDGET_MB)
        over = "（超出预算，建议降帧率或缩短时长）" if size_mb > budget else ""
        fps_txt = f"{r.effective_fps:.1f}fps" if getattr(r, "effective_fps", 0) else "静态"
        fmt_txt = ("PNG" if getattr(r, "fmt", "png") == "png"
                   else f"JPEG q{getattr(r, 'jpg_quality', JPG_QUALITY)}")
        mult = getattr(r, "speed_mult", 1.0) or 1.0
        if mult > 1.01:
            speed_txt = (f" · 覆盖 {r.span_seconds:.1f}s 快放 {mult:.1f}×"
                         f"（播放 {r.play_seconds:.1f}s）")
        elif getattr(r, "play_seconds", 0):
            speed_txt = f" · 播放 {r.play_seconds:.1f}s"
        else:
            speed_txt = ""
        extra = []
        if getattr(r, "n_walls", 1) > 1:
            extra.append(f"{r.n_walls} 张壁纸")
        if getattr(r, "aod_enabled", False):
            extra.append(f"AOD +{r.aod_bytes / 1024:.0f} KB")
        tap = getattr(r, "tap_action", "none")
        if tap != "none":
            extra.append("交互：" + TAP_ACTIONS.get(tap, {}).get("label", tap))
        extra_txt = (" · " + " · ".join(extra)) if extra else ""

        self.status.config(
            text=f"完成：{r.n_frames} 帧 @ {fps_txt} · {r.level_label} · {fmt_txt} · "
                 f"{size_mb:.2f} MB{speed_txt}{extra_txt} {over}\n产物：{r.face_path}")
        messagebox.showinfo(
            "生成完成",
            f"表盘已生成：\n{r.face_path}\n\n"
            f"{r.n_frames} 帧 @ {fps_txt} · {r.level_label} · {fmt_txt} · "
            f"{size_mb:.2f} MB{speed_txt}{extra_txt}{over}\n"
            f"用「表盘自定义工具 / Mi Fitness」安装到手表即可。",
            parent=self.root)

    def _on_failed(self, msg):
        self._building = False
        self.build_btn.config(state="normal")
        self.status.config(text="失败")
        messagebox.showerror("生成失败", msg, parent=self.root)


def run():
    dpi = _system_dpi()
    dpr = max(1.0, dpi / 96.0)
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    _apply_scaling(root, dpi)
    try:
        ttk.Style().theme_use("vista")
    except Exception:                                # noqa: BLE001
        pass
    MainWindow(root, dpr=dpr)
    root.mainloop()
