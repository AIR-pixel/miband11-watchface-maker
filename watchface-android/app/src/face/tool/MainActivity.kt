package face.tool

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
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
import face.AodGen

/**
 * 手环 11 动态表盘制作工具 —— 安卓端主界面（双页面）。
 *
 * <pre>
 *   ┌ 页签：动态壁纸 | 功能自定义 ┐
 *   │ ScrollView(weight=1)          │  页面内容，放不下就滚
 *   ├───────────────────────────────┤
 *   │ 生成按钮 + 进度 + 状态         │  在 ScrollView 外面，任何屏幕都点得到
 *   └───────────────────────────────┘
 * </pre>
 *
 * 两个关键点（改布局时别踩）：
 * 1. **生成按钮在 ScrollView 外面**，任何屏幕尺寸下都不会被挤出可视区。
 * 2. **富余高度给裁剪/AOD 预览**（基准高 + weight=1）：屏幕放得下时它把富余高度全吃掉，
 *    参数按自然高度排下来，中间不留空档；放不下时退到基准高，整页滚动。
 *    多层容器的 LayoutParams 高度必须是 WRAP_CONTENT —— 写死会把「小标题 + 控件」压扁。
 *
 * <p>页面 1 = 动态壁纸（素材、裁剪、帧率、压缩、多壁纸）。
 * 页面 2 = 功能自定义（主屏时间/日期元素、点击交互、息屏显示）。
 */
class MainActivity : Activity() {

    private companion object {
        const val REQ_PICK = 1
        const val REQ_PICK_EXTRA = 2
        const val REQ_AOD_BG = 3

        /**
         * 额外壁纸张数上限。真正该盯的是**总帧数**（体积的第一杠杆），
         * 但张数不设限会让人一路加下去，所以给个软上限并提示。
         */
        const val MAX_EXTRA_WALLS = 8

        val LEVEL_KEYS = arrayOf("high", "balanced", "small", "tiny", "micro", "nano")
        val LEVEL_LABELS = arrayOf("高画质 RGB", "均衡 P256", "小体积 P128", "极限 P64", "极小 P32", "微缩 P16")
        val FPS_VALUES = intArrayOf(6, 8, 12, 16, 20, 24, 30)
        val MAX_FRAME_VALUES = intArrayOf(96, 64, 48, 32, 128, 192, 240)

        val ALIGN_KEYS = arrayOf("TOP_LEFT", "TOP_MID", "TOP_RIGHT", "LEFT_MID", "CENTER",
            "RIGHT_MID", "BOTTOM_LEFT", "BOTTOM_MID", "BOTTOM_RIGHT")
        val ALIGN_LABELS = arrayOf("左上", "上中", "右上", "左中", "居中", "右中", "左下", "下中", "右下")

        val TAP_KEYS = arrayOf("none", "cycle", "info", "anim")
        val TAP_LABELS = arrayOf("无（不响应点击）", "切换壁纸（多张轮换）",
            "显示 / 隐藏时间日期", "暂停 / 继续动画")

        val AOD_BG_KEYS = arrayOf("none", "black", "custom")
        val AOD_BG_LABELS = arrayOf("无底图（最省体积）", "纯黑底图（+431 KB）", "自定义图片（+431 KB）")

        val AOD_TM_KEYS = arrayOf("none", "time", "both")
        val AOD_TM_LABELS = arrayOf("不显示", "只显示时间", "时间 + 日期")

        val TIME_FMTS = arrayOf("%H:%M", "%H:%M:%S", "%I:%M %p", "%H:%M")
        val DATE_FMTS = arrayOf("%m/%d", "%Y/%m/%d", "%m月%d日", "%d")

        val COLOR_PRESETS = arrayOf("#FFFFFF", "#EEEEEE", "#FF5A5A", "#4FC3F7",
            "#5CE1A0", "#FFC14D", "#B39DDB", "#000000")
    }

    // ---------------------------------------------------------------- 状态

    private var sourceUri: Uri? = null
    private var srcType = "video"
    private var srcDurationMs = 0.0

    private class ExtraWall(val uri: Uri, val type: String, val name: String, var durationMs: Double)

    private val extraWalls = ArrayList<ExtraWall>()
    private var aodBgUri: Uri? = null
    private var aodBgBitmap: Bitmap? = null

    // ---------------------------------------------------------------- 视图

