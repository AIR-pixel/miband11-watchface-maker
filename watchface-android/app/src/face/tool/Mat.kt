package face.tool

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ClipDrawable
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.LayerDrawable
import android.graphics.drawable.RippleDrawable
import android.os.Build
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.WindowInsetsController
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ListPopupWindow
import android.widget.Switch
import android.widget.TextView

/**
 * Material 3 风格控件工厂 —— **纯 framework，无 AndroidX、无 res 目录**。
 *
 * 全部用代码画：圆角靠 [GradientDrawable]，按压反馈靠 [RippleDrawable]，
 * 下拉菜单用 [ListPopupWindow]（framework 自带，比 Spinner 的旧式箭头干净得多）。
 *
 * 约束（改这个文件前先看）：
 * - 项目走的是免 Gradle 手工构建链，**没有资源系统**，所以凡是 XML 才能给的东西
 *   （theme attribute、selector xml）都得在代码里等价实现。
 * - minSdk 24，凡是 API 23+ 的 tint 接口都能直接用；只有 API 29/30 的几个
 *   （textCursorDrawable、insetsController）要判 SDK_INT。
 * - **不要引入任何第三方库**：R8 能把 kotlin-stdlib 整棵摇掉的前提是纯 framework + 零反射。
 */
class Mat(private val ctx: Context) {

    val p: Palette = Palette.of(ctx)

    companion object {
        const val FILLED = 0
        const val TONAL = 1
        const val OUTLINED = 2
        const val TEXT = 3
    }

    private val dm = ctx.resources.displayMetrics
    val tfMedium = Typeface.create("sans-serif-medium", Typeface.NORMAL)
    val tfRegular = Typeface.create("sans-serif", Typeface.NORMAL)

    fun dp(v: Float): Int = (v * dm.density).toInt()

    /** M3 的 state layer：内容色叠加 12%（深色下略高一点）。 */
    private fun stateTint(c: Int) =
        Color.argb(if (p.night) 40 else 32, Color.red(c), Color.green(c), Color.blue(c))

    // ---------------------------------------------------------------- 形状

