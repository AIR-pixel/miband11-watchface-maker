package face.tool;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.MediaMetadataRetriever;
import android.net.Uri;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import face.AodGen;
import face.FaceBuilder;
import face.LuaGen;
import face.PngEncoder;
import face.Quantizer;

/**
 * 把「素材 + 裁剪框 + 压缩等级 + 帧率 + 截取区间 + 帧数上限 + 编码格式 + JPEG 质量 + 快放开关
 * + 多壁纸 + 主屏叠加 + 息屏显示」转成 .face。
 * 核心算法（FaceBuilder/AodGen/LuaGen/Quantizer/PngEncoder）零 Android 依赖。
 *
 * <p>体积的第一杠杆是**帧数**（时长 x 帧率），其次才是色深：
 * 实测 212x520 单帧 RGB 147KB / P256 67KB / P128 53KB / P64 41.5KB / P32 31.6KB / P16 20.4KB；
 * JPEG 4:4:4 q90 41KB / q85 33KB / q80 28KB / q70 21KB。
 *
 * <p>帧数上限触顶时有两种走法（流畅度 x 时长 x 体积的三角权衡，只能选一边牺牲）：
 * speedup=false 保时长、降帧率（内容完整、速度正常、会掉帧）；
 * speedup=true  保帧率、压时长（流畅、内容完整、播放变快）。
 *
 * <p>多壁纸沿用与 PC 端相同的约定：第 1 张前缀 {@code face}（保证与单壁纸版字节兼容），
 * 第 2 张起 {@code w2}、{@code w3}…；{@code maxFrames} 是**每张**壁纸的上限。
 */
public final class FaceGenerator {

    public interface Progress { void onProgress(float frac, String msg); }

    public static final int W = 212, H = 520;
    public static final int DEFAULT_MAX_FRAMES = 96;
    public static final int JPG_QUALITY = 80;
    /** JPEG 质量档位（实测单帧 4:4:4：q90 41K / q85 33K / q80 28K / q70 21K）。 */
    public static final int[] JPG_QUALITY_OPTIONS = {90, 85, 80, 70, 60};
    /**
     * .face 尾部预览位图固定开销：12 B 头 + 212*520*4 = 440,972 B（约 430 KB）。
     * 头部 + 元数据 + 索引 + 描述块 ≈ 几百字节。这里给 300 KB 的历史估计值，
     * 属于**偏小**的粗估 —— 真实的固定开销约 431 KB。UI 里另外单独标注了真实值。
     */
    public static final long HEADER_OVERHEAD = 300L * 1024;

    private FaceGenerator() {}

    /** 帧数规划结果。sampleFps 决定抽多少帧，playFps 决定播放节奏。 */
    public static final class Plan {
        public final int nFrames;
        public final double sampleFps;
        public final double playFps;
        public final double spanSec;
        public final int periodMs;
        public final boolean speedup;

        Plan(int n, double sample, double play, double span, int period, boolean su) {
            nFrames = n; sampleFps = sample; playFps = play;
            spanSec = span; periodMs = period; speedup = su;
        }

        /** 加速倍数（未快放时为 1）。 */
        public double speedMult() {
            return (sampleFps > 0 && Math.abs(sampleFps - playFps) > 0.01)
                ? playFps / sampleFps : 1.0;
        }

        /** 播放时长（秒）。 */
        public double playSeconds() { return nFrames * periodMs / 1000.0; }
    }

