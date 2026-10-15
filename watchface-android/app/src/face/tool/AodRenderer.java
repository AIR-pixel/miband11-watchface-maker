package face.tool;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import face.AodFont;
import face.AodGen;

/**
 * AOD 素材绘制（Android 侧）。数字位图用内嵌字库（{@link AodFont}）——
 * 不再读 Canvas/Typeface 渲染：两端像素完全一致，且缩放结果可以被
 * {@code tools/diff_face.py --stage font} 逐像素对拍。
 *
 * <h2>为什么是 alpha 遮罩而不是彩色 ARGB</h2>
 * 数字/冒号是"透明底 + 单色字"。若画进 ARGB_8888，Android 内部是**预乘**存储，
 * 读回来的 RGB 会带上 alpha 权重，直接当直通 alpha 的 BGRA 用，字边缘会出现一圈暗边。
 * 现在拿 {@link AodFont} 给的灰度遮罩乘上目标颜色，得到的就是直通 alpha。
 */
public final class AodRenderer {

    private AodRenderer() {}

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
        return AodGen.maskToBgra(
            AodFont.fit(AodFont.glyph(digit), AodFont.GLYPH_W, AodFont.GLYPH_H, dw, dh),
            rgb[0], rgb[1], rgb[2]);
    }

    // ------------------------------------------------------------------ 冒号

    private static byte[] colon(int w, int h, int[] rgb) {
        return AodGen.maskToBgra(
            AodFont.fit(AodFont.colon(), AodFont.COLON_W, AodFont.COLON_H, w, h),
            rgb[0], rgb[1], rgb[2]);
    }
}
