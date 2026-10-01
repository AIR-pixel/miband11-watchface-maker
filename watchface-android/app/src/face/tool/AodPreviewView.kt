package face.tool

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.view.View
import face.AodGen
import kotlin.math.min

/**
 * 息屏显示（AOD）布局预览。
 *
 * 直接调 {@link AodGen#planAll} 拿控件表来画，所以**位置与最终 .face 完全一致**；
 * 只有字形是本地 TTF 画的近似（真机字形由 AodRenderer 用同一套 Typeface 生成）。
 *
 * 屏幕底色画成深灰而不是纯黑 —— 让用户看得出"这块是屏幕底，不是我们加的图"，
 * 与 PC 端 render_preview 的处理一致。
 */
class AodPreviewView(ctx: Context) : View(ctx) {

    var cfg: AodGen.Cfg? = null
        set(v) { field = v; invalidate() }

    var colorHex: String = "#FFFFFF"
        set(v) { field = v; invalidate() }

    /** bgMode=custom 时的底图。 */
    var bgBitmap: Bitmap? = null
        set(v) { field = v; invalidate() }

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
        textAlign = Paint.Align.LEFT
    }

    companion object {
        private const val SW = 212f
        private const val SH = 520f
        private val SAMPLE = mapOf(
            AodGen.SRC_HOUR to "09", AodGen.SRC_MINUTE to "41",
            AodGen.SRC_MONTH to "07", AodGen.SRC_DAY to "18")
    }

    override fun onDraw(canvas: Canvas) {
        val c = cfg
        if (c == null || width == 0 || height == 0) return

        val s = min(width / SW, height / SH)
        val ox = (width - SW * s) / 2f
        val oy = (height - SH * s) / 2f
        canvas.save()
        canvas.translate(ox, oy)
        canvas.scale(s, s)

        canvas.drawColor(Color.BLACK)                       // 屏外留白
        canvas.drawRect(0f, 0f, SW, SH, Paint().apply {
            color = if (c.enabled) Color.rgb(8, 8, 10) else Color.rgb(20, 20, 22)
        })
        if (!c.enabled) {
            paint.color = Color.rgb(120, 120, 130)
            paint.textSize = 18f
            paint.textAlign = Paint.Align.CENTER
            canvas.drawText("未启用息屏显示", SW / 2f, SH / 2f, paint)
            paint.textAlign = Paint.Align.LEFT
            canvas.restore()
            return
        }

        val rgb = AodGen.parseColor(colorHex)
        val col = Color.rgb(rgb[0], rgb[1], rgb[2])

        for (w in AodGen.planAll(c)) {
            when {
                w.kind == 30 && w.name == "aod_bg" -> drawBg(canvas, w)
                w.kind == 30 -> {                            // 冒号
                    paint.color = col
                    val r = maxOf(2f, w.w * 0.32f)
                    val cx = w.x + w.w / 2f
                    for (cy in intArrayOf((w.h * 0.34).toInt(), (w.h * 0.66).toInt())) {
                        canvas.drawCircle(cx, w.y + cy.toFloat(), r, paint)
                    }
                }
                else -> {                                    // 数字
                    val text = SAMPLE[w.valueSrc] ?: "00"
                    paint.color = col
                    paint.textSize = w.digitH * 0.92f
                    val b = android.graphics.Rect()
                    for (k in text.indices) {
                        val ch = text[k].toString()
                        paint.getTextBounds(ch, 0, 1, b)
                        val x = w.x + k * w.digitW + (w.digitW - b.width()) / 2f - b.left
                        val baseline = w.y + w.digitH / 2f - (b.top + b.bottom) / 2f
                        canvas.drawText(ch, x, baseline, paint)
                    }
                }
            }
        }
        canvas.restore()
    }

    private fun drawBg(canvas: Canvas, w: AodGen.Widget) {
        val bmp = bgBitmap
        if (bmp != null && !bmp.isRecycled) {
            canvas.drawBitmap(bmp, null, RectF(0f, 0f, w.w.toFloat(), w.h.toFloat()),
                Paint(Paint.FILTER_BITMAP_FLAG))
        } else {
            canvas.drawRect(0f, 0f, w.w.toFloat(), w.h.toFloat(),
                Paint().apply { color = Color.BLACK })
        }
    }
}