    /**
     * 在真正抽帧前规划帧数与播放节奏。
     * speedup=false：超上限时自动降帧率，播放时长不变；
     * speedup=true ：帧率不变，把 maxFrames 帧摊到整段时长上，播放时快放。
     *
     * <p>fps 用 double：素材真实帧率常常不是整数（29.97 / 23.976），
     * 取整会让长素材的帧数偏掉几帧。
     */
    public static Plan planFrames(double durationMs, double fps, double clipStart,
                                  double clipDur, int maxFrames, boolean speedup) {
        double totalS = durationMs / 1000.0;
        double f = fps > 0 ? fps : 24.0;
        if (totalS <= 0) {
            return new Plan(1, f, f, 0, f > 0 ? (int) Math.round(1000.0 / f) : 100, speedup);
        }
        double start = Math.max(0, Math.min(clipStart, totalS));
        double span = clipDur <= 0 ? (totalS - start) : Math.min(clipDur, totalS - start);
        span = Math.max(0, span);

        int n;
        double sample, play;
        if (speedup) {
            n = Math.min(Math.max(1, (int) Math.round(span * f)), maxFrames);
            sample = span > 0 ? n / span : f;
            play = f;
        } else {
            n = Math.max(1, (int) Math.round(span * f));
            if (n > maxFrames) {
                n = maxFrames;
                f = span > 0 ? n / span : f;
            }
            sample = f;
            play = f;
        }
        int period = play > 0 ? (int) Math.round(1000.0 / play) : 42;
        return new Plan(n, sample, play, span, period, speedup);
    }

    // ------------------------------------------------------------------ 入参

    /** 一张壁纸的来源与截取参数。 */
    public static final class WallSpec {
        public Uri uri;
        /** "video" | "image"。 */
        public String srcType = "video";
        /** (x0,y0,x1,y1) 源像素坐标；null = 全高居中裁切。 */
        public int[] crop;
        public double clipStart = 0;
        public double clipDur = 0;
        /** 0 = 源帧率。 */
        public int fps = 0;
        public int maxFrames = DEFAULT_MAX_FRAMES;
        public boolean speedup = false;

        public WallSpec(Uri uri, String srcType) {
            this.uri = uri;
            this.srcType = srcType;
        }
    }

    /** 全部生成参数。 */
    public static final class Opts {
        public List<WallSpec> walls = new ArrayList<WallSpec>();
        public String level = "balanced";
        /** "png" | "jpg"。 */
        public String fmt = "png";
        public int jpgQuality = JPG_QUALITY;
        public String title = "MyWatchface";
        /** null 则按时间戳自动生成，避免与市集表盘撞车。 */
        public String faceId;

        /** 主屏：时间/日期/点击交互（walls 字段由 generate 内部按实际抽帧结果填）。 */
        public LuaGen.Opts lua = new LuaGen.Opts();

        /** 息屏显示。 */
        public AodGen.Cfg aod = new AodGen.Cfg();
        /** aod.bgMode=custom 时的底图（调用方解码好传进来）。 */
        public Bitmap aodBg;
    }

    // ------------------------------------------------------------------ 主流程

