package face.tool;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;

import java.nio.ByteBuffer;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import face.AodGen;

/**
 * AOD 素材绘制（Android 侧）。逻辑由 {@link AodGen} 负责，这里只把像素画出来。
 *
 * <h2>为什么用 ALPHA_8 而不是直接画彩色 ARGB</h2>
 * 数字/冒号是"透明底 + 单色字"。若画进 ARGB_8888，Android 内部是**预乘**存储，
 * 读回来的 RGB 会带上 alpha 权重，直接当直通 alpha 的 BGRA 用，字边缘会出现一圈暗边。
 * 改成只画 **alpha 遮罩**，再统一乘上目标颜色，就与 PC 端 PIL 的
 * "透明底 + 单色 fill" 完全同构，得到的就是直通 alpha。
 *
 * <p>字号/居中算法照抄 Python {@code aod.render_digit_images}：
 * 字号取 {@code digit_h * 0.92}，超宽时按 {@code digit_w * 0.96} 等比缩，
 * 最后按字形实际包围盒居中（不是按 advance width）。
 */
public final class AodRenderer {

    private AodRenderer() {}

    /** 数字/冒号的字体。PC 端用 Arial Bold，安卓取同族的 Roboto Bold。 */
    private static final Typeface FONT = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD);

    /**
     * 画出控件表引用到的全部素材。
     *
     * @param customBg bgMode=custom 时的底图（可为 null）；会被拉伸填满 212x520
     * @param colorHex 数字/冒号颜色 '#RRGGBB'
     */
    public static Map<String, AodGen.Img> render(List<AodGen.Widget> ws, Bitmap customBg,
                                                 String colorHex) {
        int[] rgb = AodGen.parseColor(colorHex);
        Map<String, int[]> need = AodGen.neededImages(ws);
        Map<String, AodGen.Img> out = new LinkedHashMap<String, AodGen.Img>();

        boolean needColonTime = false, needColonDate = false;
        for (AodGen.Widget w : ws) {
            if (w.kind != 30) continue;
            if ("aod_colon.png".equals(w.img)) needColonTime = true;
            if ("aod_dcolon.png".equals(w.img)) needColonDate = true;
        }

        for (Map.Entry<String, int[]> e : need.entrySet()) {
            String name = e.getKey();
            int w = e.getValue()[0], h = e.getValue()[1];
            byte[] bgra;
            if ("aod_bg.png".equals(name)) {
                bgra = background(w, h, customBg);
            } else if (name.startsWith("aod_colon") || name.startsWith("aod_dcolon")) {
                bgra = colon(w, h, rgb);
            } else {
                int d = name.charAt(6) - '0';                 // aod_t_07.png / aod_d_07.png
                bgra = digit(w, h, d, rgb);
            }
            out.put(name, new AodGen.Img(w, h, bgra));
        }
        // 保证冒号一定存在（neededImages 里已包含，这里只作断言用）
        if (needColonTime && !out.containsKey("aod_colon.png"))
            throw new IllegalStateException("缺 aod_colon.png");
        if (needColonDate && !out.containsKey("aod_dcolon.png"))
            throw new IllegalStateException("缺 aod_dcolon.png");
        return out;
    }

    // ------------------------------------------------------------------ 底图

    /** 全屏底图，永远不透明。custom 走拉伸填满（与 PIL 的 resize 一致，不裁切）。 */
    private static byte[] background(int w, int h, Bitmap customBg) {
        Bitmap bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
        Canvas cv = new Canvas(bmp);
        cv.drawColor(Color.BLACK);
        if (customBg != null && !customBg.isRecycled()) {
            Paint p = new Paint(Paint.FILTER_BITMAP_FLAG | Paint.DITHER_FLAG);
            p.setAlpha(255);
            cv.drawBitmap(customBg, new Rect(0, 0, customBg.getWidth(), customBg.getHeight()),
                          new RectF(0, 0, w, h), p);
        }
        int[] px = new int[w * h];
        bmp.getPixels(px, 0, w, 0, 0, w, h);
        bmp.recycle();
        for (int i = 0; i < px.length; i++) px[i] |= 0xFF000000;     // 强制不透明
        return AodGen.argbToBgra(px);
    }

    // ------------------------------------------------------------------ 数字

    private static byte[] digit(int dw, int dh, int digit, int[] rgb) {
        // 掩码取 alpha，颜色统一后加 —— 与 PIL 的"透明底 + 单色 fill"同构
        return drawMask(dw, dh, rgb, new MaskPainter() {
            @Override
            public void paint(Canvas cv, Paint p, int w, int h) {
                String ch = String.valueOf(digit);
                Rect b = new Rect();
                float size = Math.max(6, (int) (h * 0.92f));
                p.setTextSize(size);
                p.getTextBounds(ch, 0, 1, b);
                int tw = b.width();
                if (tw > w * 0.96f && tw > 0) {                       // 超宽就等比缩字号
                    size = size * ((w * 0.96f) / tw);
                    p.setTextSize(Math.max(6, size));
                    p.getTextBounds(ch, 0, 1, b);
                }
                // 按字形实际包围盒居中（横竖都比 PIL 的 tight bbox 居中）
                float x = (w - b.width()) / 2f - b.left;
                float baseline = h / 2f - (b.top + b.bottom) / 2f;
                cv.drawText(ch, x, baseline, p);
            }
        });
    }

    // ------------------------------------------------------------------ 冒号

    /** 时:分 / 月:日 之间的冒号：上下两个圆点（照抄 Python render_colon_image）。 */
    private static byte[] colon(int w, int h, int[] rgb) {
        return drawMask(w, h, rgb, new MaskPainter() {
            @Override
            public void paint(Canvas cv, Paint p, int w2, int h2) {
                float r = Math.max(2, (int) (w2 * 0.32f));
                float cx = w2 / 2f;
                p.setStyle(Paint.Style.FILL);
                for (int cy : new int[]{(int) (h2 * 0.34f), (int) (h2 * 0.66f)}) {
                    cv.drawCircle(cx, cy, r, p);
                }
            }
        });
    }

    // ------------------------------------------------------------------ 公共

    private interface MaskPainter {
        void paint(Canvas cv, Paint p, int w, int h);
    }

    /** 在 ALPHA_8 位图上画遮罩，再乘上固定颜色，得到直通 alpha 的 BGRA。 */
    private static byte[] drawMask(int w, int h, int[] rgb, MaskPainter mp) {
        Bitmap bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ALPHA_8);
        Canvas cv = new Canvas(bmp);
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setColor(Color.WHITE);                  // ALPHA_8 下只取 alpha
        p.setTypeface(FONT);
        mp.paint(cv, p, w, h);
        ByteBuffer buf = ByteBuffer.allocate(w * h);
        bmp.copyPixelsToBuffer(buf);
        bmp.recycle();
        return AodGen.maskToBgra(buf.array(), rgb[0], rgb[1], rgb[2]);
    }
}
