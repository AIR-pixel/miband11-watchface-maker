package face.tool

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
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
import android.view.ViewOutlineProvider
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.Switch
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
 *   ┌ 顶部标题栏（含主题切换）        ┐
 *   │ 动态壁纸 | 功能自定义            │
 *   │ ScrollView(weight=1) 卡片式内容  │
 *   ├──────────────────────────────────┤
 *   │ 生成按钮 + 进度 + 状态           │  在 ScrollView 外面，任何屏幕都点得到
 *   └──────────────────────────────────┘
 * </pre>
 *
 * 三个改动时别踩的点：
 * 1. **生成按钮在 ScrollView 外面**，任何屏幕尺寸下都不会被挤出可视区。
 * 2. **富余高度给裁剪/AOD 预览**（基准高 + weight=1）：屏幕放得下时它把富余高度全吃掉，
 *    参数按自然高度排下来，中间不留空档；放不下时退到基准高，整页滚动。
 *    多层容器的 LayoutParams 高度必须是 WRAP_CONTENT —— 写死会把「小标题 + 控件」压扁。
 * 3. **颜色一律从 [Mat] / [Palette] 取，不许在布局里写死**。
 *    写死了就跟系统动态取色和深色模式脱钩，切换主题时会留下几块不跟着变的补丁。
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

    private lateinit var skin: Mat

    private lateinit var pages: LinearLayout
    private lateinit var pageWall: ScrollView
    private lateinit var pageFunc: ScrollView
    private lateinit var themeBtn: View
    private lateinit var tabWall: Mat.Tab
    private lateinit var tabFunc: Mat.Tab

    private lateinit var fileLabel: TextView
    private lateinit var cropLabel: TextView
    private lateinit var cropView: CropView
    private lateinit var extraBox: LinearLayout
    private lateinit var levelSpinner: MenuField
    private lateinit var fpsSpinner: MenuField
    private lateinit var fmtSpinner: MenuField
    private lateinit var jpgQSpinner: MenuField
    private lateinit var maxFrameSpinner: MenuField
    private lateinit var startEdit: EditText
    private lateinit var durEdit: EditText
    private lateinit var speedupCheck: Switch
    private lateinit var estLabel: TextView

    private lateinit var showTimeCheck: Switch
    private lateinit var timeAlignSpinner: MenuField
    private lateinit var timeSizeEdit: EditText
    private lateinit var timeXEdit: EditText
    private lateinit var timeYEdit: EditText
    private lateinit var timeColorEdit: EditText
    private lateinit var timeFmtSpinner: MenuField

    private lateinit var showDateCheck: Switch
    private lateinit var dateAlignSpinner: MenuField
    private lateinit var dateSizeEdit: EditText
    private lateinit var dateXEdit: EditText
    private lateinit var dateYEdit: EditText
    private lateinit var dateColorEdit: EditText
    private lateinit var dateFmtSpinner: MenuField

    private lateinit var tapSpinner: MenuField

    private lateinit var aodOnCheck: Switch
    private lateinit var aodBgSpinner: MenuField
    private lateinit var aodBgBtn: View
    private lateinit var aodTmSpinner: MenuField
    private lateinit var aodTimeYEdit: EditText
    private lateinit var aodDateYEdit: EditText
    private lateinit var aodColorEdit: EditText
    private lateinit var aodPrev: AodPreviewView
    private lateinit var aodEst: TextView

    private lateinit var genBtn: View
    private lateinit var progress: ProgressBar
    private lateinit var status: TextView

    private val ui = Handler(Looper.getMainLooper())
    private val estRunner = Runnable { updateEstimate() }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        skin = Mat(this)
        skin.tintWindow(window)
        buildUi()
    }

    // ---------------------------------------------------------------- 骨架

    private fun buildUi() {
        val root = skin.col().apply { setPadding(dp(14), 0, dp(14), dp(8)) }

        pages = skin.col()

        root.addView(buildAppBar(), matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
        root.addView(buildTabBar(), matchWidth(dp(48)))

        pageWall = ScrollView(this).apply { isFillViewport = true }
        pageFunc = ScrollView(this).apply { isFillViewport = true }
        buildPageWall()
        buildPageFunc()
        root.addView(pages, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        buildFooter(root)

        setContentView(root)
        selectTab(0)
    }

    private fun buildAppBar(): LinearLayout {
        val bar = skin.row().apply { gravity = Gravity.CENTER_VERTICAL }
        val titles = skin.col()
        titles.addView(TextView(this).apply {
            text = "表盘制作"
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 21f)
            typeface = skin.tfMedium
            setTextColor(skin.p.onSurface)
        })
        titles.addView(TextView(this).apply {
            text = "小米手环 11 · 212×520"
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setTextColor(skin.p.onSurfaceVariant)
        })
        bar.addView(titles, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        themeBtn = skin.button(ThemeMode.label(this), Mat.TEXT) {
            ThemeMode.next(this)
            recreate()               // 重建一次即可，配色在 onCreate 里重新解析
        }
        bar.addView(themeBtn, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        bar.setPadding(0, dp(10), 0, dp(4))
        return bar
    }

    private fun buildTabBar(): LinearLayout {
        val bar = skin.row()
        tabWall = skin.tab("动态壁纸") { selectTab(0) }
        tabFunc = skin.tab("功能自定义") { selectTab(1) }
        bar.addView(tabWall.root, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f))
        bar.addView(tabFunc.root, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f))
        return bar
    }

    private fun selectTab(i: Int) {
        pageWall.visibility = if (i == 0) View.VISIBLE else View.GONE
        pageFunc.visibility = if (i == 1) View.VISIBLE else View.GONE
        skin.selectTab(tabWall, i == 0)
        skin.selectTab(tabFunc, i == 1)
    }

    /** 页面 1：动态壁纸。 */
    private fun buildPageWall() {
        val col = skin.col().apply { setPadding(0, dp(8), 0, dp(12)) }

        // ---- 卡片：素材
        val c1 = skin.card()
        c1.addView(skin.sectionTitle("素材"))
        c1.addView(skin.button("选择视频 / 图片", Mat.TONAL) { pickFile(REQ_PICK) },
            matchWidth(dp(48)))

        fileLabel = skin.body("未选择", 12f, skin.p.onSurfaceVariant).apply {
            gravity = Gravity.CENTER
            maxLines = 2
        }
        c1.addView(fileLabel, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 10))

        cropView = CropView(this).apply {
            accent = skin.p.primary
            frameColor = skin.p.surfaceVariant
            // 圆角：靠背景 drawable 提供 outline，再把绘制裁进去
            background = skin.shape(skin.p.surfaceVariant, 14f)
            clipToOutline = true
            outlineProvider = ViewOutlineProvider.BACKGROUND
        }
        c1.addView(cropView, stretched(dp(130), 8))

        val cropRow = skin.row()
        cropRow.addView(skin.button("重置裁剪框", Mat.TEXT) { cropView.resetCrop() }, halfRow(true))
        cropRow.addView(skin.button("铺满画面", Mat.TEXT) { cropView.fillCrop() }, halfRow(false))
        c1.addView(cropRow, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 2))

        cropLabel = skin.caption("拖动移动 · 右下角拖动或双指缩放").apply { gravity = Gravity.CENTER }
        c1.addView(cropLabel, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        cropView.setOnCropChanged { x0, y0, x1, y1 ->
            cropLabel.text = "裁剪: ($x0,$y0) → ($x1,$y1)"
            scheduleEstimate()
        }
        col.addView(c1, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 10))

        // ---- 卡片：多壁纸
        val c2 = skin.card()
        c2.addView(skin.sectionTitle("多壁纸"))
        extraBox = skin.col()
        c2.addView(extraBox, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
        c2.addView(skin.button("添加一张壁纸", Mat.TEXT) { pickFile(REQ_PICK_EXTRA) },
            matchWidth(dp(40), 4))
        c2.addView(skin.caption("额外壁纸沿用同一套帧率 / 压缩 / 时长参数，裁切用「全高居中」。"),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 6))
        col.addView(c2, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 10))

        // ---- 卡片：编码参数
        val c3 = skin.card()
        c3.addView(skin.sectionTitle("编码参数"))
        buildEncodeParams(c3)
        estLabel = skin.body("预估：—", 13f, skin.p.onSurface).apply {
            typeface = skin.tfMedium
            gravity = Gravity.CENTER
        }
        c3.addView(estLabel, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 12))
        col.addView(c3, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        pageWall.addView(col, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        pages.addView(pageWall, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
    }

    /**
     * 页面 2：功能自定义。
     *
     * **只放两张卡片**（主屏 / 息屏），时间·日期·点击这三个小节用卡片内的二级标题分开 ——
     * 拆成 4 张卡片时页面会比视口高出一大截，滚动距离翻倍，反而更不「简约」。
     */
    private fun buildPageFunc() {
        val col = skin.col().apply { setPadding(0, dp(8), 0, dp(12)) }

        // ---- 卡片：主屏
        val c1 = skin.card()
        c1.addView(skin.sectionTitle("主屏 · 时间"))
        showTimeCheck = skin.switch("显示时间", true)
        c1.addView(showTimeCheck, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        val r1 = skin.row()
        timeAlignSpinner = skin.menu(ALIGN_LABELS, 1)
        r1.addView(skin.field("对齐位置", timeAlignSpinner), halfRow(true))
        timeSizeEdit = skin.edit("字号", true).apply { setText("48") }
        r1.addView(skin.field("字号", timeSizeEdit), halfRow(false))
        c1.addView(r1, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        val r2 = skin.row()
        timeXEdit = skin.edit("X", true).apply { setText("0") }
        r2.addView(skin.field("X 偏移", timeXEdit), halfRow(true))
        timeYEdit = skin.edit("Y", true).apply { setText("30") }
        r2.addView(skin.field("Y 偏移", timeYEdit), halfRow(false))
        c1.addView(r2, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        val r3 = skin.row()
        timeColorEdit = skin.edit("#FFFFFF", false)
        r3.addView(skin.field("颜色", colorRow(timeColorEdit)), halfRow(true))
        timeFmtSpinner = skin.menu(arrayOf("时:分", "时:分:秒", "12 小时制", "自定义…"), 0)
        r3.addView(skin.field("格式", timeFmtSpinner), halfRow(false))
        c1.addView(r3, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))
        wireFmtSpinner(timeFmtSpinner, timeFmtEditHolder)

        c1.addView(skin.sectionTitle("主屏 · 日期"), matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 10))
        showDateCheck = skin.switch("显示日期", false)
        c1.addView(showDateCheck, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        val r4 = skin.row()
        dateAlignSpinner = skin.menu(ALIGN_LABELS, 1)
        r4.addView(skin.field("对齐位置", dateAlignSpinner), halfRow(true))
        dateSizeEdit = skin.edit("字号", true).apply { setText("16") }
        r4.addView(skin.field("字号", dateSizeEdit), halfRow(false))
        c1.addView(r4, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        val r5 = skin.row()
        dateXEdit = skin.edit("X", true).apply { setText("0") }
        r5.addView(skin.field("X 偏移", dateXEdit), halfRow(true))
        dateYEdit = skin.edit("Y", true).apply { setText("86") }
        r5.addView(skin.field("Y 偏移", dateYEdit), halfRow(false))
        c1.addView(r5, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        val r6 = skin.row()
        dateColorEdit = skin.edit("#EEEEEE", false)
        r6.addView(skin.field("颜色", colorRow(dateColorEdit)), halfRow(true))
        dateFmtSpinner = skin.menu(arrayOf("月/日", "年/月/日", "月日中文", "仅日"), 0)
        r6.addView(skin.field("格式", dateFmtSpinner), halfRow(false))
        c1.addView(r6, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))
        wireFmtSpinner(dateFmtSpinner, dateFmtEditHolder)

        c1.addView(skin.sectionTitle("点击表盘"), matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 10))
        tapSpinner = skin.menu(TAP_LABELS, 0)
        c1.addView(skin.field("短按行为（表盘内生效）", tapSpinner),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
        c1.addView(skin.caption("跳转系统 App 做不到 —— 框架只给表盘内事件，没有对外跳转的 API，" +
            "所以这里只提供表盘内动作。"), matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))
        col.addView(c1, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 10))

        // ---- 卡片：息屏显示
        val c4 = skin.card()
        c4.addView(skin.sectionTitle("息屏显示（AOD）"))
        aodOnCheck = skin.switch("启用息屏显示", false)
        aodOnCheck.setOnCheckedChangeListener { _, _ -> onAodChanged() }
        c4.addView(aodOnCheck, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        val r7 = skin.row()
        aodBgSpinner = skin.menu(AOD_BG_LABELS, 0)
        aodBgSpinner.onSelect = { onAodChanged() }
        r7.addView(skin.field("底图", aodBgSpinner), halfRow(true))
        aodBgBtn = skin.button("选图", Mat.TEXT) { pickFile(REQ_AOD_BG) }
        r7.addView(skin.field("自定义底图", aodBgBtn), halfRow(false))
        c4.addView(r7, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 6))

        aodTmSpinner = skin.menu(AOD_TM_LABELS, 1)
        aodTmSpinner.onSelect = { onAodChanged() }
        c4.addView(skin.field("显示内容（走系统数据源，不依赖 Lua）", aodTmSpinner),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 6))

        val r8 = skin.row()
        aodTimeYEdit = skin.edit("时间行 Y", true).apply { setText("200") }
        r8.addView(skin.field("时间行 Y", aodTimeYEdit), halfRow(true))
        aodDateYEdit = skin.edit("日期行 Y", true).apply { setText("300") }
        r8.addView(skin.field("日期行 Y", aodDateYEdit), halfRow(false))
        c4.addView(r8, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 6))

        aodColorEdit = skin.edit("#FFFFFF", false)
        c4.addView(skin.field("颜色", colorRow(aodColorEdit)),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        aodPrev = AodPreviewView(this).apply {
            frameColor = skin.p.surfaceVariant
            background = skin.shape(skin.p.surfaceVariant, 14f)
            clipToOutline = true
            outlineProvider = ViewOutlineProvider.BACKGROUND
        }
        c4.addView(aodPrev, stretched(dp(170), 4))

        aodEst = skin.body("AOD 预估：—", 12.5f, skin.p.onSurfaceVariant).apply { gravity = Gravity.CENTER }
        c4.addView(aodEst, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 8))

        c4.addView(skin.caption("实测：AOD 屏不支持 Lua，时间和日期只能走系统数据源控件；" +
            "AOD 上的小图标很便宜（约 w×h×4 字节），主屏上的才会被合成为整屏位图。"),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))
        col.addView(c4, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))

        pageFunc.addView(col, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        pages.addView(pageFunc, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        onAodChanged()
    }

    /** 编码参数区：逻辑成对的占一行，行距 6dp。 */
    private fun buildEncodeParams(col: LinearLayout) {
        val row1 = skin.row()
        levelSpinner = skin.menu(LEVEL_LABELS, 1)
        row1.addView(skin.field("压缩程度", levelSpinner), halfRow(true))
        fpsSpinner = skin.menu(arrayOf("6 FPS", "8 FPS", "12 FPS", "16 FPS", "20 FPS",
            "24 FPS", "30 FPS"), 2)
        row1.addView(skin.field("帧率", fpsSpinner), halfRow(false))
        col.addView(row1, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        val row2 = skin.row()
        fmtSpinner = skin.menu(arrayOf("PNG（无损）", "JPEG（有损·更小）"), 0)
        row2.addView(skin.field("编码格式", fmtSpinner), halfRow(true))
        maxFrameSpinner = skin.menu(arrayOf("96 帧", "64 帧", "48 帧", "32 帧", "128 帧",
            "192 帧", "240 帧"), 0)
        row2.addView(skin.field("每张帧数上限", maxFrameSpinner), halfRow(false))
        col.addView(row2, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        jpgQSpinner = skin.menu(FaceGenerator.JPG_QUALITY_OPTIONS.map { "质量 $it" }.toTypedArray(), 2)
        col.addView(skin.field("JPEG 质量（仅 JPEG 生效）", jpgQSpinner),
            matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        fmtSpinner.onSelect = {
            skin.setEnabled(jpgQSpinner, fmtSpinner.selectedItemPosition == 1)
            scheduleEstimate()
        }

        val row3 = skin.row()
        startEdit = skin.edit("起始", true).apply { setText("0") }
        row3.addView(skin.field("起始（秒）", startEdit), halfRow(true))
        durEdit = skin.edit("空 = 全片", true)
        row3.addView(skin.field("时长（秒）", durEdit), halfRow(false))
        col.addView(row3, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))

        speedupCheck = skin.switch("保持帧率、压缩时长（快放）", false)
        speedupCheck.setOnCheckedChangeListener { _, _ -> scheduleEstimate() }
        col.addView(speedupCheck, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 4))
    }

    /** 下段：生成按钮 + 进度 + 状态（在 ScrollView 外面，永远点得到）。 */
    private fun buildFooter(root: LinearLayout) {
        val line = View(this).apply { setBackgroundColor(skin.p.outlineVariant) }
        root.addView(line, matchWidth(dp(1)))

        val box = skin.col().apply { setPadding(0, dp(10), 0, dp(2)) }
        genBtn = skin.button("生成表盘", Mat.FILLED) { generate() }
        box.addView(genBtn, matchWidth(dp(52)))

        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progressDrawable = skin.progressDrawable()
            minimumHeight = 0
        }
        box.addView(progress, matchWidth(dp(4), 10))

        status = skin.body("就绪", 12f, skin.p.onSurfaceVariant).apply {
            gravity = Gravity.CENTER
            setTextIsSelectable(true)
            maxLines = 3
        }
        box.addView(status, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 6))
        root.addView(box, matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
    }

    // ---------------------------------------------------------------- 控件工厂

    private fun matchWidth(h: Int, top: Int = 0) =
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, h).apply { topMargin = dp(top) }

    /** 基准高 + weight=1：屏幕有富余时把剩余高度全吸收掉。 */
    private fun stretched(baseH: Int, top: Int = 0) =
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, baseH, 1f).apply {
            topMargin = dp(top)
        }

    /**
     * 成对控件的半宽。
     * **高度必须是 WRAP_CONTENT** —— 里面是「小标题 + 控件」两层，写死高度会把两层压扁。
     */
    private fun halfRow(first: Boolean) =
        LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
            if (first) marginEnd = dp(8)
        }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    /** 颜色输入 + 「选色」按钮（框架自带 AlertDialog，不引第三方库）。 */
    private fun colorRow(edit: EditText): LinearLayout {
        val r = skin.row()
        r.addView(edit, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        r.addView(skin.button("选色") {
            AlertDialog.Builder(this).setTitle("选择颜色")
                .setItems(COLOR_PRESETS) { _, i -> edit.setText(COLOR_PRESETS[i]) }
                .setNegativeButton("取消", null).show()
        }, LinearLayout.LayoutParams(dp(64), ViewGroup.LayoutParams.WRAP_CONTENT))
        return r
    }

    // 自定义格式：下拉选「自定义…」时弹输入框，结果写进 holder
    private val timeFmtEditHolder = arrayOf("%H:%M")
    private val dateFmtEditHolder = arrayOf("%m/%d")

    private fun wireFmtSpinner(sp: MenuField, holder: Array<String>) {
        // 记录上一次的选择，避免初次回调误触发
        var last = 0
        sp.onSelect = { pos ->
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
    }

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
            extraBox.addView(skin.caption("暂无额外壁纸 —— 只有一张时「切换壁纸」不会生效。"),
                matchWidth(ViewGroup.LayoutParams.WRAP_CONTENT, 2))
            return
        }
        extraWalls.forEachIndexed { i, w ->
            val r = skin.row().apply { gravity = Gravity.CENTER_VERTICAL }
            val label = skin.body(
                String.format(Locale.US, "%d. %s%s", i + 2, w.name,
                    if (w.durationMs > 0) String.format(Locale.US, "（%.1fs）", w.durationMs / 1000.0) else ""),
                12f).apply {
                maxLines = 1
                gravity = Gravity.CENTER_VERTICAL
            }
            r.addView(label, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            r.addView(skin.button("删除", Mat.TEXT) {
                extraWalls.removeAt(i)
                renderExtraWalls()
                scheduleEstimate()
            }, LinearLayout.LayoutParams(dp(64), ViewGroup.LayoutParams.WRAP_CONTENT))
            extraBox.addView(r, matchWidth(dp(44), 2))
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

    private fun alignOf(sp: MenuField) =
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
        skin.setEnabled(aodBgBtn, on && keys == "custom")
        skin.setEnabled(aodBgSpinner, on)
        skin.setEnabled(aodTmSpinner, on)
        skin.setEnabled(aodTimeYEdit, on)
        skin.setEnabled(aodDateYEdit, on)
        skin.setEnabled(aodColorEdit, on)
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

        skin.setEnabled(genBtn, false)
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
                    skin.setEnabled(genBtn, true)
                    progress.progress = 100
                    status.text = String.format(Locale.US, "完成 %.2f MB\n%s", mb, path)
                    toast(String.format(Locale.US, "生成完成 %.2f MB", mb))
                }
            } catch (e: Exception) {
                ui.post {
                    skin.setEnabled(genBtn, true)
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
