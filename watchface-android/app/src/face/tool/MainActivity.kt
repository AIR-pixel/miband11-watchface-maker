package face.tool

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.io.FileOutputStream
import java.util.Locale

/**
 * 手环 11 动态表盘制作工具 —— 安卓端主界面。
 * 导入视频/图片 → 框选裁剪区 → 选截取区间/帧率/帧数上限/压缩/格式 → 生成 .face。
 *
 * 布局分两段：
 *   上：ScrollView（weight=1）—— 素材 + 裁剪预览 + 全部参数 + 体积预估
 *   下：固定 —— 生成按钮 + 进度 + 状态
 *
 * 两个关键点：
 * 1. **生成按钮在 ScrollView 外面**，任何屏幕尺寸下都不会被挤出可视区。
 * 2. **裁剪预览用「基准高 + weight」**：屏幕放得下时它把富余高度全部吃掉，
 *    参数就按自然高度排下来，中间不留空档；放不下时它退到基准高，整页滚动。
 *    （早先版本把预览固定成屏高 30%，富余空间全变成参数区和生成按钮之间的空档。）
 */
class MainActivity : Activity() {

    private companion object {
        const val REQ_PICK = 1
        val LEVEL_KEYS = arrayOf("high", "balanced", "small", "tiny", "micro", "nano")
        val FPS_VALUES = intArrayOf(6, 8, 12, 16, 20, 24, 30)
        val MAX_FRAME_VALUES = intArrayOf(96, 64, 48, 32, 128, 192, 240)
    }

    private var sourceUri: Uri? = null
    private var srcType = "video"
    private var srcDurationMs = 0.0

    private lateinit var fileLabel: TextView
    private lateinit var cropLabel: TextView
    private lateinit var estLabel: TextView
    private lateinit var status: TextView
    private lateinit var cropView: CropView
    private lateinit var levelSpinner: Spinner
    private lateinit var fpsSpinner: Spinner
    private lateinit var fmtSpinner: Spinner
    private lateinit var jpgQSpinner: Spinner
    private lateinit var maxFrameSpinner: Spinner
    private lateinit var startEdit: EditText
    private lateinit var durEdit: EditText
    private lateinit var speedupCheck: CheckBox
    private lateinit var genBtn: Button
    private lateinit var progress: ProgressBar

