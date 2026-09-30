# -*- coding: utf-8 -*-
"""主窗口（tkinter 版）：导入素材 → 框选 → 选压缩/帧率 → 一键生成 .face。

为什么从 PyQt5 换成 tkinter：
PyQt5 装完之后本体是 144 MB（其中 Qt5 的 DLL 和 opengl32sw.dll 占绝大部分），
而 tkinter 随 CPython 一起安装、额外占用为 0。这个工具只用到「画个位图 + 几个矩形 +
十几个标准控件」，用不着整个 Qt。换过来之后依赖从约 160 MB 降到约 16 MB（只剩 Pillow）。

移植时踩到 / 处理掉的点：
- 高 DPI：必须显式声明进程 DPI 感知，否则在 150%/200% 缩放的屏幕上整个界面是糊的
  （Qt 默认就感知，tk 不是）。见 _system_dpi() / _apply_scaling()。
- 没有 QThread：用 threading.Thread + `root.after(0, ...)` 回主线程改 UI。
  子线程里绝不要直接碰控件 —— tk 不是线程安全的。
- 没有 QTimer 的防抖：用 `root.after_cancel` + `root.after`。
- 窗口尺寸按内容自适应（tk 的控件在不同 DPI 下高度差别很大），
  避免出现"参数被窗口边缘切掉"。
"""
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from watchface_tool import crop as crop_mod
from watchface_tool import extract as extract_mod
from watchface_tool import pipeline
from watchface_tool import quantize as quantize_mod
from watchface_tool.constants import (
    COMPRESS_LEVELS, DEFAULT_BUDGET_MB, DEFAULT_FPS, DEFAULT_MAX_FRAMES,
    ENCODE_FORMATS, FPS_OPTIONS, JPG_QUALITY, JPG_QUALITY_OPTIONS,
)

from .crop_canvas import CropCanvas

CONFIG_PATH = os.path.expanduser("~/.watchface_tool.json")

_COMPILER_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "..", "assets", "Compiler.exe"),
    os.path.join(os.path.dirname(__file__), "..", "Compiler.exe"),
]

# 可选：装了 tkinterdnd2 就支持把文件拖进窗口，没装也不影响（用按钮选就行）。
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
    """让 Tk 按真实 DPI 渲染字体（点 → 像素）。"""
    try:
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:                                # noqa: BLE001
        pass


# ---------------------------------------------------------------------- 主窗口