    public static byte[] generate(Context ctx, Opts o, Progress cb) throws Exception {
        if (o.walls.isEmpty()) throw new IllegalArgumentException("至少需要一张壁纸");
        final int nWalls = o.walls.size();

        final int colors; final boolean dither;
        { int[] ld = levelParams(o.level); colors = ld[0]; dither = ld[1] != 0; }
        final String ext = "jpg".equals(o.fmt) ? "jpg" : "png";

        final List<FaceBuilder.FileEntry> files = new ArrayList<FaceBuilder.FileEntry>();
        List<LuaGen.Wall> luaWalls = new ArrayList<LuaGen.Wall>();
        final byte[][] previewHolder = new byte[1][];
        int totalFrames = 0;

        for (int wi = 0; wi < nWalls; wi++) {
            final WallSpec ws = o.walls.get(wi);
            final int fwi = wi;
            final String tag = nWalls > 1 ? ("壁纸 " + (wi + 1) + "/" + nWalls) : "";
            float base = 0.05f + 0.75f * wi / nWalls;
            prog(cb, base, "读取素材…" + tag);

            double durMs = probeDurationMs(ctx, ws.uri, ws.srcType);
            // 用户没指定帧率时读素材真实帧率，读不到才退回 24（与 PC 端一致）。
            // 之前这里一律写死 24，同一个素材两端算出的帧数会不一样。
            final double fps = ws.fps > 0 ? ws.fps : probeFrameRate(ctx, ws.uri, ws.srcType);
            final Plan plan = planFrames(durMs, fps, ws.clipStart, ws.clipDur,
                                         ws.maxFrames, ws.speedup);
            if (nWalls == 1 && plan.speedMult() > 1.01) {
                prog(cb, 0.08f, String.format(
                    "快放模式：%d 帧覆盖 %.1fs，按 %.0ffps 播放 ≈ %.1fs（%.1f 倍速）",
                    plan.nFrames, plan.spanSec, plan.playFps, plan.playSeconds(), plan.speedMult()));
            } else if (nWalls == 1 && fps > 0 && Math.abs(plan.playFps - fps) >= 1) {
                prog(cb, 0.08f, String.format(
                    "时长 %.1fs x %.0ffps 超过帧数上限 %d，自动降到 %.1ffps（时长不变）",
                    plan.spanSec, fps, ws.maxFrames, plan.playFps));
            }

            final int[] nOut = {0};
            FrameSink sink = new FrameSink() {
                @Override public void accept(Bitmap raw) {
                    // 边抽边编码边回收：原实现先把全部原始分辨率帧攒进 List，
                    // 96 帧 1080p 就是约 800 MB，直接 OOM。
                    Bitmap cropped = cropScale(raw, ws.crop);
                    try {
                        byte[] data = encodeFrame(cropped, colors, dither, o.fmt, o.jpgQuality);
                        files.add(new FaceBuilder.FileEntry(
                            String.format("lua/%s_%02d.%s", wallPrefix(fwi), nOut[0] + 1, ext),
                            data));
                        if (fwi == 0 && nOut[0] == 0) previewHolder[0] = toBgra(cropped);
                    } finally {
                        if (cropped != raw) cropped.recycle();
                    }
                    nOut[0]++;
                    prog(cb, 0.05f + 0.75f * (fwi + nOut[0] / (float) Math.max(1, plan.nFrames))
                              / nWalls,
                         "处理" + tag + " 帧 " + nOut[0] + "/" + plan.nFrames);
                }
            };
            forEachFrame(ctx, ws.uri, ws.srcType, plan, ws.clipStart, sink);
            if (nOut[0] == 0) {
                // 一帧都没抽到（MediaMetadataRetriever 啃不动的素材）：退回整图
                Bitmap b = BitmapFactory.decodeStream(
                    ctx.getContentResolver().openInputStream(ws.uri));
                if (b != null) {
                    try { sink.accept(b); } finally { if (!b.isRecycled()) b.recycle(); }
                }
            }

            luaWalls.add(new LuaGen.Wall(wallPrefix(wi), nOut[0], plan.periodMs));
            totalFrames += nOut[0];
        }

        byte[] previewBgra = previewHolder[0] != null ? previewHolder[0] : blackBgra();

        // ---- main.lua ----
        prog(cb, 0.82f, "生成脚本…");
        o.lua.walls = luaWalls;
        o.lua.periodMs = luaWalls.get(0).periodMs;
        o.lua.ext = ext;
        o.lua.fpsDesc = nWalls + " 张壁纸 / 共 " + totalFrames + " 帧";
        files.add(new FaceBuilder.FileEntry("lua/main.lua",
                                            LuaGen.generate(o.lua).getBytes("UTF-8")));

        // ---- 息屏显示 ----
        boolean hasAod = o.aod != null && o.aod.enabled;
        List<FaceBuilder.Rec> aodRecs = null;
        if (hasAod) {
            prog(cb, 0.90f, "生成息屏素材…");
            List<AodGen.Widget> widgets = AodGen.planAll(o.aod);
            Map<String, AodGen.Img> imgs = AodRenderer.render(widgets, o.aodBg, o.aod.color);
            aodRecs = AodGen.buildRecords(widgets, imgs);
        }

        prog(cb, 0.95f, "打包 .face…");
        String faceId = o.faceId != null && !o.faceId.isEmpty() ? o.faceId : autoFaceId();
        return FaceBuilder.build(o.title, faceId, files, previewBgra, hasAod, aodRecs);
    }