    private lateinit var pages: LinearLayout
    private lateinit var pageWall: ScrollView
    private lateinit var pageFunc: ScrollView

    private lateinit var fileLabel: TextView
    private lateinit var cropLabel: TextView
    private lateinit var cropView: CropView
    private lateinit var extraBox: LinearLayout
    private lateinit var levelSpinner: Spinner
    private lateinit var fpsSpinner: Spinner
    private lateinit var fmtSpinner: Spinner
    private lateinit var jpgQSpinner: Spinner
    private lateinit var maxFrameSpinner: Spinner
    private lateinit var startEdit: EditText
    private lateinit var durEdit: EditText
    private lateinit var speedupCheck: CheckBox
    private lateinit var estLabel: TextView

    private lateinit var showTimeCheck: CheckBox
    private lateinit var timeAlignSpinner: Spinner
    private lateinit var timeSizeEdit: EditText
    private lateinit var timeXEdit: EditText
    private lateinit var timeYEdit: EditText
    private lateinit var timeColorEdit: EditText
    private lateinit var timeFmtSpinner: Spinner

    private lateinit var showDateCheck: CheckBox
    private lateinit var dateAlignSpinner: Spinner
    private lateinit var dateSizeEdit: EditText
    private lateinit var dateXEdit: EditText
    private lateinit var dateYEdit: EditText
    private lateinit var dateColorEdit: EditText
    private lateinit var dateFmtSpinner: Spinner

    private lateinit var tapSpinner: Spinner

    private lateinit var aodOnCheck: CheckBox
    private lateinit var aodBgSpinner: Spinner
    private lateinit var aodBgBtn: Button
    private lateinit var aodTmSpinner: Spinner
    private lateinit var aodTimeYEdit: EditText
    private lateinit var aodDateYEdit: EditText
    private lateinit var aodColorEdit: EditText
    private lateinit var aodPrev: AodPreviewView
    private lateinit var aodEst: TextView

    private lateinit var genBtn: Button
    private lateinit var progress: ProgressBar
    private lateinit var status: TextView

