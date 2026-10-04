package face.tool

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View

/**
 * 裁剪预览 View：显示素材预览帧，支持拖动移动 / 右下角拖动或双指缩放裁剪框（比例锁 212:520）。
 * 裁剪框坐标以「源图像素」为单位，通过 getCrop() 取回。
 *
 * 缩放修正要点（此前"缩放异常"的原因）：
 * 1. 高度按**绝对位置**推导（当前点到锚点），而不是"初始高度 + 单步增量"——
 *    后者每步都从按下时刻重算，缩放几乎不累积，拖了没反应。
 * 2. 水平/垂直拖动都能驱动缩放（取两者较大者），不再只认垂直分量。
 * 3. 补充双指缩放；手柄命中区比视觉大，便于抓取。
 */
class CropView(context: Context) : View(context) {

    fun interface OnCropChanged {
        fun changed(x0: Int, y0: Int, x1: Int, y1: Int)
    }

    private companion object {
        const val ASPECT = 212f / 520f
        const val MIN_H = 20f            // 裁剪框最小高度（源像素）
        const val HANDLE_VIS_DP = 8f     // 手柄视觉半边长（dp）
        const val HANDLE_HIT_DP = 22f    // 手柄命中半边长（dp，比视觉大）
        const val MODE_NONE = 0
        const val MODE_MOVE = 1
        const val MODE_RESIZE = 2
    }

    private var src: Bitmap? = null
    private val imgRect = RectF()    // 图片在 View 内的绘制区域
    private val crop = RectF()       // 裁剪框（源图像素坐标）
    private var listener: OnCropChanged? = null

    private var mode = MODE_NONE
    private var lastX = 0f
    private var lastY = 0f
    private val origin = RectF()

