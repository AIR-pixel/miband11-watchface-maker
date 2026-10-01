package face;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 息屏显示（AOD）子工程的**纯逻辑**：布局规划 + 描述记录推导 + 体积预估。
 *
 * <p>零 Android 依赖 —— 像素由调用方以 {@link Img} 传入，因此可以在桌面 JVM 上
 * 与 PC 端 Python 参考实现逐字节对拍（12 例 × 13 字段，12/12 一致；
 * 颜色解析另测 12/12）。改动本文件后请重跑该差分 ——
 * 参见 {@code docs/项目经验.md} 方法论第 5 条。
 * 平台相关的绘制（Canvas / Typeface）放在 {@code face.tool.AodRenderer}。
 *
 * <h2>AOD 的三条硬事实（2026-10-01 实测，别推翻重来）</h2>
 * <ol>
 *   <li><b>AOD 屏不支持 Lua。</b>在 AOD.fprj 里写 Shape=34 挂载点，lua 不会入包
 *       （产物只多 88 B，且换名/不换名字节相同）。所以 AOD 只能靠
 *       Shape=30（静态图）与 Shape=32（数字位图 + Value_Src）驱动。</li>
 *   <li><b>Shape=32 的数据源是真的。</b>Value_Src 写数据源 ID，编译器只把数字原样存下、
 *       不校验，由设备侧 dataman 运行期解析。</li>
 *   <li><b>AOD 上的 Shape=30 很便宜</b>（`w*h*4 + 60`），因为不会被合成为整屏位图；
 *       主屏上的 Shape=30 才会（+441 KB/个）。</li>
 * </ol>
 *
 * <h2>设计取舍</h2>
 * 时分共用同一张 11 图数字列表（各两位），只付一次位图钱；冒号单独一张 Shape=30 小图
 * （12x64 ≈ 3 KB），比再建一张 Shape=32 列表划算。默认不放全屏黑底 ——
 * AMOLED 黑像素不发光，白省 431 KB。
 */
public final class AodGen {

    public static final int SCREEN_W = 212;
    public static final int SCREEN_H = 520;

    public static final int TIME_DIGIT_W = 46, TIME_DIGIT_H = 64;
    public static final int DATE_DIGIT_W = 20, DATE_DIGIT_H = 28;
    /** 时与分 / 月与日之间的冒号（Shape=30 静态图）。 */
    public static final int COLON_W = 12;

    /**
     * 官方样本（手环 8 Pro）的 BitmapList 是 11 张：00..09 再补一张 00。
     * 照抄这个数量，避免"少一张导致某位数字不显示"这类玄学问题。
     */
    public static final int DIGIT_IMAGE_COUNT = 11;

    /** Value_Src 数据源 ID（十六进制字面量去掉 0x 与前导零）。 */
    public static final String SRC_HOUR = "0811", SRC_MINUTE = "1011";
    public static final String SRC_MONTH = "1012", SRC_DAY = "1812";

    public static final int TAG_ANCHOR = 0x0000, TAG_BITMAP = 0x0200;
    public static final int TAG_ARRAY = 0x0300, TAG_SMALL = 0x0700;

    /** 一张 AOD 素材：尺寸 + **BGRA8888 直通 alpha** 像素。 */
    public static final class Img {
        public final int w, h;
        public final byte[] bgra;

        public Img(int w, int h, byte[] bgra) {
            if (bgra.length != w * h * 4)
                throw new IllegalArgumentException("像素长度 " + bgra.length + " != " + (w * h * 4));
            this.w = w;
            this.h = h;
            this.bgra = bgra;
        }
    }

    /** 一个 AOD 控件。kind=30 静态图 / kind=32 数字（BitmapList + Value_Src）。 */
    public static final class Widget {
        public final int kind;
        public final String name;
        public final int x, y, w, h;
        /** kind=32 用。 */
        public final int digitW, digitH, digits;
        public final String valueSrc;
        public final List<String> bitmapList;
        /** kind=30 用。 */
        public final String img;

        private Widget(int kind, String name, int x, int y, int w, int h,
                       int digitW, int digitH, int digits, String valueSrc,
                       List<String> bitmapList, String img) {
            this.kind = kind; this.name = name; this.x = x; this.y = y; this.w = w; this.h = h;
            this.digitW = digitW; this.digitH = digitH; this.digits = digits;
            this.valueSrc = valueSrc; this.bitmapList = bitmapList; this.img = img;
        }