    private val ui = Handler(Looper.getMainLooper())
    private val estRunner = Runnable { updateEstimate() }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        buildUi()
    }

    // ---------------------------------------------------------------- UI

    private fun buildUi() {
        val root = LinearLayout(this)
        root.orientation = LinearLayout.VERTICAL
        root.setPadding(dp(12), dp(8), dp(12), dp(8))

        buildScrollBody(root)
        buildFooter(root)

        setContentView(root)
    }

    private fun buildScrollBody(root: LinearLayout) {
        val col = LinearLayout(this)
        col.orientation = LinearLayout.VERTICAL

        val pick = Button(this)
        pick.text = "选择视频 / 图片"
        pick.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
        pick.setOnClickListener { pickFile() }
        col.addView(pick, matchWidth(dp(48)))

        fileLabel = TextView(this)
        fileLabel.text = "未选择"
        fileLabel.gravity = Gravity.CENTER
        fileLabel.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        fileLabel.maxLines = 2
        col.addView(fileLabel, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        // 裁剪预览：基准 130dp + weight=1 —— 富余高度全归它
        cropView = CropView(this)
        cropView.setBackgroundColor(0xFF282828.toInt())
        col.addView(cropView, stretched(dp(130)))

        val cropRow = LinearLayout(this)
        cropRow.orientation = LinearLayout.HORIZONTAL
        cropRow.addView(button("重置裁剪框") { cropView.resetCrop() }, halfRow(first = true))
        cropRow.addView(button("铺满画面") { cropView.fillCrop() }, halfRow(first = false))
        col.addView(cropRow, matchWidth(dp(48)))

        cropLabel = TextView(this)
        cropLabel.text = "拖动移动 · 右下角拖动/双指缩放"
        cropLabel.gravity = Gravity.CENTER
        cropLabel.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        col.addView(cropLabel, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        cropView.setOnCropChanged { x0, y0, x1, y1 ->
            cropLabel.text = "裁剪: ($x0,$y0) → ($x1,$y1)"
            scheduleEstimate()
        }

        buildParams(col)

        val scroll = ScrollView(this)
        scroll.isFillViewport = true   // 第二趟测量给精确高度，weight 才会生效
        scroll.addView(col, ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT)
        root.addView(scroll, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
    }

    /** 参数区：逻辑成对的占一行，行距 10dp。 */
    private fun buildParams(col: LinearLayout) {
        val row1 = row()
        levelSpinner = spinner(
            arrayOf("高画质 RGB", "均衡 P256", "小体积 P128", "极限 P64", "极小 P32", "微缩 P16"), 1)
        row1.addView(captioned("压缩程度", levelSpinner), halfRow(first = true))
        fpsSpinner = spinner(
            arrayOf("6 FPS", "8 FPS", "12 FPS", "16 FPS", "20 FPS", "24 FPS", "30 FPS"), 2)
        row1.addView(captioned("帧率", fpsSpinner), halfRow(first = false))
        col.addView(row1, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, top = 12))

        val row2 = row()
        fmtSpinner = spinner(arrayOf("PNG（无损）", "JPEG（有损·更小）"), 0)
        row2.addView(captioned("编码格式", fmtSpinner), halfRow(first = true))
        maxFrameSpinner = spinner(
            arrayOf("96 帧", "64 帧", "48 帧", "32 帧", "128 帧", "192 帧", "240 帧"), 0)
        row2.addView(captioned("帧数上限", maxFrameSpinner), halfRow(first = false))
        col.addView(row2, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, top = 10))

        val qLabels = FaceGenerator.JPG_QUALITY_OPTIONS.map { "q$it" }.toTypedArray()
        jpgQSpinner = spinner(qLabels, 2)   // 默认 q80
        col.addView(captioned("JPEG 质量（仅 JPEG 生效）", jpgQSpinner),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, top = 10))

        fmtSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                jpgQSpinner.isEnabled = pos == 1
                scheduleEstimate()
            }

            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        jpgQSpinner.isEnabled = false

        val row3 = row()
        startEdit = numEdit("起始 秒").apply { setText("0") }
        row3.addView(captioned("起始（秒）", startEdit), halfRow(first = true))
        durEdit = numEdit("空=全片")
        row3.addView(captioned("时长（秒）", durEdit), halfRow(first = false))
        col.addView(row3, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, top = 10))

        speedupCheck = CheckBox(this)
        speedupCheck.text = "保持帧率、压缩时长（快放）"
        speedupCheck.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        speedupCheck.setOnCheckedChangeListener { _, _ -> scheduleEstimate() }
        col.addView(speedupCheck, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, top = 10))

        estLabel = TextView(this)
        estLabel.text = "预估：—"
        estLabel.gravity = Gravity.CENTER
        estLabel.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        col.addView(estLabel, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, top = 6))
    }

    /** 下段：生成按钮 + 进度 + 状态（在 ScrollView 外面，永远点得到）。 */
    private fun buildFooter(root: LinearLayout) {
        genBtn = Button(this)
        genBtn.text = "生成 .face"
        genBtn.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
        genBtn.setOnClickListener { generate() }
        root.addView(genBtn, matchWidth(dp(50), top = 10))

        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal)
        progress.max = 100
        root.addView(progress, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, top = 4))

        status = TextView(this)
        status.text = "就绪"
        status.gravity = Gravity.CENTER
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        status.setTextIsSelectable(true)   // 路径可以直接长按复制
        status.maxLines = 3
        root.addView(status, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
    }

    // ---------------------------------------------------------------- 控件工厂

    private fun row(): LinearLayout {
        val r = LinearLayout(this)
        r.orientation = LinearLayout.HORIZONTAL
        return r
    }

    private fun button(text: String, onClick: () -> Unit): Button {
        val b = Button(this)
        b.text = text
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        b.setOnClickListener { onClick() }
        return b
    }

    /** 给控件加一行小标题，避免「96 帧」这种下拉不知道在说什么。 */
    private fun captioned(caption: String, v: View): LinearLayout {
        val box = LinearLayout(this)
        box.orientation = LinearLayout.VERTICAL
        val label = TextView(this)
        label.text = caption
        label.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        label.setPadding(dp(2), 0, 0, dp(2))
        box.addView(label, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
        box.addView(v, matchWidth(dp(46)))
        return box
    }

    private fun spinner(items: Array<String>, def: Int): Spinner {
        val s = Spinner(this)
        val a = ArrayAdapter(this, android.R.layout.simple_spinner_item, items)
        a.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        s.adapter = a
        s.setSelection(def)
        s.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                scheduleEstimate()
            }

            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        return s
    }

    private fun numEdit(hint: String): EditText {
        val e = EditText(this)
        e.hint = hint
        e.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        e.inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
        e.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {
                scheduleEstimate()
            }

            override fun afterTextChanged(s: Editable?) {}
        })
        return e
    }

    private fun matchWidth(h: Int, top: Int = 0) =
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, h).apply {
            topMargin = dp(top)
        }

    /** 基准高 + weight=1：屏幕有富余时把剩余高度全吸收掉。 */
    private fun stretched(baseH: Int) =
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, baseH, 1f)

    /**
     * 成对控件的半宽。
     * **高度必须是 WRAP_CONTENT** —— 里面是「小标题 + 控件」两层，写死高度会把两层压扁，
     * 参数就会挤在一起（早先 dp(42) 的写法就是这个后果）。
     */
    private fun halfRow(first: Boolean) =
        LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
            if (first) marginEnd = dp(8)
        }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    // ---------------------------------------------------------------- 素材

    private fun pickFile() {
        val i = Intent(Intent.ACTION_GET_CONTENT)
        i.type = "*/*"
        i.addCategory(Intent.CATEGORY_OPENABLE)
        startActivityForResult(i, REQ_PICK)
    }

    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        val picked = data?.data
        if (req != REQ_PICK || res != RESULT_OK || picked == null) return
        sourceUri = picked
        val mime = contentResolver.getType(picked)
        srcType = if (mime != null && mime.startsWith("image/")) "image" else "video"
        val name = picked.lastPathSegment
        fileLabel.text = name
        Thread {
            val dur = if (srcType == "image") 0.0
            else FaceGenerator.probeDurationMs(this, picked, srcType)
            val bmp: Bitmap? = FaceGenerator.previewFrame(this, picked, srcType)
            ui.post {
                srcDurationMs = dur
                cropView.setBitmap(bmp)
                if (dur > 0) {
                    fileLabel.text = name + String.format(Locale.US, "\n时长 %.1fs", dur / 1000.0)
                }
                updateEstimate()
            }
        }.start()
    }

    // ---------------------------------------------------------------- 参数取值

    private fun levelOf(pos: Int) = LEVEL_KEYS[pos.coerceIn(0, LEVEL_KEYS.size - 1)]
    private fun fpsOf(pos: Int) = FPS_VALUES[pos.coerceIn(0, FPS_VALUES.size - 1)]
    private fun maxFrameOf(pos: Int) = MAX_FRAME_VALUES[pos.coerceIn(0, MAX_FRAME_VALUES.size - 1)]
    private fun fmtOf() = if (fmtSpinner.selectedItemPosition == 1) "jpg" else "png"

    private fun jpgQualityOf(): Int {
        val pos = jpgQSpinner.selectedItemPosition
            .coerceIn(0, FaceGenerator.JPG_QUALITY_OPTIONS.size - 1)
        return FaceGenerator.JPG_QUALITY_OPTIONS[pos]
    }

    private fun parseDouble(s: String?, def: Double): Double {
        if (s.isNullOrBlank()) return def
        return try {
            s.trim().toDouble()
        } catch (e: NumberFormatException) {
            def
        }
    }

    // ---------------------------------------------------------------- 预估

    private fun scheduleEstimate() {
        ui.removeCallbacks(estRunner)
        ui.postDelayed(estRunner, 250)
    }

    private fun updateEstimate() {
        val u = sourceUri
        if (u == null) {
            estLabel.text = "预估：—"
            return
        }
        val type = srcType
        val crop = cropView.getCrop()
        val level = levelOf(levelSpinner.selectedItemPosition)
        val fmt = fmtOf()
        val jpgQ = jpgQualityOf()
        val fps = fpsOf(fpsSpinner.selectedItemPosition)
        val maxFrames = maxFrameOf(maxFrameSpinner.selectedItemPosition)
        val clipStart = parseDouble(startEdit.text.toString(), 0.0)
        val clipDur = parseDouble(durEdit.text.toString(), 0.0)
        val speedup = speedupCheck.isChecked
        val dur = srcDurationMs
        Thread {
            val p = FaceGenerator.planFrames(dur, fps, clipStart, clipDur, maxFrames, speedup)
            val bytes = FaceGenerator.estimateBytes(this, u, type, crop, level, fmt, p.nFrames, jpgQ)
            ui.post {
                val extra = if (p.speedMult() > 1.01) {
                    String.format(Locale.US, " · %.1fx 快放 / 播放 %.1fs", p.speedMult(), p.playSeconds())
                } else {
                    String.format(Locale.US, " · 播放 %.1fs", p.playSeconds())
                }
                val fmtTxt = if (fmt == "png") "" else String.format(Locale.US, " · JPEG q%d", jpgQ)
                estLabel.text = String.format(Locale.US,
                    "预计 %d 帧 @ %.1ffps · 约 %.2f MB%s%s",
                    p.nFrames, p.playFps, bytes / 1048576.0, fmtTxt, extra)
            }
        }.start()
    }

    // ---------------------------------------------------------------- 生成

    private fun generate() {
        val u = sourceUri
        if (u == null) {
            toast("请先选择素材")
            return
        }
        val crop = cropView.getCrop()
        val fps = fpsOf(fpsSpinner.selectedItemPosition)
        val level = levelOf(levelSpinner.selectedItemPosition)
        val fmt = fmtOf()
        val jpgQ = jpgQualityOf()
        val maxFrames = maxFrameOf(maxFrameSpinner.selectedItemPosition)
        val clipStart = parseDouble(startEdit.text.toString(), 0.0)
        val clipDur = parseDouble(durEdit.text.toString(), 0.0)
        val speedup = speedupCheck.isChecked

        genBtn.isEnabled = false
        progress.progress = 0
        status.text = "生成中…"

        Thread {
            try {
                val faceId = (System.currentTimeMillis() / 1000).toString().take(8)
                val face = FaceGenerator.generate(this, u, srcType, crop,
                    level, fps, clipStart, clipDur, maxFrames, fmt, jpgQ, speedup,
                    "Watchface", faceId
                ) { f, m ->
                    ui.post {
                        progress.progress = (f * 100).toInt()
                        status.text = m
                    }
                }
                val path = saveFace(face, faceId)
                val mb = face.size / 1048576.0
                ui.post {
                    genBtn.isEnabled = true
                    progress.progress = 100
                    status.text = String.format(Locale.US, "完成 %.2f MB\n%s", mb, path)
                    toast(String.format(Locale.US, "生成完成 %.2f MB", mb))
                }
            } catch (e: Exception) {
                ui.post {
                    genBtn.isEnabled = true
                    status.text = "失败: ${e.message}"
                    toast("生成失败: ${e.message}")
                }
            }
        }.start()
    }

    private fun saveFace(face: ByteArray, faceId: String): String {
        val dir = File(getExternalFilesDir(null), "faces")
        dir.mkdirs()
        val f = File(dir, "watchface_$faceId.face")
        FileOutputStream(f).use { it.write(face) }
        return f.absolutePath
    }

    private fun toast(m: String) = Toast.makeText(this, m, Toast.LENGTH_SHORT).show()
}
