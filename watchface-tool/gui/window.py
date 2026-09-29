# -*- coding: utf-8 -*-
"""主窗口：导入素材 → 框选 → 选压缩/帧率 → 一键生成 .face。"""
import os
import subprocess
import sys
import time

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QProgressBar, QSpinBox, QVBoxLayout, QWidget,
)

from watchface_tool import build as build_mod
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


def _load_config():
    import json
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(cfg):
    import json
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class BuildWorker(QThread):
    progress = pyqtSignal(float, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        try:
            r = pipeline.generate_face(progress=self._emit, **self.params)
            self.done.emit(r)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))

    def _emit(self, frac, msg):
        self.progress.emit(frac, msg)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("手环 11 动态表盘制作工具")
        self.resize(980, 620)
        self.setAcceptDrops(True)

        self._source_path = None
        self._meta = None
        self._preview_img = None
        self._worker = None
        self._last_result = None

        # 体积预估防抖：拖动裁剪框时不要每次都跑量化
        self._est_timer = QTimer(self)
        self._est_timer.setSingleShot(True)
        self._est_timer.setInterval(250)
        self._est_timer.timeout.connect(self._update_estimate)

        cfg = _load_config()
        self._compiler = cfg.get("compiler") or self._find_compiler()

        self._build_ui()
        self._apply_compiler_state()
        # 初始按当前编码格式决定 JPEG 质量是否可用
        self.jpgq_combo.setEnabled(self.fmt_combo.currentData() == "jpg")

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # 左：预览画布
        left = QVBoxLayout()
        self.canvas = CropCanvas()
        self.canvas.cropChanged.connect(self._on_crop_changed)
        left.addWidget(self.canvas, 1)
        self.crop_label = QLabel("裁剪区域：未加载")
        self.crop_label.setAlignment(Qt.AlignCenter)
        left.addWidget(self.crop_label)

        left_box = QWidget()
        left_box.setLayout(left)
        root.addWidget(left_box, 3)

        # 右：参数面板
        right = QVBoxLayout()
        right.setSpacing(8)

        # 素材
        src_group = QGroupBox("1. 素材")
        g = QGridLayout(src_group)
        self.src_btn = QPushButton("选择视频 / GIF / 图片（或拖入窗口）")
        self.src_btn.clicked.connect(self._pick_source)
        g.addWidget(self.src_btn, 0, 0, 1, 2)
        self.src_label = QLabel("未选择")
        self.src_label.setWordWrap(True)
        g.addWidget(self.src_label, 1, 0, 1, 2)
        right.addWidget(src_group)

        # 压缩 + 帧率 + 时长/帧数
        param_group = QGroupBox("2. 参数（体积第一杠杆是帧数，其次才是色深）")
        g = QGridLayout(param_group)
        g.addWidget(QLabel("压缩等级"), 0, 0)
        self.level_combo = QComboBox()
        for key, cfg in COMPRESS_LEVELS.items():
            self.level_combo.addItem(cfg["label"], key)
        self.level_combo.setCurrentIndex(1)  # balanced
        self.level_combo.currentIndexChanged.connect(self._on_param_changed)
        g.addWidget(self.level_combo, 0, 1)

        g.addWidget(QLabel("编码格式"), 1, 0)
        self.fmt_combo = QComboBox()
        for key, cfg in ENCODE_FORMATS.items():
            self.fmt_combo.addItem(cfg["label"], key)
        self.fmt_combo.currentIndexChanged.connect(self._on_param_changed)
        g.addWidget(self.fmt_combo, 1, 1)

        g.addWidget(QLabel("帧率"), 2, 0)
        self.fps_combo = QComboBox()
        self.fps_combo.addItem("源素材帧率", None)
        for f in FPS_OPTIONS:
            self.fps_combo.addItem(f"{f} FPS", f)
        self.fps_combo.setCurrentIndex(FPS_OPTIONS.index(DEFAULT_FPS) + 1)
        self.fps_combo.currentIndexChanged.connect(self._on_param_changed)
        g.addWidget(self.fps_combo, 2, 1)

        g.addWidget(QLabel("截取区间"), 3, 0)
        clip_row = QHBoxLayout()
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0, 3600)
        self.start_spin.setDecimals(1)
        self.start_spin.setSingleStep(0.5)
        self.start_spin.setSuffix(" s 起")
        self.start_spin.valueChanged.connect(self._on_param_changed)
        clip_row.addWidget(self.start_spin)
        self.dur_spin = QDoubleSpinBox()
        self.dur_spin.setRange(0, 3600)
        self.dur_spin.setDecimals(1)
        self.dur_spin.setSingleStep(0.5)
        self.dur_spin.setSuffix(" s")
        self.dur_spin.setSpecialValueText("全片")
        self.dur_spin.valueChanged.connect(self._on_param_changed)
        clip_row.addWidget(self.dur_spin)
        g.addLayout(clip_row, 3, 1)

        g.addWidget(QLabel("帧数上限"), 4, 0)
        self.maxframes_spin = QSpinBox()
        self.maxframes_spin.setRange(1, 240)
        self.maxframes_spin.setValue(DEFAULT_MAX_FRAMES)
        self.maxframes_spin.setSuffix(" 帧")
        self.maxframes_spin.valueChanged.connect(self._on_param_changed)
        g.addWidget(self.maxframes_spin, 4, 1)

        self.speedup_check = QCheckBox("保持帧率、压缩时长（快放）")
        self.speedup_check.setToolTip(
            "勾选：帧率不变，把帧数上限摊到整段时长上，播放时快放 —— 流畅但变快。\n"
            "不勾：帧率自动下调以保住时长 —— 速度正常但会掉帧。\n"
            "流畅度 x 时长 x 体积是三角权衡，只能选一边牺牲。")
        self.speedup_check.stateChanged.connect(self._on_param_changed)
        g.addWidget(self.speedup_check, 5, 0, 1, 2)

        g.addWidget(QLabel("JPEG 质量"), 6, 0)
        self.jpgq_combo = QComboBox()
        for q in JPG_QUALITY_OPTIONS:
            self.jpgq_combo.addItem(f"q{q}", q)
        self.jpgq_combo.setCurrentIndex(JPG_QUALITY_OPTIONS.index(JPG_QUALITY))
        self.jpgq_combo.setToolTip(
            "仅「编码格式 = JPEG」时生效。实测 212x520 单帧（4:4:4）：\n"
            "  q90 41KB ≈ P64 PNG 41.5KB　q85 33KB　q80 28KB　q70 21KB\n"
            "q90 以上体积反超 P64 PNG，而 P64 是无损调色板，所以 80~85 最划算。\n"
            "JPEG 与 PNG 不是单纯替代：P64 PNG 平涂区有色带，JPEG 有噪点。")
        self.jpgq_combo.currentIndexChanged.connect(self._on_param_changed)
        g.addWidget(self.jpgq_combo, 6, 1)

        self.est_label = QLabel("预估：—")
        self.est_label.setWordWrap(True)
        self.est_label.setStyleSheet("color: #0a7;")
        g.addWidget(self.est_label, 7, 0, 1, 2)

        self.time_check = QCheckBox("叠加时间 / 日期")
        self.time_check.setChecked(True)
        g.addWidget(self.time_check, 8, 0, 1, 2)

        g.addWidget(QLabel("表盘名称"), 9, 0)
        self.name_edit = QLineEdit("MyWatchface")
        g.addWidget(self.name_edit, 9, 1)

        g.addWidget(QLabel("表盘 ID"), 10, 0)
        id_row = QHBoxLayout()
        self.id_edit = QLineEdit(self._gen_id())
        id_row.addWidget(self.id_edit)
        id_btn = QPushButton("随机")
        id_btn.clicked.connect(lambda: self.id_edit.setText(self._gen_id()))
        id_row.addWidget(id_btn)
        g.addLayout(id_row, 10, 1)

        g.addWidget(QLabel("体积预算 (MB)"), 11, 0)
        self.budget_spin = QSpinBox()
        self.budget_spin.setRange(1, 20)
        self.budget_spin.setValue(int(DEFAULT_BUDGET_MB))
        self.budget_spin.setSuffix(" MB")
        self.budget_spin.valueChanged.connect(self._on_param_changed)
        g.addWidget(self.budget_spin, 11, 1)
        right.addWidget(param_group)

        # 裁剪框操作
        crop_row = QHBoxLayout()
        self.reset_crop_btn = QPushButton("重置裁剪框")
        self.reset_crop_btn.clicked.connect(lambda: self.canvas.reset_crop())
        crop_row.addWidget(self.reset_crop_btn)
        self.fill_crop_btn = QPushButton("铺满画面")
        self.fill_crop_btn.clicked.connect(lambda: self.canvas.fill_crop())
        crop_row.addWidget(self.fill_crop_btn)
        right.addLayout(crop_row)

        # Compiler.exe
        comp_group = QGroupBox("3. Compiler.exe（自备，见 README）")
        g = QGridLayout(comp_group)
        self.comp_edit = QLineEdit(self._compiler or "")
        self.comp_edit.setPlaceholderText("Compiler.exe 路径")
        g.addWidget(self.comp_edit, 0, 0)
        comp_btn = QPushButton("浏览")
        comp_btn.clicked.connect(self._pick_compiler)
        g.addWidget(comp_btn, 0, 1)
        self.comp_status = QLabel("")
        self.comp_status.setWordWrap(True)
        g.addWidget(self.comp_status, 1, 0, 1, 2)
        right.addWidget(comp_group)

        # 生成
        self.build_btn = QPushButton("生成 .face")
        self.build_btn.setMinimumHeight(40)
        self.build_btn.setFont(QFont("", 12, QFont.Bold))
        self.build_btn.clicked.connect(self._start_build)
        right.addWidget(self.build_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        right.addWidget(self.progress)

        self.status = QLabel("就绪")
        self.status.setWordWrap(True)
        right.addWidget(self.status)

        right_box = QWidget()
        right_box.setLayout(right)
        root.addWidget(right_box, 2)

    # ---------- 素材 ----------
    def _pick_source(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择素材", "",
            "素材 (*.gif *.mp4 *.mov *.webm *.mkv *.avi *.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)")
        if path:
            self._load_source(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p and os.path.isfile(p):
                self._load_source(p)
                break

    def _load_source(self, path):
        try:
            img, meta = extract_mod.extract_preview(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "无法读取素材", str(e))
            return
        self._source_path = path
        self._meta = meta
        self._preview_img = img
        dur_ms = meta.get("duration_ms") or 0
        dur_txt = f"  ·  {dur_ms / 1000:.1f}s" if dur_ms else ""
        self.src_label.setText(f"{os.path.basename(path)}\n"
                               f"尺寸 {meta['size'][0]}x{meta['size'][1]}  ·  "
                               f"类型 {meta['type']}{dur_txt}")
        self.canvas.set_image(img)
        self.status.setText("已加载，请在左侧框选裁剪区域")
        self._update_estimate()

    def _on_crop_changed(self, box):
        if self._preview_img:
            self.crop_label.setText(f"裁剪区域：({box[0]}, {box[1]}) → ({box[2]}, {box[3]})")
        t = getattr(self, "_est_timer", None)
        if t is not None:
            t.start()

    def _on_param_changed(self, *args):
        self.jpgq_combo.setEnabled(self.fmt_combo.currentData() == "jpg")
        t = getattr(self, "_est_timer", None)
        if t is not None:
            t.start()

    def _update_estimate(self):
        """用首帧真实编码字节外推整个表盘体积。帧间差异实测 <3%。"""
        if getattr(self, "est_label", None) is None:
            return
        if not (self._source_path and self._meta and self._preview_img):
            self.est_label.setText("预估：—")
            return
        try:
            clip_dur = self.dur_spin.value() or None
            plan = extract_mod.plan_frames(
                self._meta, self.fps_combo.currentData(), self.maxframes_spin.value(),
                self.start_spin.value(), clip_dur, self.speedup_check.isChecked())
            W, H = self._meta["size"]
            cropped = crop_mod.apply_crop(self._preview_img, self.canvas.get_crop(), W, H)
            level = self.level_combo.currentData()
            fmt = self.fmt_combo.currentData()
            jpgq = self.jpgq_combo.currentData()
            total = quantize_mod.estimate_total_bytes(
                cropped, level, fmt, plan.n, jpg_quality=jpgq)
            mb = total / 1048576.0
            budget = self.budget_spin.value()

            play_s = plan.n * plan.period_ms / 1000.0 if plan.period_ms else 0.0
            note = f"预计 {plan.n} 帧 · 约 {mb:.2f} MB"
            if fmt == "jpg":
                note += f"（JPEG q{jpgq}）"
            if plan.span > 0:
                if plan.speedup:
                    mult = plan.play_fps / plan.sample_fps if plan.sample_fps else 1.0
                    note += (f"（覆盖 {plan.span:.1f}s，播放 {play_s:.1f}s"
                             f" @ {plan.play_fps:.0f}fps ≈ {mult:.1f}× 快放）")
                else:
                    note += (f"（时长 {plan.span:.1f}s @ {plan.play_fps:.1f}fps"
                             f" ≈ {play_s:.1f}s）")
            if mb > budget:
                self.est_label.setText(note + f"\n← 超出预算 {budget}MB，截短时长或降色深")
                self.est_label.setStyleSheet("color: #c00;")
            else:
                self.est_label.setText(note)
                self.est_label.setStyleSheet("color: #0a7;")
        except Exception as e:  # noqa: BLE001
            self.est_label.setText(f"预估失败：{e}")
            self.est_label.setStyleSheet("color: #c00;")

    # ---------- Compiler ----------
    def _find_compiler(self):
        for c in _COMPILER_CANDIDATES:
            c = os.path.normpath(os.path.abspath(c))
            if os.path.isfile(c):
                return c
        return None

    def _pick_compiler(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Compiler.exe", "", "Compiler.exe (*.exe)")
        if path:
            self._compiler = path
            self.comp_edit.setText(path)
            self._apply_compiler_state()

    def _apply_compiler_state(self):
        ok = self._compiler and os.path.isfile(self._compiler)
        if ok:
            self.comp_status.setText(f"已就绪：{self._compiler}")
            self.comp_status.setStyleSheet("color: green;")
        else:
            self.comp_status.setText(
                "未找到 Compiler.exe。请从 EasyFace 工具目录复制 Compiler.exe 并在上方指定路径。")
            self.comp_status.setStyleSheet("color: red;")

    # ---------- 生成 ----------
    def _gen_id(self):
        return str(int(time.time()))[-8:]

    def _start_build(self):
        if not self._source_path:
            QMessageBox.information(self, "提示", "请先选择或拖入素材。")
            return
        if not (self._compiler and os.path.isfile(self._compiler)):
            QMessageBox.warning(self, "缺少 Compiler.exe", "请先在下方指定 Compiler.exe 路径。")
            return
        name = self.name_edit.text().strip() or "MyWatchface"
        face_id = self.id_edit.text().strip() or self._gen_id()
        if not face_id.isdigit():
            QMessageBox.warning(self, "表盘 ID 无效", "表盘 ID 必须是数字。")
            return

        out_dir = os.path.join(os.path.dirname(self._source_path), "watchface_out")

        params = dict(
            source_path=self._source_path,
            crop_box=self.canvas.get_crop(),
            level=self.level_combo.currentData(),
            target_fps=self.fps_combo.currentData(),
            face_name=name,
            face_id=face_id,
            compiler_exe=self._compiler,
            show_time=self.time_check.isChecked(),
            output_dir=out_dir,
            clip_start=self.start_spin.value(),
            clip_dur=self.dur_spin.value() or None,
            max_frames=self.maxframes_spin.value(),
            fmt=self.fmt_combo.currentData(),
            speedup=self.speedup_check.isChecked(),
            jpg_quality=self.jpgq_combo.currentData(),
        )

        cfg = _load_config()
        cfg["compiler"] = self._compiler
        _save_config(cfg)

        self.build_btn.setEnabled(False)
        self.progress.setValue(0)
        self._worker = BuildWorker(params)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, frac, msg):
        self.progress.setValue(int(frac * 100))
        self.status.setText(msg)

    def _on_done(self, r):
        self.build_btn.setEnabled(True)
        self.progress.setValue(100)
        self._last_result = r
        size_mb = r.face_size / 1048576.0
        budget = self.budget_spin.value()
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
        self.status.setText(
            f"完成：{r.n_frames} 帧 @ {fps_txt} · {r.level_label} · {fmt_txt} · "
            f"{size_mb:.2f} MB{speed_txt} {over}\n产物：{r.face_path}")
        QMessageBox.information(
            self, "生成完成",
            f"表盘已生成：\n{r.face_path}\n\n"
            f"{r.n_frames} 帧 @ {fps_txt} · {r.level_label} · {fmt_txt} · "
            f"{size_mb:.2f} MB{speed_txt}{over}\n"
            f"用「表盘自定义工具 / Mi Fitness」安装到手表即可。")

    def _on_failed(self, msg):
        self.build_btn.setEnabled(True)
        self.status.setText("失败")
        QMessageBox.critical(self, "生成失败", msg)


def run():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