    /** 进度回调：cb 为 null 时安静跳过（调用方不该因为不关心进度就 NPE）。 */
    private static void prog(Progress cb, float frac, String msg) {
        if (cb != null) cb.onProgress(frac, msg);
    }

    /** 壁纸文件名前缀：第 1 张沿用 face（与单壁纸版本字节兼容），第 2 张起 w2、w3… */
    private static String wallPrefix(int index) {
        return index == 0 ? "face" : ("w" + (index + 1));
    }

    /** 旧签名（单壁纸、无 AOD）。 */
    public static byte[] generate(Context ctx, Uri uri, String srcType,
                                  int[] crop, String level, int fps,
                                  double clipStart, double clipDur, int maxFrames,
                                  String fmt, int jpgQuality, boolean speedup,
                                  String title, String faceId,
                                  Progress cb) throws Exception {
        Opts o = new Opts();
        WallSpec ws = new WallSpec(uri, srcType);
        ws.crop = crop; ws.fps = fps; ws.clipStart = clipStart; ws.clipDur = clipDur;
        ws.maxFrames = maxFrames; ws.speedup = speedup;
        o.walls.add(ws);
        o.level = level; o.fmt = fmt; o.jpgQuality = jpgQuality;
        o.title = title; o.faceId = faceId;
        return generate(ctx, o, cb);
    }

    // ------------------------------------------------------------------ 体积

    /**
     * 只算**帧数据**（不含固定开销与 AOD）。多壁纸时逐张相加，
     * 再统一加一次 {@link #HEADER_OVERHEAD} 和 {@link AodGen#estimateBytes}。
     */
    public static long estimateWallBytes(Context ctx, Uri uri, String srcType, int[] crop,
                                         String level, String fmt, int nFrames, int jpgQuality) {
        return estimateWallBytes(ctx, uri, srcType, crop, level, fmt, nFrames, jpgQuality, null);
    }

    /**
     * 带预览帧缓存的版本。
     *
     * <p>UI 的体积预估会被反复调用（每改一个参数都要重算），每次都重新解码视频
     * 首帧很浪费 —— 调用方把已经解码好的首帧传进来即可。传 null 就自己解码。
     */
    public static long estimateWallBytes(Context ctx, Uri uri, String srcType, int[] crop,
                                         String level, String fmt, int nFrames, int jpgQuality,
                                         Bitmap cachedPreview) {
        try {
            Bitmap b = cachedPreview != null ? cachedPreview : previewFrame(ctx, uri, srcType);
            if (b == null) return 0;
            Bitmap c = cropScale(b, crop);
            int[] ld = levelParams(level);
            byte[] d = encodeFrame(c, ld[0], ld[1] != 0, fmt, jpgQuality);
            if (c != b) c.recycle();
            return (long) d.length * nFrames;
        } catch (Throwable e) {
            return 0;
        }
    }

    /** 单张壁纸的完整预估（帧数据 + 固定开销）。 */
    public static long estimateBytes(Context ctx, Uri uri, String srcType, int[] crop,
                                     String level, String fmt, int nFrames,
                                     int jpgQuality) {
        return estimateBytes(ctx, uri, srcType, crop, level, fmt, nFrames, jpgQuality, null);
    }

    /** 带 AOD 的版本：AOD 通常比动画帧还大，不加上会让预估严重偏低。 */
    public static long estimateBytes(Context ctx, Uri uri, String srcType, int[] crop,
                                     String level, String fmt, int nFrames,
                                     int jpgQuality, AodGen.Cfg aod) {
        long wall = estimateWallBytes(ctx, uri, srcType, crop, level, fmt, nFrames, jpgQuality);
        if (wall <= 0) return 0;
        return wall + HEADER_OVERHEAD + AodGen.estimateBytes(aod);
    }