        static Widget image(String name, String file, int x, int y, int w, int h) {
            return new Widget(30, name, x, y, w, h, 0, 0, 0, null, null, file);
        }

        static Widget digits(String name, int x, int y, int dw, int dh, int digits,
                             String src, List<String> list) {
            return new Widget(32, name, x, y, dw * digits, dh,
                              dw, dh, digits, src, list, null);
        }
    }

    /** AOD 配置。默认值与 Python 端 {@code build_aod} 的 cfg 默认值一致。 */
    public static final class Cfg {
        public boolean enabled;
        /** none | black | custom。 */
        public String bgMode = "none";
        /** 自定义底图是否可用（图片本身由调用方渲染成全屏 Img）。 */
        public boolean hasCustomBg;
        /** none | time | both。 */
        public String timeMode = "time";
        public int timeY = 200, dateY = 300;
        /** '#RRGGBB'。 */
        public String color = "#FFFFFF";

        public int timeDigitW = TIME_DIGIT_W, timeDigitH = TIME_DIGIT_H;
        public int dateDigitW = DATE_DIGIT_W, dateDigitH = DATE_DIGIT_H;
        public int colonW = COLON_W;
    }

    private AodGen() {}

    // ------------------------------------------------------------------ 布局

    /** 数字型控件要落的文件名（0..9），与 Python 端命名一致。 */
    public static String[] digitFiles(boolean time) {
        String[] f = new String[10];
        for (int i = 0; i < 10; i++) f[i] = String.format(time ? "aod_t_%02d.png" : "aod_d_%02d.png", i);
        return f;
    }

    /**
     * 按 cfg 算出完整控件列表（含底图），顺序与 Python {@code build_aod} 的追加顺序一致：
     * 底图 → 时 → 冒号 → 分 → 月 → 冒号 → 日。
     */
    public static List<Widget> planAll(Cfg c) {
        List<Widget> ws = new ArrayList<Widget>();
        boolean hasBg = c.enabled && ("black".equals(c.bgMode)
                || ("custom".equals(c.bgMode) && c.hasCustomBg));
        if (hasBg) ws.add(Widget.image("aod_bg", "aod_bg.png", 0, 0, SCREEN_W, SCREEN_H));

        if (!c.enabled) return ws;
        boolean t = "time".equals(c.timeMode) || "both".equals(c.timeMode);
        boolean d = "both".equals(c.timeMode);
        if (t) {
            List<String> tf = digitList(true);
            int tw = c.timeDigitW * 2 + c.colonW + c.timeDigitW * 2;
            int x0 = (SCREEN_W - tw) / 2;
            ws.add(Widget.digits("aod_hour", x0, c.timeY, c.timeDigitW, c.timeDigitH,
                                 2, SRC_HOUR, tf));
            ws.add(Widget.image("aod_colon", "aod_colon.png",
                                x0 + c.timeDigitW * 2, c.timeY, c.colonW, c.timeDigitH));
            ws.add(Widget.digits("aod_min", x0 + c.timeDigitW * 2 + c.colonW, c.timeY,
                                 c.timeDigitW, c.timeDigitH, 2, SRC_MINUTE, tf));
        }
        if (d) {
            List<String> df = digitList(false);
            int dw = c.dateDigitW * 2 + c.colonW + c.dateDigitW * 2;
            int dx = (SCREEN_W - dw) / 2;
            ws.add(Widget.digits("aod_month", dx, c.dateY, c.dateDigitW, c.dateDigitH,
                                 2, SRC_MONTH, df));
            ws.add(Widget.image("aod_dcolon", "aod_dcolon.png",
                                dx + c.dateDigitW * 2, c.dateY, c.colonW, c.dateDigitH));
            ws.add(Widget.digits("aod_day", dx + c.dateDigitW * 2 + c.colonW, c.dateY,
                                 c.dateDigitW, c.dateDigitH, 2, SRC_DAY, df));
        }
        return ws;
    }

    /**
     * BitmapList：10 张（0..9）**再补一张 0 凑成 11 项** —— 官方样本就是 11 张，
     * 照抄数量规避"某位数字不显示"。时分共用同一份，所以只付一次位图钱。
     */
    public static List<String> digitList(boolean time) {
        String[] f = digitFiles(time);
        List<String> l = new ArrayList<String>(DIGIT_IMAGE_COUNT);
        for (String s : f) l.add(s);
        l.add(f[0]);
        return l;
    }

    // -------------------------------------------------------------- 描述记录