    private val scaleDetector = ScaleGestureDetector(context,
        object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
            override fun onScale(d: ScaleGestureDetector): Boolean {
                if (src == null) return false
                zoomBy(d.scaleFactor)
                return true
            }
        })

    /** 裁剪框/手柄的颜色（跟随动态取色）。 */
    var accent: Int = Color.rgb(0, 190, 255)
        set(v) {
            field = v
            borderPaint.color = v
            handlePaint.color = v
            invalidate()
        }

    /** 无素材时的底色。 */
    var frameColor: Int = Color.rgb(40, 40, 40)
        set(v) { field = v; invalidate() }

    private val dimPaint = Paint().apply { color = 0x99000000.toInt() }
    private val borderPaint = Paint().apply {
        color = Color.rgb(0, 190, 255)
        style = Paint.Style.STROKE
        strokeWidth = dp(2f)
    }
    private val handlePaint = Paint().apply { color = Color.rgb(0, 190, 255) }
    private val cornerPaint = Paint().apply {
        color = Color.argb(220, 255, 255, 255)
        style = Paint.Style.STROKE
        strokeWidth = dp(3f)
    }

    fun setBitmap(b: Bitmap?) {
        src = b
        recalcFit()
        resetCrop()
    }

    /** 默认裁剪框：85% 高居中 —— 留出上下移动余地（全高会被 clamp 锁死）。 */
    fun resetCrop() {
        val s = src ?: return
        applyCropFrac(s, 0.85f)
        emit()
        invalidate()
    }

    /** 铺满：尽可能大地取框（会自动吸附比例）。 */
    fun fillCrop() {
        val s = src ?: return
        applyCropFrac(s, 1.0f)
        emit()
        invalidate()
    }

    private fun applyCropFrac(s: Bitmap, frac: Float) {
        var ch = s.height * frac
        var cw = ch * ASPECT
        if (cw > s.width) {
            cw = s.width.toFloat()
            ch = cw / ASPECT
        }
        val cx = s.width / 2f
        val cy = s.height / 2f
        crop.set(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        clampCrop()
    }

    fun getCrop(): IntArray = intArrayOf(
        crop.left.toInt(), crop.top.toInt(), crop.right.toInt(), crop.bottom.toInt())

    fun setOnCropChanged(l: OnCropChanged) {
        listener = l
    }

    // ---------------------------------------------------------------- 坐标

    private fun recalcFit() {
        val s = src ?: return
        if (width == 0 || height == 0) return
        val scale = minOf(width / s.width.toFloat(), height / s.height.toFloat())
        val dw = s.width * scale
        val dh = s.height * scale
        val ox = (width - dw) / 2f
        val oy = (height - dh) / 2f
        imgRect.set(ox, oy, ox + dw, oy + dh)
    }

    private fun scale(): Float {
        val s = src ?: return 1f
        return if (s.width == 0) 1f else imgRect.width() / s.width
    }

    private fun toImg(vx: Float, vy: Float, out: FloatArray) {
        val s = scale()
        out[0] = (vx - imgRect.left) / s
        out[1] = (vy - imgRect.top) / s
    }

    private fun handleRect(hit: Boolean): RectF {
        val s = scale()
        val hx = imgRect.left + crop.right * s
        val hy = imgRect.top + crop.bottom * s
        val half = dp(if (hit) HANDLE_HIT_DP else HANDLE_VIS_DP)
        return RectF(hx - half, hy - half, hx + half, hy + half)
    }

    private fun cropWidgetRect(): RectF {
        val s = scale()
        return RectF(
            imgRect.left + crop.left * s, imgRect.top + crop.top * s,
            imgRect.left + crop.right * s, imgRect.top + crop.bottom * s)
    }

    /** 按比例缩放（以框中心为锚）。 */
    private fun zoomBy(f: Float) {
        val s = src ?: return
        val cx = crop.centerX()
        val cy = crop.centerY()
        var newH = maxOf(MIN_H, crop.height() * f)
        var newW = newH * ASPECT
        if (newW > s.width) {
            newW = s.width.toFloat()
            newH = newW / ASPECT
        }
        if (newH > s.height) {
            newH = s.height.toFloat()
            newW = newH * ASPECT
        }
        crop.set(cx - newW / 2, cy - newH / 2, cx + newW / 2, cy + newH / 2)
        clampCrop()
        emit()
        invalidate()
    }

    // ---------------------------------------------------------------- 交互

    override fun onTouchEvent(e: MotionEvent): Boolean {
        if (src == null) return true
        scaleDetector.onTouchEvent(e)
        if (scaleDetector.isInProgress) {
            mode = MODE_NONE
            invalidate()
            return true
        }
        val x = e.x
        val y = e.y
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                // 裁剪框拖动优先于外层滚动容器
                parent?.requestDisallowInterceptTouchEvent(true)
                mode = if (handleRect(true).contains(x, y)) MODE_RESIZE else MODE_MOVE
                lastX = x
                lastY = y
                origin.set(crop)
                invalidate()
                return true
            }

            MotionEvent.ACTION_POINTER_DOWN -> {
                mode = MODE_NONE     // 多指交给 ScaleGestureDetector
                return true
            }

            MotionEvent.ACTION_MOVE -> {
                if (mode == MODE_NONE) return true
                val cur = FloatArray(2)
                val last = FloatArray(2)
                toImg(x, y, cur)
                toImg(lastX, lastY, last)
                when (mode) {
                    MODE_MOVE -> crop.offset(cur[0] - last[0], cur[1] - last[1])
                    MODE_RESIZE -> {
                        // 绝对位移驱动：横拖竖拖都响应
                        val hFromY = cur[1] - origin.top
                        val hFromX = (cur[0] - origin.left) / ASPECT
                        val newH = maxOf(MIN_H, maxOf(hFromY, hFromX))
                        val newW = newH * ASPECT
                        crop.set(origin.left, origin.top, origin.left + newW, origin.top + newH)
                    }
                }
                clampCrop()
                lastX = x
                lastY = y
                invalidate()
                return true
            }

            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                parent?.requestDisallowInterceptTouchEvent(false)
                mode = MODE_NONE
                clampCrop()
                emit()
                invalidate()
                return true
            }
        }
        return true
    }

    private fun clampCrop() {
        val s = src ?: return
        var w = minOf(crop.width(), s.width.toFloat())
        var h = w / ASPECT
        if (h > s.height) {
            h = s.height.toFloat()
            w = h * ASPECT
        }
        w = maxOf(w, MIN_H)
        h = maxOf(h, MIN_H)
        crop.right = crop.left + w
        crop.bottom = crop.top + h
        if (crop.left < 0) crop.offsetTo(0f, crop.top)
        if (crop.top < 0) crop.offsetTo(crop.left, 0f)
        if (crop.right > s.width) crop.offsetTo(s.width - crop.width(), crop.top)
        if (crop.bottom > s.height) crop.offsetTo(crop.left, s.height - crop.height())
    }

    private fun emit() {
        listener?.changed(crop.left.toInt(), crop.top.toInt(),
            crop.right.toInt(), crop.bottom.toInt())
    }

    override fun onSizeChanged(w: Int, h: Int, ow: Int, oh: Int) {
        super.onSizeChanged(w, h, ow, oh)
        recalcFit()
    }

    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(frameColor)
        val s = src ?: return
        canvas.drawBitmap(s, null, imgRect, null)

        val cr = cropWidgetRect()
        // 暗化裁剪框外
        canvas.drawRect(imgRect.left, imgRect.top, imgRect.right, cr.top, dimPaint)
        canvas.drawRect(imgRect.left, cr.bottom, imgRect.right, imgRect.bottom, dimPaint)
        canvas.drawRect(imgRect.left, cr.top, cr.left, cr.bottom, dimPaint)
        canvas.drawRect(cr.right, cr.top, imgRect.right, cr.bottom, dimPaint)

        canvas.drawRect(cr, borderPaint)

        // 四角标记（白）
        val len = dp(14f)
        canvas.drawLine(cr.left, cr.top, cr.left + len, cr.top, cornerPaint)
        canvas.drawLine(cr.left, cr.top, cr.left, cr.top + len, cornerPaint)
        canvas.drawLine(cr.right, cr.top, cr.right - len, cr.top, cornerPaint)
        canvas.drawLine(cr.right, cr.top, cr.right, cr.top + len, cornerPaint)
        canvas.drawLine(cr.left, cr.bottom, cr.left + len, cr.bottom, cornerPaint)
        canvas.drawLine(cr.left, cr.bottom, cr.left, cr.bottom - len, cornerPaint)

        // 右下角缩放手柄：实心方块 + 白边
        val h = handleRect(false)
        canvas.drawRect(h, handlePaint)
        canvas.drawRect(h, cornerPaint)
    }

    private fun dp(v: Float) = v * resources.displayMetrics.density
}