    private static int[] levelParams(String level) {
        switch (level) {
            case "high":  return new int[]{0, 0};
            case "small": return new int[]{128, 1};
            case "tiny":  return new int[]{64, 0};
            case "micro": return new int[]{32, 0};
            case "nano":  return new int[]{16, 0};
            default:      return new int[]{256, 1};
        }
    }

    // ---- 抽帧 ----
    public static double probeDurationMs(Context ctx, Uri uri, String srcType) {
        if ("image".equals(srcType)) return 0;
        MediaMetadataRetriever mmr = new MediaMetadataRetriever();
        try {
            mmr.setDataSource(ctx, uri);
            String d = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION);
            return d != null ? Double.parseDouble(d) : 0;
        } catch (Exception e) {
            return 0;
        } finally {
            try { mmr.release(); } catch (Throwable ignored) {}
        }
    }

    /** 逐帧消费：抽到一张就交给 sink 处理掉，不让整批帧驻留内存。 */
    private interface FrameSink {
        void accept(Bitmap raw);
    }

    /**
     * 抽帧并逐帧交给 sink。
     *
     * <p>不返回 List：原始分辨率的帧攒在内存里是 OOM 的头号来源
     * （96 帧 1080p ≈ 800 MB）。sink 返回后原帧立即回收。
     */
    private static void forEachFrame(Context ctx, Uri uri, String srcType, Plan plan,
                                     double clipStart, FrameSink sink) throws Exception {
        if ("image".equals(srcType)) {
            Bitmap b = BitmapFactory.decodeStream(ctx.getContentResolver().openInputStream(uri));
            if (b != null) {
                try { sink.accept(b); } finally { if (!b.isRecycled()) b.recycle(); }
            }
            return;
        }
        double sampleFps = plan.sampleFps > 0 ? plan.sampleFps : 24.0;
        MediaMetadataRetriever mmr = new MediaMetadataRetriever();
        try {
            mmr.setDataSource(ctx, uri);
            for (int i = 0; i < plan.nFrames; i++) {
                long tUs = (long) ((clipStart + i / sampleFps) * 1_000_000L);
                Bitmap f = mmr.getFrameAtTime(tUs, MediaMetadataRetriever.OPTION_CLOSEST);
                if (f == null) continue;
                try { sink.accept(f); } finally { if (!f.isRecycled()) f.recycle(); }
            }
        } finally {
            try { mmr.release(); } catch (Throwable ignored) {}
        }
    }

    /**
     * 素材真实帧率；拿不到返回 0（调用方退回 24）。
     * PC 端会读源帧率，安卓端之前一律写死 24，两端帧数对不上。
     */
    public static double probeFrameRate(Context ctx, Uri uri, String srcType) {
        if ("image".equals(srcType)) return 0;
        MediaMetadataRetriever mmr = new MediaMetadataRetriever();
        try {
            mmr.setDataSource(ctx, uri);
            String s = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_CAPTURE_FRAMERATE);
            if (s != null) {
                double v = Double.parseDouble(s);
                if (v > 0) return v;
            }
        } catch (Exception ignored) {
            // 拿不到就退回默认
        } finally {
            try { mmr.release(); } catch (Throwable ignored) {}
        }
        return 0;
    }

    // ---- 帧处理 ----

    /** 裁切并缩放到 212x520。crop 为 null 时用「全高 + 水平居中」。 */
    private static Bitmap cropScale(Bitmap src, int[] crop) {
        int sw = src.getWidth(), sh = src.getHeight();
        int[] cb = crop != null ? crop : defaultCrop(sw, sh);
        int x0 = Math.max(0, Math.min(cb[0], sw - 1));
        int y0 = Math.max(0, Math.min(cb[1], sh - 1));
        int x1 = Math.max(x0 + 1, Math.min(cb[2], sw));
        int y1 = Math.max(y0 + 1, Math.min(cb[3], sh));
        Bitmap c = Bitmap.createBitmap(src, x0, y0, x1 - x0, y1 - y0);
        Bitmap s = Bitmap.createScaledBitmap(c, W, H, true);
        if (s != c) c.recycle();
        return s;
    }

    /** 默认裁切：全高 + 水平居中，锁 212:520；与 PC 端 crop.default_crop 一致。 */
    static int[] defaultCrop(int w, int h) {
        double aspect = (double) W / H;
        double ch = h, cw = ch * aspect;
        if (cw > w) { cw = w; ch = cw / aspect; }
        double cx = w / 2.0, cy = h / 2.0;
        int x0 = (int) Math.round(cx - cw / 2), y0 = (int) Math.round(cy - ch / 2);
        int x1 = (int) Math.round(cx + cw / 2), y1 = (int) Math.round(cy + ch / 2);
        return new int[]{x0, y0, x1, y1};
    }

    private static byte[] encodeFrame(Bitmap bmp, int colors, boolean dither,
                                      String fmt, int jpgQuality) {
        if ("jpg".equals(fmt)) {
            ByteArrayOutputStream o = new ByteArrayOutputStream();
            // 注意：Android 的 Bitmap.compress 固定 4:2:0 色度子采样，改不了，
            // 所以安卓端 JPEG 质量天花板低于 PC 端（PC 走 4:4:4）。
            bmp.compress(Bitmap.CompressFormat.JPEG, jpgQuality, o);
            return o.toByteArray();
        }
        int[] px = new int[W * H];
        bmp.getPixels(px, 0, W, 0, 0, W, H);
        if (colors <= 0) {
            byte[] rgb = new byte[W * H * 3];
            for (int i = 0; i < px.length; i++) {
                rgb[i * 3] = (byte) ((px[i] >> 16) & 0xFF);
                rgb[i * 3 + 1] = (byte) ((px[i] >> 8) & 0xFF);
                rgb[i * 3 + 2] = (byte) (px[i] & 0xFF);
            }
            return PngEncoder.encodeRGB(W, H, rgb);
        }
        for (int i = 0; i < px.length; i++) px[i] &= 0xFFFFFF;
        Quantizer.Result r = Quantizer.quantize(px, W, H, colors, dither);
        return PngEncoder.encodeP8(W, H, r.palette, r.indices);
    }

    /**
     * 帧位图 → 尾部预览位图。
     *
     * <p><b>必须是 BGRA</b> —— .face 里的像素一律 BGRA8888 直通 alpha（实测）。
     * 早期版本这里写的是 RGBA，红蓝会对调（纯色彩素材上表现为整体偏色）。
     */
    static byte[] toBgra(Bitmap bmp) {
        int[] px = new int[W * H];
        bmp.getPixels(px, 0, W, 0, 0, W, H);
        return AodGen.argbToBgra(px);
    }

    private static byte[] blackBgra() {
        byte[] b = new byte[W * H * 4];
        for (int i = 3; i < b.length; i += 4) b[i] = (byte) 0xFF;
        return b;
    }

    private static String autoFaceId() {
        String s = String.valueOf(System.currentTimeMillis() / 1000L);
        return s.length() > 8 ? s.substring(s.length() - 8) : s;
    }

    /** 供主界面生成预览帧用。 */
    public static Bitmap previewFrame(Context ctx, Uri uri, String srcType) {
        if ("image".equals(srcType)) {
            try {
                return BitmapFactory.decodeStream(ctx.getContentResolver().openInputStream(uri));
            } catch (Exception e) { return null; }
        }
        MediaMetadataRetriever mmr = new MediaMetadataRetriever();
        try {
            mmr.setDataSource(ctx, uri);
            return mmr.getFrameAtTime(0, MediaMetadataRetriever.OPTION_CLOSEST);
        } catch (Exception e) {
            return null;
        } finally {
            try { mmr.release(); } catch (Throwable ignored) {}
        }
    }
}