    /**
     * 由控件列表推导 AOD 描述记录。顺序固定为
     * <b>锚(0x0000)×控件数 → 位图(0x0200) → 位图数组(0x0300) → 小件(0x0700)</b>。
     *
     * <p>两个容易写错的地方：
     * <ul>
     *   <li>记录里的 {@code idx}：锚是**控件序号**，其余是**该类内序号**（0,1,2…），
     *       互相独立计数。</li>
     *   <li>锚 payload 的首字段也是**类内序号**（按 refTag 0x0200 / 0x0700 分别计数），
     *       不是控件序号。</li>
     * </ul>
     *
     * @param images 文件名 → 素材。kind=30 用控件自身的 w/h；kind=32 用 digitW/digitH。
     */
    public static List<FaceBuilder.Rec> buildRecords(List<Widget> ws, Map<String, Img> images) {
        List<FaceBuilder.Rec> recs = new ArrayList<FaceBuilder.Rec>();

        // ---- 锚：一条控件一条 ----
        int seq200 = 0, seq700 = 0;
        for (int i = 0; i < ws.size(); i++) {
            Widget w = ws.get(i);
            int refTag = w.kind == 30 ? TAG_BITMAP : TAG_SMALL;
            int anchorX = w.kind == 30 ? w.x : w.x + w.digitW;
            int anchorY = w.y;
            int seq = w.kind == 30 ? seq200++ : seq700++;
            byte[] p = new byte[16];
            putU16(p, 0, seq);
            putU16(p, 2, refTag);
            putU16(p, 4, anchorX);
            putU16(p, 6, anchorY);
            recs.add(new FaceBuilder.Rec(i, TAG_ANCHOR, p));
        }

        // ---- 位图：每个 Shape=30 一条，idx 是位图类内序号 ----
        int k = 0;
        for (Widget w : ws) {
            if (w.kind != 30) continue;
            Img im = need(images, w.img);
            byte[] p = new byte[12 + im.bgra.length];
            putU16(p, 4, im.w);
            putU16(p, 6, im.h);
            putU32(p, 8, im.bgra.length);
            System.arraycopy(im.bgra, 0, p, 12, im.bgra.length);
            recs.add(new FaceBuilder.Rec(k++, TAG_BITMAP, p));
        }

        // ---- 位图数组：每个「不同 BitmapList」一条（去重） ----
        int ak = 0;
        Map<String, Integer> arrOf = new LinkedHashMap<String, Integer>();
        for (Widget w : ws) {
            if (w.kind != 32) continue;
            String key = key(w.bitmapList);
            if (arrOf.containsKey(key)) continue;
            ByteArrayOutputStream px = new ByteArrayOutputStream();
            for (String f : w.bitmapList) {
                Img im = need(images, f);
                px.write(im.bgra, 0, im.bgra.length);
            }
            byte[] data = px.toByteArray();
            int n = w.bitmapList.size();
            byte[] p = new byte[12 + data.length];
            p[1] = (byte) n;                       // u8 图数
            putU16(p, 4, w.digitW);
            putU16(p, 6, w.digitH);
            putU32(p, 8, w.digitW * w.digitH * 4 * n);
            System.arraycopy(data, 0, p, 12, data.length);
            arrOf.put(key, ak);
            recs.add(new FaceBuilder.Rec(ak++, TAG_ARRAY, p));
        }

        // ---- 小件：每个 Shape=32 一条 ----
        int sk = 0;
        for (Widget w : ws) {
            if (w.kind != 32) continue;
            Integer ai = arrOf.get(key(w.bitmapList));
            if (ai == null) throw new IllegalStateException("未找到位图数组：" + w.name);
            byte[] p = new byte[20];
            byte[] vs = hex2bin(w.valueSrc);
            p[0] = vs[0];
            p[1] = vs[1];
            p[2] = (byte) w.digits;
            p[3] = 0x16;
            putU16(p, 8, ai);
            putU16(p, 10, TAG_ARRAY);
            recs.add(new FaceBuilder.Rec(sk++, TAG_SMALL, p));
        }
        return recs;
    }

    /** 控件表引用到的全部素材文件名 → 需要的像素尺寸（调用方据此绘制）。 */
    public static Map<String, int[]> neededImages(List<Widget> ws) {
        Map<String, int[]> m = new LinkedHashMap<String, int[]>();
        for (Widget w : ws) {
            if (w.kind == 30) {
                m.put(w.img, new int[]{w.w, w.h});
            } else {
                for (String f : w.bitmapList) m.put(f, new int[]{w.digitW, w.digitH});
            }
        }
        return m;
    }

