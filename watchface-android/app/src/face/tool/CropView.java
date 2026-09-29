package face.tool;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;

/**
 * 裁剪预览 View：显示素材预览帧，支持拖动移动 / 右下角缩放裁剪框（比例锁 212:520）。
 * 裁剪框坐标以"源图像素"为单位，通过 getCrop() 取回。
 *
 * 缩放修正要点（此前"缩放异常"的原因）：
 * 1. 高度按**绝对位置**推导（当前点到锚点），而不是"初始高度 + 单步增量"——
 *    后者每步都从按下时刻重算，缩放几乎不累积，拖了没反应。
 * 2. 水平/垂直拖动都能驱动缩放（取两者较大者），不再只认垂直分量。
 * 3. 补充双指缩放；手柄命中区比视觉大，便于抓取。
 */
public final class CropView extends View {

    public interface OnCropChanged { void changed(int x0, int y0, int x1, int y1); }

    private static final float ASPECT = 212f / 520f;
    private static final float MIN_H = 20f;      // 裁剪框最小高度（源像素）
    private static final float HANDLE_VIS_DP = 8f;   // 手柄视觉半边长（dp）
    private static final float HANDLE_HIT_DP = 22f;  // 手柄命中半边长（dp，比视觉大）

    private Bitmap src;
    private RectF imgRect = new RectF();   // 图片在 View 内的绘制区域
    private RectF crop = new RectF();      // 裁剪框（源图像素坐标）
    private OnCropChanged listener;

    private int mode;                       // 0=无 1=移动 2=缩放
    private float lastX, lastY;
    private RectF origin = new RectF();

    private final ScaleGestureDetector scaleDetector;

    private final Paint dimPaint = new Paint();
    private final Paint borderPaint = new Paint();
    private final Paint handlePaint = new Paint();
    private final Paint cornerPaint = new Paint();

    public CropView(Context c) {
        super(c);
        dimPaint.setColor(0x99000000);
        borderPaint.setColor(Color.rgb(0, 190, 255));
        borderPaint.setStyle(Paint.Style.STROKE);
        borderPaint.setStrokeWidth(dp(2));
        handlePaint.setColor(Color.rgb(0, 190, 255));
        cornerPaint.setColor(Color.argb(220, 255, 255, 255));
        cornerPaint.setStyle(Paint.Style.STROKE);
        cornerPaint.setStrokeWidth(dp(3));

        scaleDetector = new ScaleGestureDetector(c,
            new ScaleGestureDetector.SimpleOnScaleGestureListener() {
                @Override
                public boolean onScale(ScaleGestureDetector d) {
                    if (src == null) return false;
                    zoomBy(d.getScaleFactor());
                    return true;
                }
            });
    }

    public void setBitmap(Bitmap b) {
        src = b;
        recalcFit();
        resetCrop();
    }

    /** 默认裁剪框：85% 高居中 —— 留出上下移动余地（全高会被 clamp 锁死）。 */
    public void resetCrop() {
        if (src == null) return;
        applyCropFrac(0.85f);
        emit();
        invalidate();
    }

    /** 铺满：尽可能大地取框（会自动吸附比例）。 */
    public void fillCrop() {
        if (src == null) return;
        applyCropFrac(1.0f);
        emit();
        invalidate();
    }

    private void applyCropFrac(float frac) {
        float ch = src.getHeight() * frac;
        float cw = ch * ASPECT;
        if (cw > src.getWidth()) { cw = src.getWidth(); ch = cw / ASPECT; }
        float cx = src.getWidth() / 2f, cy = src.getHeight() / 2f;
        crop.set(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2);
        clampCrop();
    }

    public int[] getCrop() {
        return new int[]{
            (int) crop.left, (int) crop.top,
            (int) crop.right, (int) crop.bottom
        };
    }

    public void setOnCropChanged(OnCropChanged l) { listener = l; }

    private void recalcFit() {
        if (src == null || getWidth() == 0 || getHeight() == 0) return;
        float scale = Math.min(getWidth() / (float) src.getWidth(),
                               getHeight() / (float) src.getHeight());
        float dw = src.getWidth() * scale, dh = src.getHeight() * scale;
        float ox = (getWidth() - dw) / 2f, oy = (getHeight() - dh) / 2f;
        imgRect.set(ox, oy, ox + dw, oy + dh);
    }

    private float scale() {
        return src == null || src.getWidth() == 0 ? 1f : imgRect.width() / src.getWidth();
    }

    private void toImg(float vx, float vy, float[] out) {
        out[0] = (vx - imgRect.left) / scale();
        out[1] = (vy - imgRect.top) / scale();
    }

    private RectF handleRect(boolean hit) {
        float s = scale();
        float hx = imgRect.left + crop.right * s;
        float hy = imgRect.top + crop.bottom * s;
        float half = hit ? dp(HANDLE_HIT_DP) : dp(HANDLE_VIS_DP);
        return new RectF(hx - half, hy - half, hx + half, hy + half);
    }

    private RectF cropWidgetRect() {
        float s = scale();
        return new RectF(
            imgRect.left + crop.left * s, imgRect.top + crop.top * s,
            imgRect.left + crop.right * s, imgRect.top + crop.bottom * s);
    }