    fun shape(color: Int, rDp: Float, stroke: Int? = null, swDp: Float = 1f): GradientDrawable =
        GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(rDp).toFloat()
            if (stroke != null) setStroke(dp(swDp), stroke)
        }

    /** 水波纹。mask 传白色圆角（RippleDrawable 的 mask 只看 alpha）。 */
    fun ripple(content: Drawable?, tintColor: Int, rDp: Float): Drawable =
        RippleDrawable(ColorStateList.valueOf(stateTint(tintColor)),
            content, shape(0xFFFFFFFF.toInt(), rDp))

    // ---------------------------------------------------------------- 按钮

    fun button(text: String, kind: Int = FILLED, onClick: () -> Unit): Button = Button(ctx).apply {
        this.text = text
        isAllCaps = false
        typeface = tfMedium
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        gravity = Gravity.CENTER
        // 框架 Button 自带 elevation 动画（矩形阴影），会把圆角背景露成方的
        stateListAnimator = null
        minimumHeight = dp(if (kind == TEXT) 40f else 48f)
        setPadding(dp(18f), 0, dp(18f), 0)

        when (kind) {
            TONAL -> {
                background = ripple(shape(p.secondaryContainer, 20f), p.onSecondaryContainer, 20f)
                setTextColor(p.onSecondaryContainer)
            }
            OUTLINED -> {
                background = ripple(shape(Color.TRANSPARENT, 20f, p.outline), p.primary, 20f)
                setTextColor(p.primary)
            }
            TEXT -> {
                background = ripple(null, p.primary, 20f)
                setTextColor(p.primary)
            }
            else -> {
                background = ripple(shape(p.primary, 20f), p.onPrimary, 20f)
                setTextColor(p.onPrimary)
            }
        }
        setOnClickListener { onClick() }
    }

    // ---------------------------------------------------------------- 容器

    fun card(): LinearLayout = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        background = shape(p.surfaceContainer, 16f)
        setPadding(dp(12f), dp(10f), dp(12f), dp(12f))
    }

    fun row(): LinearLayout = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }

    fun col(): LinearLayout = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }

    // ---------------------------------------------------------------- 文字

    fun sectionTitle(t: String): TextView = TextView(ctx).apply {
        text = t
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        typeface = tfMedium
        setTextColor(p.primary)
        setPadding(dp(2f), 0, 0, dp(8f))
    }

    fun body(t: String, sizeSp: Float = 13f, color: Int = p.onSurface): TextView = TextView(ctx).apply {
        text = t
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp)
        typeface = tfRegular
        setTextColor(color)
        setLineSpacing(0f, 1.25f)
    }

    fun caption(t: String): TextView = TextView(ctx).apply {
        text = t
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
        typeface = tfRegular
        setTextColor(p.onSurfaceVariant)
        setLineSpacing(0f, 1.3f)
    }

    /** 小标题 + 控件（成对控件半宽排列时用）。 */
    fun field(label: String, v: View): LinearLayout = col().apply {
        addView(TextView(ctx).apply {
            text = label
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            typeface = tfRegular
            setTextColor(p.onSurfaceVariant)
            setPadding(dp(2f), 0, 0, dp(4f))
        }, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        addView(v, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
    }

    // ---------------------------------------------------------------- 输入

    fun edit(hint: String, numeric: Boolean): EditText = EditText(ctx).apply {
        this.hint = hint
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        typeface = tfRegular
        setTextColor(p.onSurface)
        setHintTextColor(p.onSurfaceVariant)
        setHighlightColor(p.primaryContainer)
        inputType = if (numeric)
            InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
        else
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS
        if (Build.VERSION.SDK_INT >= 29) textCursorDrawable = ColorDrawable(p.primary)
        background = shape(p.surfaceContainerHighest, 8f)
        setPad(this)
        // M3 filled text field：聚焦时描边变主色
        setOnFocusChangeListener { _, has ->
            background = shape(p.surfaceContainerHighest, 8f, if (has) p.primary else null, 2f)
            setPad(this)
        }
        minHeight = dp(48f)
    }

    private fun setPad(e: EditText) = e.setPadding(dp(12f), dp(12f), dp(12f), dp(12f))

    fun menu(items: Array<String>, def: Int, onChange: ((Int) -> Unit)? = null): MenuField =
        MenuField(ctx, this, items, def).apply { onSelect = onChange }

    fun switch(text: String, on: Boolean): Switch = Switch(ctx).apply {
        this.text = text
        isChecked = on
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        typeface = tfRegular
        setTextColor(p.onSurface)
        setPadding(0, dp(4f), 0, dp(4f))
        thumbTintList = ColorStateList(
            arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()),
            intArrayOf(p.onPrimary, p.outline))
        trackTintList = ColorStateList(
            arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()),
            intArrayOf(p.primary, p.surfaceVariant))
    }

    // ---------------------------------------------------------------- 其它

    /** M3：禁用态 = 38% 不透明度（不是换灰底）。 */
    fun setEnabled(v: View, on: Boolean) {
        v.isEnabled = on
        v.alpha = if (on) 1f else 0.38f
    }

    /** M3 线性进度条：4dp 圆角轨道，不是框架默认的矩形条。 */
    @Suppress("DEPRECATION")
    fun progressDrawable(): LayerDrawable {
        val clip = ClipDrawable(shape(p.primary, 2f), Gravity.START, ClipDrawable.HORIZONTAL)
        val ld = LayerDrawable(arrayOf<Drawable>(shape(p.surfaceVariant, 2f), clip))
        ld.setId(0, android.R.id.background)
        ld.setId(1, android.R.id.progress)
        return ld
    }

    /** 把窗口底色/状态栏/导航栏都并到当前配色上，否则切深色时四周会留一圈白边。 */
    fun tintWindow(w: Window) {
        w.setBackgroundDrawable(ColorDrawable(p.surface))
        w.statusBarColor = p.surface
        w.navigationBarColor = p.surface
        if (!p.night) {
            if (Build.VERSION.SDK_INT >= 30) {
                w.insetsController?.setSystemBarsAppearance(
                    WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                        WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
                    WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                        WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS)
            } else {
                @Suppress("DEPRECATION")
                w.decorView.systemUiVisibility = w.decorView.systemUiVisibility or
                    View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
            }
        }
    }

    // ---------------------------------------------------------------- Tab

    data class Tab(val root: LinearLayout, val label: TextView, val indicator: View)

    fun tab(label: String, onClick: () -> Unit): Tab {
        val root = col().apply {
            gravity = Gravity.CENTER_HORIZONTAL
            setOnClickListener { onClick() }
        }
        val tv = TextView(ctx).apply {
            text = label
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            typeface = tfMedium
            gravity = Gravity.CENTER
        }
        val ind = View(ctx).apply { background = shape(Color.TRANSPARENT, 1.5f) }
        root.addView(tv, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, 0, 1f).apply { gravity = Gravity.CENTER })
        root.addView(ind, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(3f)).apply {
            marginStart = dp(16f); marginEnd = dp(16f) })
        return Tab(root, tv, ind)
    }

    fun selectTab(t: Tab, on: Boolean) {
        t.label.setTextColor(if (on) p.primary else p.onSurfaceVariant)
        t.label.typeface = if (on) tfMedium else tfRegular
        t.indicator.background = shape(if (on) p.primary else Color.TRANSPARENT, 1.5f)
    }
}