    // ------------------------------------------------------------------ 体积

    /**
     * 按实测模型估算 AOD 给整个 .face 增加多少字节。
     *
     * <p>模型：AOD 空屏 +88 B；每个 Shape=30 `w*h*4 + 60`；
     * 每个 Shape=32 `图宽*图高*4 * 图数`（共用同一 BitmapList 只算一次）。
     */
    public static long estimateBytes(Cfg c) {
        if (!c.enabled) return 0;
        long n = 88;
        if ("black".equals(c.bgMode) || "custom".equals(c.bgMode)) {
            n += (long) SCREEN_W * SCREEN_H * 4 + 60;
        }
        if ("time".equals(c.timeMode) || "both".equals(c.timeMode)) {
            n += (long) DIGIT_IMAGE_COUNT * c.timeDigitW * c.timeDigitH * 4;
            n += (long) c.colonW * c.timeDigitH * 4 + 60;
        }
        if ("both".equals(c.timeMode)) {
            n += (long) DIGIT_IMAGE_COUNT * c.dateDigitW * c.dateDigitH * 4;
            n += (long) c.colonW * c.dateDigitH * 4 + 60;
        }
        return n;
    }

    // ---------------------------------------------------------------- helper

    private static String key(List<String> list) {
        StringBuilder s = new StringBuilder();
        for (int i = 0; i < list.size(); i++) {
            if (i > 0) s.append('|');
            s.append(list.get(i));
        }
        return s.toString();
    }

    private static Img need(Map<String, Img> images, String name) {
        Img im = images.get(name);
        if (im == null) throw new IllegalStateException("缺素材：" + name);
        return im;
    }

    /** "0811" → {0x08, 0x11}。 */
    public static byte[] hex2bin(String hex) {
        byte[] b = new byte[hex.length() / 2];
        for (int i = 0; i < b.length; i++) {
            b[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
        }
        return b;
    }

    /** ARGB(0xAARRGGBB) → 直通 alpha 的 BGRA 字节流。 */
    public static byte[] argbToBgra(int[] argb) {
        byte[] out = new byte[argb.length * 4];
        for (int i = 0; i < argb.length; i++) {
            int c = argb[i];
            out[i * 4] = (byte) (c & 0xFF);            // B
            out[i * 4 + 1] = (byte) ((c >>> 8) & 0xFF); // G
            out[i * 4 + 2] = (byte) ((c >>> 16) & 0xFF); // R
            out[i * 4 + 3] = (byte) ((c >>> 24) & 0xFF); // A
        }
        return out;
    }

    /** 用一个灰度遮罩 + 固定颜色合成直通 alpha 的 BGRA（等价于 PIL 画单色字到透明底）。 */
    public static byte[] maskToBgra(byte[] mask, int r, int g, int b) {
        byte[] out = new byte[mask.length * 4];
        for (int i = 0; i < mask.length; i++) {
            out[i * 4] = (byte) b;
            out[i * 4 + 1] = (byte) g;
            out[i * 4 + 2] = (byte) r;
            out[i * 4 + 3] = mask[i];
        }
        return out;
    }

    /** '#RRGGBB' / '#RGB' → {r,g,b}，非法则返回白色。 */
    public static int[] parseColor(String s) {
        String t = s == null ? "" : s.trim();
        if (t.startsWith("#")) t = t.substring(1);
        if (t.length() == 3) {
            t = "" + t.charAt(0) + t.charAt(0) + t.charAt(1) + t.charAt(1) + t.charAt(2) + t.charAt(2);
        }
        try {
            return new int[]{Integer.parseInt(t.substring(0, 2), 16),
                             Integer.parseInt(t.substring(2, 4), 16),
                             Integer.parseInt(t.substring(4, 6), 16)};
        } catch (Exception e) {
            return new int[]{255, 255, 255};
        }
    }

    private static void putU16(byte[] b, int o, int v) {
        b[o] = (byte) (v & 0xFF);
        b[o + 1] = (byte) ((v >>> 8) & 0xFF);
    }

    private static void putU32(byte[] b, int o, int v) {
        b[o] = (byte) (v & 0xFF);
        b[o + 1] = (byte) ((v >>> 8) & 0xFF);
        b[o + 2] = (byte) ((v >>> 16) & 0xFF);
        b[o + 3] = (byte) ((v >>> 24) & 0xFF);
    }
}