    private val ui = Handler(Looper.getMainLooper())
    private val estRunner = Runnable { updateEstimate() }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        buildUi()
    }

    // ---------------------------------------------------------------- 骨架

    private fun buildUi() {
        val root = LinearLayout(this)
        root.orientation = LinearLayout.VERTICAL
        root.setPadding(dp(12), dp(6), dp(12), dp(8))

        pageWall = ScrollView(this).apply { isFillViewport = true }
        pageFunc = ScrollView(this).apply { isFillViewport = true }
        pages = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        root.addView(buildTabBar(), matchWidth(dp(42)))
        buildPageWall()
        buildPageFunc()
        root.addView(pages, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        buildFooter(root)
        setContentView(root)
        selectTab(0)
    }

    private fun buildTabBar(): LinearLayout {
        val bar = row()
        val a = Button(this).apply {
            text = "① 动态壁纸"
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setOnClickListener { selectTab(0) }
        }
        val b = Button(this).apply {
            text = "② 功能自定义"
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setOnClickListener { selectTab(1) }
        }
        bar.addView(a, halfRow(first = true))
        bar.addView(b, halfRow(first = false))
        tabBtns = arrayOf(a, b)
        return bar
    }

    private var tabBtns: Array<Button>? = null

    private fun selectTab(i: Int) {
        pageWall.visibility = if (i == 0) View.VISIBLE else View.GONE
        pageFunc.visibility = if (i == 1) View.VISIBLE else View.GONE
        tabBtns?.forEachIndexed { k, b ->
            b.setBackgroundColor(if (k == i) Color.rgb(0x3D, 0x5A, 0x80) else Color.rgb(0x2A, 0x2A, 0x2E))
            b.setTextColor(if (k == i) Color.WHITE else Color.rgb(0xC0, 0xC0, 0xC6))
        }
    }

    /** 页面 1：动态壁纸。 */
    private fun buildPageWall() {
        val col = column()
        val pick = Button(this).apply {
            text = "选择视频 / 图片"
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            setOnClickListener { pickFile(REQ_PICK) }
        }
        col.addView(pick, matchWidth(dp(48)))

        fileLabel = TextView(this).apply {
            text = "未选择"
            gravity = Gravity.CENTER
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            maxLines = 2
        }
        col.addView(fileLabel, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        cropView = CropView(this).apply { setBackgroundColor(0xFF282828.toInt()) }
        col.addView(cropView, stretched(dp(120)))

        val cropRow = row()
        cropRow.addView(button("重置裁剪框") { cropView.resetCrop() }, halfRow(first = true))
        cropRow.addView(button("铺满画面") { cropView.fillCrop() }, halfRow(first = false))
        col.addView(cropRow, matchWidth(dp(48)))

        cropLabel = TextView(this).apply {
            text = "拖动移动 · 右下角拖动/双指缩放"
            gravity = Gravity.CENTER
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        }
        col.addView(cropLabel, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        cropView.setOnCropChanged { x0, y0, x1, y1 ->
            cropLabel.text = "裁剪: ($x0,$y0) → ($x1,$y1)"
            scheduleEstimate()
        }

        sectionTitle(col, "多壁纸（点击表盘可切换）")
        extraBox = column()
        col.addView(extraBox, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
        col.addView(button("＋ 添加一张壁纸") { pickFile(REQ_PICK_EXTRA) }, matchWidth(dp(42), 6))
        hint(col, "额外壁纸沿用同一套帧率/压缩/时长参数，裁切用「全高居中」。")

        sectionTitle(col, "编码参数")
        buildEncodeParams(col)

        estLabel = TextView(this).apply {
            text = "预估：—"
            gravity = Gravity.CENTER
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        }
        col.addView(estLabel, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        pageWall.addView(col, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        pages.addView(pageWall, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
    }

    /** 页面 2：功能自定义。 */
    private fun buildPageFunc() {
        val col = column()

        sectionTitle(col, "主屏 · 时间")
        showTimeCheck = cbx("显示时间", true)
        col.addView(showTimeCheck, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        val r1 = row()
        timeAlignSpinner = spinner(ALIGN_LABELS, 1)
        r1.addView(captioned("对齐位置", timeAlignSpinner), halfRow(true))
        timeSizeEdit = numEdit("48").apply { setText("48") }
        r1.addView(captioned("字号", timeSizeEdit), halfRow(false))
        col.addView(r1, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        val r2 = row()
        timeXEdit = numEdit("0").apply { setText("0") }
        r2.addView(captioned("X 偏移", timeXEdit), halfRow(true))
        timeYEdit = numEdit("30").apply { setText("30") }
        r2.addView(captioned("Y 偏移", timeYEdit), halfRow(false))
        col.addView(r2, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        val r3 = row()
        timeColorEdit = hexEdit("#FFFFFF")
        r3.addView(captioned("颜色", colorRow(timeColorEdit)), halfRow(true))
        timeFmtSpinner = spinner(arrayOf("时:分", "时:分:秒", "12 小时制", "自定义…"), 0)
        r3.addView(captioned("格式", timeFmtSpinner), halfRow(false))
        col.addView(r3, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))
        wireFmtSpinner(timeFmtSpinner, timeFmtEditHolder)

        sectionTitle(col, "主屏 · 日期")
        showDateCheck = cbx("显示日期", false)
        col.addView(showDateCheck, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        val r4 = row()
        dateAlignSpinner = spinner(ALIGN_LABELS, 1)
        r4.addView(captioned("对齐位置", dateAlignSpinner), halfRow(true))
        dateSizeEdit = numEdit("16").apply { setText("16") }
        r4.addView(captioned("字号", dateSizeEdit), halfRow(false))
        col.addView(r4, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        val r5 = row()
        dateXEdit = numEdit("0").apply { setText("0") }
        r5.addView(captioned("X 偏移", dateXEdit), halfRow(true))
        dateYEdit = numEdit("86").apply { setText("86") }
        r5.addView(captioned("Y 偏移", dateYEdit), halfRow(false))
        col.addView(r5, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        val r6 = row()
        dateColorEdit = hexEdit("#EEEEEE")
        r6.addView(captioned("颜色", colorRow(dateColorEdit)), halfRow(true))
        dateFmtSpinner = spinner(arrayOf("月/日", "年/月/日", "月日中文", "仅日"), 0)
        r6.addView(captioned("格式", dateFmtSpinner), halfRow(false))
        col.addView(r6, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))
        wireFmtSpinner(dateFmtSpinner, dateFmtEditHolder)

        sectionTitle(col, "点击表盘")
        tapSpinner = spinner(TAP_LABELS, 0)
        col.addView(captioned("短按行为（表盘内生效）", tapSpinner),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))
        hint(col, "跳转系统 App 做不到 —— 框架只给表盘内事件，没有对外跳转的 API，" +
            "所以这里只提供表盘内动作。")

        sectionTitle(col, "息屏显示（AOD）")
        aodOnCheck = cbx("启用息屏显示", false)
        aodOnCheck.setOnCheckedChangeListener { _, _ -> onAodChanged() }
        col.addView(aodOnCheck, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        val r7 = row()
        aodBgSpinner = spinner(AOD_BG_LABELS, 0)
        aodBgSpinner.onItemSelectedListener = simpleListener { onAodChanged() }
        r7.addView(captioned("底图", aodBgSpinner), halfRow(true))
        aodBgBtn = button("选图") { pickFile(REQ_AOD_BG) }
        r7.addView(captioned("自定义底图", aodBgBtn), halfRow(false))
        col.addView(r7, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        aodTmSpinner = spinner(AOD_TM_LABELS, 1)
        aodTmSpinner.onItemSelectedListener = simpleListener { onAodChanged() }
        col.addView(captioned("显示内容（走系统数据源，不依赖 Lua）", aodTmSpinner),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        val r8 = row()
        aodTimeYEdit = numEdit("200").apply { setText("200") }
        r8.addView(captioned("时间行 Y", aodTimeYEdit), halfRow(true))
        aodDateYEdit = numEdit("300").apply { setText("300") }
        r8.addView(captioned("日期行 Y", aodDateYEdit), halfRow(false))
        col.addView(r8, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        aodColorEdit = hexEdit("#FFFFFF")
        col.addView(captioned("颜色", colorRow(aodColorEdit)),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        hint(col, "实测：AOD 屏**不支持 Lua**，时间和日期只能走系统数据源控件；" +
            "AOD 上的小图标很便宜（约 w×h×4 字节），主屏上的才会被合成为整屏位图。" +
            "数字用系统字体的粗体，与 PC 端 Arial Bold 有细微差别。")

        aodPrev = AodPreviewView(this)
        col.addView(aodPrev, stretched(dp(220)))

        aodEst = TextView(this).apply {
            text = "AOD 预估：—"
            gravity = Gravity.CENTER
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        }
        col.addView(aodEst, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 6))

        pageFunc.addView(col, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        pages.addView(pageFunc, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        onAodChanged()
    }

    /** 编码参数区：逻辑成对的占一行，行距 8~12dp。 */
    private fun buildEncodeParams(col: LinearLayout) {
        val row1 = row()
        levelSpinner = spinner(LEVEL_LABELS, 1)
        row1.addView(captioned("压缩程度", levelSpinner), halfRow(true))
        fpsSpinner = spinner(arrayOf("6 FPS", "8 FPS", "12 FPS", "16 FPS", "20 FPS",
            "24 FPS", "30 FPS"), 2)
        row1.addView(captioned("帧率", fpsSpinner), halfRow(false))
        col.addView(row1, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 12))

        val row2 = row()
        fmtSpinner = spinner(arrayOf("PNG（无损）", "JPEG（有损·更小）"), 0)
        row2.addView(captioned("编码格式", fmtSpinner), halfRow(true))
        maxFrameSpinner = spinner(arrayOf("96 帧", "64 帧", "48 帧", "32 帧", "128 帧",
            "192 帧", "240 帧"), 0)
        row2.addView(captioned("每张帧数上限", maxFrameSpinner), halfRow(false))
        col.addView(row2, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        jpgQSpinner = spinner(FaceGenerator.JPG_QUALITY_OPTIONS.map { "q$it" }.toTypedArray(), 2)
        col.addView(captioned("JPEG 质量（仅 JPEG 生效）", jpgQSpinner),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))
        jpgQSpinner.isEnabled = false

        fmtSpinner.onItemSelectedListener = simpleListener {
            jpgQSpinner.isEnabled = fmtSpinner.selectedItemPosition == 1
            scheduleEstimate()
        }

        val row3 = row()
        startEdit = numEdit("起始 秒").apply { setText("0") }
        row3.addView(captioned("起始（秒）", startEdit), halfRow(true))
        durEdit = numEdit("空=全片")
        row3.addView(captioned("时长（秒）", durEdit), halfRow(false))
        col.addView(row3, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        speedupCheck = CheckBox(this).apply {
            text = "保持帧率、压缩时长（快放）"
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        }
        speedupCheck.setOnCheckedChangeListener { _, _ -> scheduleEstimate() }
        col.addView(speedupCheck, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 6))
    }

    /** 下段：生成按钮 + 进度 + 状态（在 ScrollView 外面，永远点得到）。 */
    private fun buildFooter(root: LinearLayout) {
        genBtn = Button(this).apply {
            text = "生成 .face"
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            setOnClickListener { generate() }
        }
        root.addView(genBtn, matchWidth(dp(48), 8))

        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 100 }
        root.addView(progress, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        status = TextView(this).apply {
            text = "就绪"
            gravity = Gravity.CENTER
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            setTextIsSelectable(true)
            maxLines = 3
        }
        root.addView(status, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
    }

    // ---------------------------------------------------------------- 控件工厂

    private fun row(): LinearLayout = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }

    private fun column(): LinearLayout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

    private fun button(text: String, onClick: () -> Unit): Button = Button(this).apply {
        this.text = text
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        setOnClickListener { onClick() }
    }

    private fun cbx(text: String, on: Boolean): CheckBox = CheckBox(this).apply {
        this.text = text
        isChecked = on
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
    }

    private fun sectionTitle(col: LinearLayout, t: String) {
        val v = TextView(this).apply {
            text = t
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setTextColor(Color.rgb(0x7F, 0xB0, 0xE0))
        }
        col.addView(v, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 12))
    }

    private fun hint(col: LinearLayout, t: String) {
        val v = TextView(this).apply {
            text = t
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            setTextColor(Color.rgb(0x9A, 0x9A, 0xA2))
            setLineSpacing(0f, 1.15f)
        }
        col.addView(v, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))
    }

    /** 给控件加一行小标题，避免「96 帧」这种下拉不知道在说什么。 */
    private fun captioned(caption: String, v: View): LinearLayout {
        val box = column()
        val label = TextView(this).apply {
            text = caption
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            setPadding(dp(2), 0, 0, dp(2))
            maxLines = 2
        }
        box.addView(label, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
        box.addView(v, matchWidth(dp(46)))
        return box
    }

    private fun spinner(items: Array<String>, def: Int): Spinner = Spinner(this).apply {
        adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_item, items)
            .apply { setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
        setSelection(def)
        onItemSelectedListener = simpleListener { scheduleEstimate() }
    }

    private fun simpleListener(after: () -> Unit) = object : AdapterView.OnItemSelectedListener {
        override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) = after()
        override fun onNothingSelected(p: AdapterView<*>?) {}
    }

    private fun numEdit(hint: String): EditText = EditText(this).apply {
        this.hint = hint
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
        addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) = scheduleEstimate()
            override fun afterTextChanged(s: Editable?) {}
        })
    }

    private fun hexEdit(def: String): EditText = EditText(this).apply {
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS
        setText(def)                       // 先赋值再加监听，避免构造期回调打到自己
        addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) = scheduleEstimate()
            override fun afterTextChanged(s: Editable?) {}
        })
    }

    /** 颜色输入 + 「选色」按钮（框架自带 AlertDialog，不引第三方库）。 */
    private fun colorRow(edit: EditText): LinearLayout {
        val r = row()
        r.addView(edit, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        r.addView(button("选色") {
            AlertDialog.Builder(this).setTitle("选择颜色")
                .setItems(COLOR_PRESETS) { _, i -> edit.setText(COLOR_PRESETS[i]) }
                .setNegativeButton("取消", null).show()
        }, LinearLayout.LayoutParams(dp(58), ViewGroup.LayoutParams.WRAP_CONTENT))
        return r
    }

    // 自定义格式：下拉选「自定义…」时弹输入框，结果写进 holder
    private val timeFmtEditHolder = arrayOf("%H:%M")
    private val dateFmtEditHolder = arrayOf("%m/%d")

    private fun wireFmtSpinner(sp: Spinner, holder: Array<String>) {
        // 记录上一次的选择，避免 onItemSelected 初始回调误触发
        var last = 0
        sp.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                val presets = if (holder === timeFmtEditHolder) TIME_FMTS else DATE_FMTS
                if (pos < presets.size) {
                    holder[0] = presets[pos]
                } else {
                    val e = EditText(this@MainActivity).apply {
                        setText(holder[0]); setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
                        inputType = InputType.TYPE_CLASS_TEXT
                    }
                    AlertDialog.Builder(this@MainActivity)
                        .setTitle("自定义 strftime 格式（如 %H:%M）")
                        .setView(e)
                        .setPositiveButton("确定") { _, _ ->
                            holder[0] = e.text.toString().ifBlank { presets[0] }
                            scheduleEstimate()
                        }
                        .setNegativeButton("取消") { _, _ -> sp.setSelection(last) }
                        .show()
                }
                last = pos
                scheduleEstimate()
            }

            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
    }

    private fun matchWidth(h: Int, top: Int = 0) =
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, h).apply { topMargin = dp(top) }

    /** 基准高 + weight=1：屏幕有富余时把剩余高度全吸收掉。 */
    private fun stretched(baseH: Int) =
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, baseH, 1f)

    /**
     * 成对控件的半宽。
     * **高度必须是 WRAP_CONTENT** —— 里面是「小标题 + 控件」两层，写死高度会把两层压扁。
     */
    private fun halfRow(first: Boolean) =
        LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
            if (first) marginEnd = dp(8)
        }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    // ---------------------------------------------------------------- 素材

    private fun pickFile(req: Int) {
        val i = Intent(Intent.ACTION_GET_CONTENT)
        i.type = if (req == REQ_AOD_BG) "image/*" else "*/*"
        i.addCategory(Intent.CATEGORY_OPENABLE)
        startActivityForResult(i, req)
    }

    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        val picked = data?.data
        if (res != RESULT_OK || picked == null) return
        val mime = contentResolver.getType(picked)
        val type = if (mime != null && mime.startsWith("image/")) "image" else "video"

        when (req) {
            REQ_PICK -> {
                sourceUri = picked
                srcType = type
                val name = picked.lastPathSegment ?: "已选素材"
                fileLabel.text = name
                Thread {
                    val dur = if (type == "image") 0.0
                              else FaceGenerator.probeDurationMs(this, picked, type)
                    val bmp: Bitmap? = FaceGenerator.previewFrame(this, picked, type)
                    ui.post {
                        srcDurationMs = dur
                        cropView.setBitmap(bmp)
                        if (dur > 0) fileLabel.text =
                            name + String.format(Locale.US, "\n时长 %.1fs", dur / 1000.0)
                        scheduleEstimate()
                    }
                }.start()
            }
            REQ_PICK_EXTRA -> {
                if (extraWalls.size >= MAX_EXTRA_WALLS) {
                    toast("最多 $MAX_EXTRA_WALLS 张额外壁纸 —— 帧数总量才是体积的第一杠杆")
                    return
                }
                val name = picked.lastPathSegment ?: ("壁纸 " + (extraWalls.size + 2))
                val w = ExtraWall(picked, type, name, 0.0)
                extraWalls.add(w)
                renderExtraWalls()
                Thread {
                    w.durationMs = if (type == "image") 0.0
                                   else FaceGenerator.probeDurationMs(this, picked, type)
                    ui.post {
                        renderExtraWalls()
                        scheduleEstimate()
                    }
                }.start()
            }
            REQ_AOD_BG -> {
                aodBgUri = picked
                Thread {
                    val bmp = try {
                        contentResolver.openInputStream(picked)?.use { BitmapFactory.decodeStream(it) }
                    } catch (e: Exception) { null }
                    ui.post {
                        aodBgBitmap = bmp
                        if (aodBgSpinner.selectedItemPosition != 2) aodBgSpinner.setSelection(2)
                        onAodChanged()
                    }
                }.start()
            }
        }
    }

    private fun renderExtraWalls() {
        extraBox.removeAllViews()
        if (extraWalls.isEmpty()) {
            hint(extraBox, "暂无额外壁纸 —— 只有一张时「切换壁纸」不会生效。")
            return
        }
        extraWalls.forEachIndexed { i, w ->
            val r = row()
            val label = TextView(this).apply {
                text = String.format(Locale.US, "%d. %s%s", i + 2, w.name,
                    if (w.durationMs > 0) String.format(Locale.US, "（%.1fs）", w.durationMs / 1000.0) else "")
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
                maxLines = 1
                gravity = Gravity.CENTER_VERTICAL
            }
            r.addView(label, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            r.addView(button("删除") {
                extraWalls.removeAt(i)
                renderExtraWalls()
                scheduleEstimate()
            }, LinearLayout.LayoutParams(dp(62), ViewGroup.LayoutParams.WRAP_CONTENT))
            extraBox.addView(r, matchWidth(dp(40), 4))
        }
    }

    // ---------------------------------------------------------------- 参数取值

    private fun levelOf() = LEVEL_KEYS[levelSpinner.selectedItemPosition.coerceIn(0, LEVEL_KEYS.size - 1)]
    private fun fpsOf() = FPS_VALUES[fpsSpinner.selectedItemPosition.coerceIn(0, FPS_VALUES.size - 1)]

    private fun maxFrameOf() =
        MAX_FRAME_VALUES[maxFrameSpinner.selectedItemPosition.coerceIn(0, MAX_FRAME_VALUES.size - 1)]

    private fun fmtOf() = if (fmtSpinner.selectedItemPosition == 1) "jpg" else "png"

    private fun jpgQualityOf(): Int = FaceGenerator.JPG_QUALITY_OPTIONS[
        jpgQSpinner.selectedItemPosition.coerceIn(0, FaceGenerator.JPG_QUALITY_OPTIONS.size - 1)]

    private fun alignOf(sp: Spinner) =
        ALIGN_KEYS[sp.selectedItemPosition.coerceIn(0, ALIGN_KEYS.size - 1)]

    private fun iOf(e: EditText, def: Int) = e.text.toString().trim().toIntOrNull() ?: def

    private fun dOf(e: EditText, def: Double) =
        e.text.toString().trim().toDoubleOrNull() ?: def

    private fun hexOf(e: EditText): String = e.text.toString().trim().ifBlank { "#FFFFFF" }

    /** '#RRGGBB' → 0xRRGGBB（非法则白色）。 */
    private fun colorInt(s: String): Int {
        val c = AodGen.parseColor(s)
        return (c[0] shl 16) or (c[1] shl 8) or c[2]
    }

    private fun aodCfg(): AodGen.Cfg = AodGen.Cfg().apply {
        enabled = aodOnCheck.isChecked
        bgMode = AOD_BG_KEYS[aodBgSpinner.selectedItemPosition.coerceIn(0, AOD_BG_KEYS.size - 1)]
        timeMode = AOD_TM_KEYS[aodTmSpinner.selectedItemPosition.coerceIn(0, AOD_TM_KEYS.size - 1)]
        timeY = iOf(aodTimeYEdit, 200)
        dateY = iOf(aodDateYEdit, 300)
        color = hexOf(aodColorEdit)
        hasCustomBg = aodBgBitmap != null
    }

    private fun onAodChanged() {
        val on = aodOnCheck.isChecked
        val keys = AOD_BG_KEYS[aodBgSpinner.selectedItemPosition.coerceIn(0, AOD_BG_KEYS.size - 1)]
        aodBgBtn.isEnabled = on && keys == "custom"
        aodBgSpinner.isEnabled = on
        aodTmSpinner.isEnabled = on
        aodTimeYEdit.isEnabled = on
        aodDateYEdit.isEnabled = on
        aodColorEdit.isEnabled = on
        scheduleEstimate()
    }

    // ---------------------------------------------------------------- 预估

    private fun scheduleEstimate() {
        ui.removeCallbacks(estRunner)
        ui.postDelayed(estRunner, 250)
    }

    private fun updateEstimate() {
        // 界面还没建完时（下拉在构造期就会回调一次）直接跳过，250ms 后自然会再跑
        if (!::aodEst.isInitialized || !::estLabel.isInitialized) return

        // AOD 预估（不需要素材，主线程算）+ 刷新息屏预览
        val cfg = aodCfg()
        aodPrev.colorHex = hexOf(aodColorEdit)
        aodPrev.bgBitmap = aodBgBitmap
        aodPrev.cfg = cfg
        val aodBytes = AodGen.estimateBytes(cfg)
        val tmLabel = AOD_TM_LABELS[
            aodTmSpinner.selectedItemPosition.coerceIn(0, AOD_TM_LABELS.size - 1)]
        aodEst.text = if (!cfg.enabled) "AOD 预估：未启用"
        else String.format(Locale.US, "AOD 预估：约 %.0f KB（%s）", aodBytes / 1024.0, tmLabel)

        val u = sourceUri
        if (u == null) {
            estLabel.text = "预估：—"
            return
        }
        val type = srcType
        val crop = cropView.getCrop()
        val level = levelOf()
        val fmt = fmtOf()
        val jpgQ = jpgQualityOf()
        val fps = fpsOf()
        val maxFrames = maxFrameOf()
        val clipStart = dOf(startEdit, 0.0)
        val clipDur = dOf(durEdit, 0.0)
        val speedup = speedupCheck.isChecked
        val dur = srcDurationMs
        val extras = extraWalls.map { Triple(it.uri, it.type, it.durationMs) }

        Thread {
            val p0 = FaceGenerator.planFrames(dur, fps, clipStart, clipDur, maxFrames, speedup)
            var bytes = FaceGenerator.estimateWallBytes(this, u, type, crop, level, fmt, p0.nFrames, jpgQ)
            var frames = p0.nFrames
            var playSec = p0.playSeconds()
            for ((eu, et, ed) in extras) {
                val pi = FaceGenerator.planFrames(ed, fps, clipStart, clipDur, maxFrames, speedup)
                bytes += FaceGenerator.estimateWallBytes(this, eu, et, null, level, fmt, pi.nFrames, jpgQ)
                frames += pi.nFrames
                playSec += pi.playSeconds()
            }
            val aod = AodGen.estimateBytes(cfg)
            val total = bytes + FaceGenerator.HEADER_OVERHEAD + aod
            ui.post {
                val nWalls = 1 + extras.size
                val extra = if (p0.speedMult() > 1.01)
                    String.format(Locale.US, " · %.1fx 快放", p0.speedMult()) else ""
                val fmtTxt = if (fmt == "png") "" else String.format(Locale.US, " · JPEG q%d", jpgQ)
                val aodTxt = if (cfg.enabled) String.format(Locale.US, " · AOD %.0fKB", aod / 1024.0) else ""
                estLabel.text = String.format(Locale.US,
                    "%d 张 / 共 %d 帧 · 约 %.2f MB%s%s%s（含固定开销 431KB）",
                    nWalls, frames, total / 1048576.0, fmtTxt, extra, aodTxt)
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
        val o = FaceGenerator.Opts()
        FaceGenerator.WallSpec(u, srcType).let {
            it.crop = cropView.getCrop()
            it.fps = fpsOf()
            it.maxFrames = maxFrameOf()
            it.clipStart = dOf(startEdit, 0.0)
            it.clipDur = dOf(durEdit, 0.0)
            it.speedup = speedupCheck.isChecked
            o.walls.add(it)
        }
        for (w in extraWalls) {
            FaceGenerator.WallSpec(w.uri, w.type).let {
                it.crop = null                       // 额外壁纸走全高居中
                it.fps = fpsOf()
                it.maxFrames = maxFrameOf()
                it.clipStart = dOf(startEdit, 0.0)
                it.clipDur = dOf(durEdit, 0.0)
                it.speedup = speedupCheck.isChecked
                o.walls.add(it)
            }
        }
        o.level = levelOf()
        o.fmt = fmtOf()
        o.jpgQuality = jpgQualityOf()
        o.title = "Watchface"
        o.faceId = null

        with(o.lua) {
            showTime = showTimeCheck.isChecked
            showDate = showDateCheck.isChecked
            timeAlign = alignOf(timeAlignSpinner)
            timeX = iOf(timeXEdit, 0); timeY = iOf(timeYEdit, 30)
            timeSize = iOf(timeSizeEdit, 48); timeColor = colorInt(hexOf(timeColorEdit))
            timeFmt = timeFmtEditHolder[0]
            dateAlign = alignOf(dateAlignSpinner)
            dateX = iOf(dateXEdit, 0); dateY = iOf(dateYEdit, 86)
            dateSize = iOf(dateSizeEdit, 16); dateColor = colorInt(hexOf(dateColorEdit))
            dateFmt = dateFmtEditHolder[0]
            tapAction = TAP_KEYS[tapSpinner.selectedItemPosition.coerceIn(0, TAP_KEYS.size - 1)]
        }
        o.aod = aodCfg()
        o.aodBg = aodBgBitmap

        genBtn.isEnabled = false
        progress.progress = 0
        status.text = "生成中…"

        Thread {
            try {
                val faceId = (System.currentTimeMillis() / 1000).toString().take(8)
                o.faceId = faceId
                val face = FaceGenerator.generate(this, o) { f, m ->
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