/**
 * M3「Exposed dropdown menu」—— 替换 Spinner。
 *
 * 为什么不用 Spinner：框架 Spinner 的箭头和底划线是 API 21 时代的老样式，
 * 改不掉（要改就得引 AppCompat），而 [ListPopupWindow] 是 framework 自带的，
 * 配一个圆角浮层就是 M3 的菜单。
 *
 * 为了少动调用方，保留了 Spinner 的两个习惯用法：
 * [selectedItemPosition] 读写、[setSelection]；
 * 回调换成 [onSelect]（Spinner 的 listener 需要在构造期就吃掉一次回调，容易误触发，
 * 这里改成只在用户真正点选时触发）。
 */
class MenuField(
    ctx: Context,
    private val mat: Mat,
    items: Array<String>,
    def: Int
) : TextView(ctx) {

    var items: Array<String> = items
        set(v) {
            field = v
            index = index.coerceIn(0, v.lastIndex)
            render()
        }

    var index: Int = def.coerceIn(0, items.lastIndex)
        set(v) {
            val n = v.coerceIn(0, items.lastIndex)
            field = n
            render()
        }

    /** 用户点选后触发（构造/代码赋值都不触发）。 */
    var onSelect: ((Int) -> Unit)? = null

    var selectedItemPosition: Int
        get() = index
        set(v) { index = v }

    fun setSelection(i: Int) { index = i }

    init {
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        typeface = Typeface.create("sans-serif", Typeface.NORMAL)
        gravity = Gravity.CENTER_VERTICAL or Gravity.START
        setPadding(mat.dp(12f), 0, mat.dp(12f), 0)
        minHeight = mat.dp(48f)
        background = mat.ripple(mat.shape(mat.p.surfaceContainerHighest, 8f),
            mat.p.onSurface, 8f)
        setTextColor(mat.p.onSurface)
        setOnClickListener { showMenu() }
        render()
    }

    private fun render() {
        text = items[index] + "   ▾"
    }

    override fun setEnabled(enabled: Boolean) {
        super.setEnabled(enabled)
        setTextColor(if (enabled) mat.p.onSurface else mat.p.onSurfaceVariant)
        alpha = if (enabled) 1f else 0.6f
    }

    private fun showMenu() {
        val pop = ListPopupWindow(context)
        pop.setAnchorView(this)
        pop.setAdapter(object : ArrayAdapter<String>(
            context, android.R.layout.simple_list_item_1, items) {
            override fun getView(pos: Int, cv: View?, parent: ViewGroup): View {
                val v = super.getView(pos, cv, parent)
                if (v is TextView) {
                    v.text = items[pos]
                    v.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
                    v.setTextColor(mat.p.onSurface)
                    v.setPadding(mat.dp(16f), mat.dp(10f), mat.dp(16f), mat.dp(10f))
                    v.setBackgroundColor(
                        if (pos == index) mat.p.secondaryContainer else Color.TRANSPARENT)
                }
                return v
            }
        })
        pop.setOnItemClickListener { _, _, pos, _ ->
            index = pos
            onSelect?.invoke(pos)
            pop.dismiss()
        }
        pop.setBackgroundDrawable(mat.shape(mat.p.surfaceContainerHigh, 12f))
        pop.setModal(true)
        pop.width = width                       // 与控件同宽：点开时已经 layout 过
        pop.height = ListPopupWindow.WRAP_CONTENT
        pop.setVerticalOffset(mat.dp(4f))
        pop.show()
        // 去掉系统的橙色/蓝色高亮与分割线，否则 M3 圆角浮层上会露出旧样式
        pop.listView?.apply {
            selector = ColorDrawable(Color.TRANSPARENT)
            divider = null
            dividerHeight = 0
            // 不设这个，快速滚动时列表底会被填成黑块（AbsListView 的老行为）
            setCacheColorHint(Color.TRANSPARENT)
        }
    }
}