def _short(path, limit=48):
    """路径太长就中间省略。绝对路径直接铺出来会把右栏撑得很宽。完整路径在上面的输入框里。"""
    if not path or len(path) <= limit:
        return path
    head = path[: max(8, limit // 3)]
    tail = path[-(limit - len(head) - 1):]
    return f"{head}…{tail}"


class MainWindow:
    def __init__(self, root, dpr=1.0):
        self.root = root
        self.dpr = dpr

        self._source_path = None
        self._meta = None
        self._preview_img = None
        self._est_job = None            # after() 句柄，用作防抖
        self._building = False

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

    # ------------------------------------------------------------------ 构建

    def _build_ui(self):
        pad = int(10 * self.dpr)
        main = ttk.Frame(self.root, padding=pad)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1, minsize=int(300 * self.dpr))   # 左：预览
        main.columnconfigure(1, weight=0)                                # 右：参数
        main.rowconfigure(0, weight=1)

        self._build_left(main)
        self._build_right(main)

    def _wrap(self):
        """长文本标签的折行宽度（像素）。不设的话，一个长路径标签就能把右栏撑到 1100px、
        把左边的预览挤成一条。"""
        return int(330 * self.dpr)

    def _build_left(self, parent):
        left = ttk.Frame(parent)
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

    def _build_right(self, parent):
        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        row = 0

        # ---- 1. 素材 ----
        g = ttk.LabelFrame(right, text="1. 素材", padding=int(6 * self.dpr))
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
        self.level_combo.current(1)          # balanced
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
        cb = ttk.Checkbutton(g, text="保持帧率、压缩时长（快放）", variable=self.speedup_var,
                             command=self._on_param_changed)
        cb.grid(row=r, column=0, columnspan=2, sticky="w", pady=int(2 * self.dpr))
        r += 1

        add_label("JPEG 质量", r)
        self.jpgq_combo = ttk.Combobox(g, state="readonly",
                                       values=[f"q{q}" for q in JPG_QUALITY_OPTIONS])
        self.jpgq_combo.current(JPG_QUALITY_OPTIONS.index(JPG_QUALITY))
        self.jpgq_combo.grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.jpgq_combo.bind("<<ComboboxSelected>>", self._on_param_changed)
        r += 1

        self.est_label = ttk.Label(g, text="预估：—", foreground="#00806a", justify="left",
                                   wraplength=self._wrap())
        self.est_label.grid(row=r, column=0, columnspan=2, sticky="ew",
                            pady=(int(6 * self.dpr), 0))
        r += 1

        self.time_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(g, text="叠加时间 / 日期", variable=self.time_var
                        ).grid(row=r, column=0, columnspan=2, sticky="w")
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
        ttk.Button(idrow, text="随机", width=6,
                   command=lambda: self.id_var.set(self._gen_id())
                   ).grid(row=0, column=1)
        r += 1

        add_label("体积预算", r)
        self.budget_var = tk.IntVar(value=int(DEFAULT_BUDGET_MB))
        ttk.Spinbox(g, from_=1, to=20, textvariable=self.budget_var,
                    command=self._on_param_changed
                    ).grid(row=r, column=1, sticky="ew", pady=int(2 * self.dpr))
        self.budget_var.trace_add("write", lambda *_: self._on_param_changed())
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

        # ---- 生成 ----
        self.build_btn = ttk.Button(right, text="生成 .face", command=self._start_build)
        self.build_btn.grid(row=row, column=0, sticky="ew", pady=(int(8 * self.dpr), 0))
        row += 1
        self.progress = ttk.Progressbar(right, mode="determinate", maximum=100)
        self.progress.grid(row=row, column=0, sticky="ew", pady=(int(4 * self.dpr), 0))
        row += 1
        self.status = ttk.Label(right, text="就绪", justify="left", wraplength=self._wrap())
        self.status.grid(row=row, column=0, sticky="w", pady=(int(4 * self.dpr), 0))

    def _fit_window(self):
        """按内容自适应窗口尺寸。tk 的控件高度随 DPI 变，写死会切掉参数。"""
        self.root.update_idletasks()
        need_w = max(self.root.winfo_reqwidth(), int(980 * self.dpr))
        need_h = max(self.root.winfo_reqheight(), int(600 * self.dpr))
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(need_w, int(sw * 0.92)), min(need_h, int(sh * 0.9))
        x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 3)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(min(int(700 * self.dpr), int(sw * 0.92)),
                          min(int(420 * self.dpr), int(sh * 0.9)))

    def _ensure_room(self):
        """内容变长时只把窗口**长大**、绝不缩小。

        窗口高度是在加载素材之前按空标签算的，加载后素材信息、预估行都会多出一两行，
        底部「生成 .face」按钮就可能被顶到窗口外面。这里按需补高度。
        """
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

    # ------------------------------------------------------------------ 素材

    def _pick_source(self):
        path = filedialog.askopenfilename(
            title="选择素材",
            filetypes=[("素材", "*.gif *.mp4 *.mov *.webm *.mkv *.avi *.png *.jpg *.jpeg *.bmp *.webp"),
                       ("所有文件", "*.*")])
        if path:
            self._load_source(path)

    def _on_drop(self, event):
        # tkinterdnd2 给的是形如 "{C:/a b/x.gif} C:/y.mp4" 的字符串
        raw = self.root.tk.splitlist(event.data)
        for p in raw:
            p = str(p)
            if p and os.path.isfile(p):
                self._load_source(p)
                return

    def _load_source(self, path):
        try:
            img, meta = extract_mod.extract_preview(path)
        except Exception as e:                      # noqa: BLE001
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

    # ------------------------------------------------------------------ 预估

    def _on_crop_changed(self, x0, y0, x1, y1):
        if self._preview_img:
            self.crop_label.config(text=f"裁剪区域：({x0}, {y0}) → ({x1}, {y1})")
        self._schedule_estimate()

    def _on_param_changed(self, *_args):
        self._schedule_estimate()

    def _on_fmt_changed(self, *_args):
        is_jpg = self._fmt_key() == "jpg"
        self.jpgq_combo.config(state="readonly" if is_jpg else "disabled")
        self._schedule_estimate()

    def _schedule_estimate(self):
        """防抖：拖动裁剪框时不要每次都跑量化。"""
        if self._est_job is not None:
            try:
                self.root.after_cancel(self._est_job)
            except Exception:                        # noqa: BLE001
                pass
        self._est_job = self.root.after(250, self._update_estimate)

    def _update_estimate(self):
        """用首帧真实编码字节外推整个表盘体积。帧间差异实测 <3%。"""
        self._est_job = None
        if not (self._source_path and self._meta and self._preview_img):
            self.est_label.config(text="预估：—")
            return
        try:
            clip_dur = self._float(self.dur_var, 0.0) or None
            plan = extract_mod.plan_frames(
                self._meta, self._fps_value(), self._int(self.maxframes_var, DEFAULT_MAX_FRAMES),
                self._float(self.start_var, 0.0), clip_dur, self.speedup_var.get())
            W, H = self._meta["size"]
            cropped = crop_mod.apply_crop(self._preview_img, self.canvas.get_crop(), W, H)
            total = quantize_mod.estimate_total_bytes(
                cropped, self._level_key(), self._fmt_key(), plan.n,
                jpg_quality=self._jpg_quality())
            mb = total / 1048576.0
            budget = self._int(self.budget_var, DEFAULT_BUDGET_MB)

            play_s = plan.n * plan.period_ms / 1000.0 if plan.period_ms else 0.0
            note = f"预计 {plan.n} 帧 · 约 {mb:.2f} MB"
            if self._fmt_key() == "jpg":
                note += f"（JPEG q{self._jpg_quality()}）"
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
                    text=note + f"\n← 超出预算 {budget}MB，截短时长或降色深",
                    foreground="#c00000")
            else:
                self.est_label.config(text=note, foreground="#00806a")
            self._ensure_room()
        except Exception as e:                       # noqa: BLE001
            self.est_label.config(text=f"预估失败：{e}", foreground="#c00000")

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

    # ------------------------------------------------------------------ 生成

    def _gen_id(self):
        import time
        return str(int(time.time()))[-8:]

    def _start_build(self):
        if not self._source_path:
            messagebox.showinfo("提示", "请先选择或拖入素材。", parent=self.root)
            return
        comp = self.comp_var.get().strip()
        if not (comp and os.path.isfile(comp)):
            messagebox.showwarning("缺少 Compiler.exe",
                                   "请先在下方指定 Compiler.exe 路径。", parent=self.root)
            return
        name = self.name_var.get().strip() or "MyWatchface"
        face_id = self.id_var.get().strip() or self._gen_id()
        if not face_id.isdigit():
            messagebox.showwarning("表盘 ID 无效", "表盘 ID 必须是数字。", parent=self.root)
            return

        params = dict(
            source_path=self._source_path,
            crop_box=self.canvas.get_crop(),
            level=self._level_key(),
            target_fps=self._fps_value(),
            face_name=name,
            face_id=face_id,
            compiler_exe=comp,
            show_time=self.time_var.get(),
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
        """子线程里只跑计算，UI 更新一律 root.after 回主线程。"""
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
        self.status.config(
            text=f"完成：{r.n_frames} 帧 @ {fps_txt} · {r.level_label} · {fmt_txt} · "
                 f"{size_mb:.2f} MB{speed_txt} {over}\n产物：{r.face_path}")
        messagebox.showinfo(
            "生成完成",
            f"表盘已生成：\n{r.face_path}\n\n"
            f"{r.n_frames} 帧 @ {fps_txt} · {r.level_label} · {fmt_txt} · "
            f"{size_mb:.2f} MB{speed_txt}{over}\n"
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
    if _HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    _apply_scaling(root, dpi)
    try:
        ttk.Style().theme_use("vista")
    except Exception:                                # noqa: BLE001
        pass
    MainWindow(root, dpr=dpr)
    root.mainloop()