    /** 按比例缩放（以框中心为锚）。 */
    private void zoomBy(float f) {
        if (src == null) return;
        float cx = crop.centerX(), cy = crop.centerY();
        float newH = Math.max(MIN_H, crop.height() * f);
        float newW = newH * ASPECT;
        if (newW > src.getWidth()) { newW = src.getWidth(); newH = newW / ASPECT; }
        if (newH > src.getHeight()) { newH = src.getHeight(); newW = newH * ASPECT; }
        crop.set(cx - newW / 2, cy - newH / 2, cx + newW / 2, cy + newH / 2);
        clampCrop();
        emit();
        invalidate();
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        if (src == null) return true;
        scaleDetector.onTouchEvent(e);
        if (scaleDetector.isInProgress()) {
            mode = 0;
            invalidate();
            return true;
        }
        float x = e.getX(), y = e.getY();
        switch (e.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                if (handleRect(true).contains(x, y)) {
                    mode = 2;                       // 缩放
                } else {
                    mode = 1;                       // 框内框外都进入移动；不再把框瞬移到点击点
                }
                lastX = x; lastY = y;
                origin.set(crop);
                invalidate();
                return true;
            case MotionEvent.ACTION_POINTER_DOWN:
                mode = 0;                           // 多指交给 ScaleGestureDetector
                return true;
            case MotionEvent.ACTION_MOVE: {
                if (mode == 0) break;
                float[] cur = new float[2], last = new float[2];
                toImg(x, y, cur);
                toImg(lastX, lastY, last);
                if (mode == 1) {
                    crop.offset(cur[0] - last[0], cur[1] - last[1]);
                } else if (mode == 2) {
                    // 绝对位移驱动：横拖竖拖都响应
                    float hFromY = cur[1] - origin.top;
                    float hFromX = (cur[0] - origin.left) / ASPECT;
                    float newH = Math.max(MIN_H, Math.max(hFromY, hFromX));
                    float newW = newH * ASPECT;
                    crop.set(origin.left, origin.top, origin.left + newW, origin.top + newH);
                }
                clampCrop();
                lastX = x; lastY = y;
                invalidate();
                return true;
            }
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                mode = 0;
                clampCrop();
                emit();
                invalidate();
                return true;
        }
        return true;
    }

    private void clampCrop() {
        float w = Math.min(crop.width(), src.getWidth());
        float h = w / ASPECT;
        if (h > src.getHeight()) { h = src.getHeight(); w = h * ASPECT; }
        w = Math.max(w, MIN_H); h = Math.max(h, MIN_H);
        crop.right = crop.left + w;
        crop.bottom = crop.top + h;
        if (crop.left < 0) crop.offsetTo(0, crop.top);
        if (crop.top < 0) crop.offsetTo(crop.left, 0);
        if (crop.right > src.getWidth()) crop.offsetTo(src.getWidth() - crop.width(), crop.top);
        if (crop.bottom > src.getHeight()) crop.offsetTo(crop.left, src.getHeight() - crop.height());
    }

    private void emit() {
        if (listener != null) {
            listener.changed((int) crop.left, (int) crop.top, (int) crop.right, (int) crop.bottom);
        }
    }

    @Override
    protected void onSizeChanged(int w, int h, int ow, int oh) {
        super.onSizeChanged(w, h, ow, oh);
        recalcFit();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        canvas.drawColor(Color.rgb(40, 40, 40));
        if (src == null) return;
        canvas.drawBitmap(src, null, imgRect, null);

        RectF cr = cropWidgetRect();
        // 暗化裁剪框外
        canvas.drawRect(imgRect.left, imgRect.top, imgRect.right, cr.top, dimPaint);
        canvas.drawRect(imgRect.left, cr.bottom, imgRect.right, imgRect.bottom, dimPaint);
        canvas.drawRect(imgRect.left, cr.top, cr.left, cr.bottom, dimPaint);
        canvas.drawRect(cr.right, cr.top, imgRect.right, cr.bottom, dimPaint);

        canvas.drawRect(cr, borderPaint);

        // 四角标记（白）
        float L = dp(14);
        canvas.drawLine(cr.left, cr.top, cr.left + L, cr.top, cornerPaint);
        canvas.drawLine(cr.left, cr.top, cr.left, cr.top + L, cornerPaint);
        canvas.drawLine(cr.right, cr.top, cr.right - L, cr.top, cornerPaint);
        canvas.drawLine(cr.right, cr.top, cr.right, cr.top + L, cornerPaint);
        canvas.drawLine(cr.left, cr.bottom, cr.left + L, cr.bottom, cornerPaint);
        canvas.drawLine(cr.left, cr.bottom, cr.left, cr.bottom - L, cornerPaint);

        // 右下角缩放手柄：实心方块 + 白边
        RectF h = handleRect(false);
        canvas.drawRect(h, handlePaint);
        canvas.drawRect(h, cornerPaint);
    }

    private float dp(float v) { return v * getResources().getDisplayMetrics().density; }
}
