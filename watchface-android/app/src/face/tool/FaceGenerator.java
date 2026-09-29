package face.tool;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.MediaMetadataRetriever;
import android.net.Uri;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.List;

import face.FaceBuilder;
import face.LuaGen;
import face.PngEncoder;
import face.Quantizer;

/**
 * 把「素材 + 裁剪框 + 压缩等级 + 帧率 + 截取区间 + 帧数上限 + 编码格式 + JPEG 质量 + 快放开关」
 * 转成 .face。核心算法（FaceBuilder/Quantizer/PngEncoder/LuaGen）零 Android 依赖。
 *
 * 体积的第一杠杆是**帧数**（时长 x 帧率），其次才是色深：
 * 实测 212x520 单帧 RGB 147KB / P256 67KB / P128 53KB / P64 41.5KB / P32 31.6KB / P16 20.4KB；
 * JPEG 4:4:4 q90 41KB / q85 33KB / q80 28KB / q70 21KB。
 *
 * 帧数上限触顶时有两种走法（流畅度 x 时长 x 体积的三角权衡，只能选一边牺牲）：
 *   speedup=false 保时长、降帧率（内容完整、速度正常、会掉帧）
 *   speedup=true  保帧率、压时长（流畅、内容完整、播放变快）
 */
public final class FaceGenerator {

    public interface Progress { void onProgress(float frac, String msg); }

    public static final int W = 212, H = 520;
    public static final int DEFAULT_MAX_FRAMES = 96;
    public static final int JPG_QUALITY = 80;
    /** JPEG 质量档位（实测单帧 4:4:4：q90 41K / q85 33K / q80 28K / q70 21K）。 */
    public static final int[] JPG_QUALITY_OPTIONS = {90, 85, 80, 70, 60};
    /** .face 头部 + 尾部位图（212x520 RGBA8888 = 440960B）等固定开销。 */
    private static final long HEADER_OVERHEAD = 300L * 1024;

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

    public static Plan planFrames(double durationMs, int fps, double clipStart,
                                  double clipDur, int maxFrames) {
        return planFrames(durationMs, fps, clipStart, clipDur, maxFrames, false);
    }

    /**
     * 在真正抽帧前规划帧数与播放节奏。
     * speedup=false：超上限时自动降帧率，播放时长不变；
     * speedup=true ：帧率不变，把 maxFrames 帧摊到整段时长上，播放时快放。
     */
    public static Plan planFrames(double durationMs, int fps, double clipStart,
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

    public static byte[] generate(Context ctx, Uri uri, String srcType,
                                  int[] crop, String level, int fps,
                                  double clipStart, double clipDur, int maxFrames,
                                  String fmt, int jpgQuality, boolean speedup,
                                  String title, String faceId,
                                  Progress cb) throws Exception {
        cb.onProgress(0.05f, "读取素材…");

        // 1. 探测时长并规划（超上限时按模式决定降帧率还是快放）
        double durMs = probeDurationMs(ctx, uri, srcType);
        Plan plan = planFrames(durMs, fps, clipStart, clipDur, maxFrames, speedup);
        if (plan.speedMult() > 1.01) {
            cb.onProgress(0.08f, String.format(
                "快放模式：%d 帧覆盖 %.1fs，按 %.0ffps 播放 ≈ %.1fs（%.1f 倍速）",
                plan.nFrames, plan.spanSec, plan.playFps, plan.playSeconds(), plan.speedMult()));
        } else if (fps > 0 && Math.abs(plan.playFps - fps) >= 1) {
            cb.onProgress(0.08f, String.format(
                "时长 %.1fs x %dfps 超过帧数上限 %d，自动降到 %.1ffps（时长不变）",
                plan.spanSec, fps, maxFrames, plan.playFps));
        }

        // 2. 抽帧
        List<Bitmap> frames = extractFrames(ctx, uri, srcType, plan, clipStart);

        int colors; boolean dither;
        switch (level) {
            case "high":  colors = 0;   dither = false; break;
            case "small": colors = 128; dither = true;  break;
            case "tiny":  colors = 64;  dither = false; break;
            case "micro": colors = 32;  dither = false; break;
            case "nano":  colors = 16;  dither = false; break;
            default:      colors = 256; dither = true;
        }

        String ext = "jpg".equals(fmt) ? "jpg" : "png";
        List<FaceBuilder.FileEntry> files = new ArrayList<>();
        int n = frames.size();
        byte[] previewRgba = null;

        for (int i = 0; i < n; i++) {
            Bitmap cropped = cropScale(frames.get(i), crop);
            byte[] data = encodeFrame(cropped, colors, dither, fmt, jpgQuality);
            files.add(new FaceBuilder.FileEntry(
                String.format("lua/face_%02d.%s", i + 1, ext), data));
            if (i == 0) previewRgba = toRgba(cropped);
            cb.onProgress(0.2f + 0.6f * (i + 1) / n, "处理帧 " + (i + 1) + "/" + n);
        }

        String lua = LuaGen.generate(n, plan.periodMs, true, ext);
        files.add(new FaceBuilder.FileEntry("lua/main.lua", lua.getBytes("UTF-8")));

        cb.onProgress(0.9f, "打包 .face…");
        return FaceBuilder.build(title, faceId, files, previewRgba);
    }

    /** 体积预估：用首帧真实编码字节外推 + 固定开销（供 UI 实时显示）。 */
    public static long estimateBytes(Context ctx, Uri uri, String srcType, int[] crop,
                                     String level, String fmt, int nFrames,
                                     int jpgQuality) {
        try {
            Bitmap b = previewFrame(ctx, uri, srcType);
            if (b == null) return 0;
            Bitmap c = cropScale(b, crop);
            int colors; boolean dither;
            switch (level) {
                case "high":  colors = 0;   dither = false; break;
                case "small": colors = 128; dither = true;  break;
                case "tiny":  colors = 64;  dither = false; break;
                case "micro": colors = 32;  dither = false; break;
                case "nano":  colors = 16;  dither = false; break;
                default:      colors = 256; dither = true;
            }
            byte[] d = encodeFrame(c, colors, dither, fmt, jpgQuality);
            return (long) d.length * nFrames + HEADER_OVERHEAD;
        } catch (Throwable e) {
            return 0;
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

    private static List<Bitmap> extractFrames(Context ctx, Uri uri, String srcType,
                                              Plan plan, double clipStart) throws Exception {
        List<Bitmap> out = new ArrayList<>();
        if ("image".equals(srcType)) {
            Bitmap b = BitmapFactory.decodeStream(ctx.getContentResolver().openInputStream(uri));
            if (b != null) out.add(b);
            return out;
        }
        double sampleFps = plan.sampleFps > 0 ? plan.sampleFps : 24.0;
        MediaMetadataRetriever mmr = new MediaMetadataRetriever();
        try {
            mmr.setDataSource(ctx, uri);
            int n = plan.nFrames;
            for (int i = 0; i < n; i++) {
                long tUs = (long) ((clipStart + i / sampleFps) * 1_000_000L);
                Bitmap f = mmr.getFrameAtTime(tUs, MediaMetadataRetriever.OPTION_CLOSEST);
                if (f != null) out.add(f);
            }
        } finally {
            try { mmr.release(); } catch (Throwable ignored) {}
        }
        if (out.isEmpty()) {
            // 视频抽帧失败则退回整图（可能是个 gif，MediaMetadataRetriever 抽不到帧）
            Bitmap b = BitmapFactory.decodeStream(ctx.getContentResolver().openInputStream(uri));
            if (b != null) out.add(b);
        }
        return out;
    }

    // ---- 帧处理 ----
    private static Bitmap cropScale(Bitmap src, int[] crop) {
        int sw = src.getWidth(), sh = src.getHeight();
        int x0 = Math.max(0, Math.min(crop[0], sw - 1));
        int y0 = Math.max(0, Math.min(crop[1], sh - 1));
        int x1 = Math.max(x0 + 1, Math.min(crop[2], sw));
        int y1 = Math.max(y0 + 1, Math.min(crop[3], sh));
        Bitmap c = Bitmap.createBitmap(src, x0, y0, x1 - x0, y1 - y0);
        Bitmap s = Bitmap.createScaledBitmap(c, W, H, true);
        if (s != c) c.recycle();
        return s;
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

    private static byte[] toRgba(Bitmap bmp) {
        int[] px = new int[W * H];
        bmp.getPixels(px, 0, W, 0, 0, W, H);
        byte[] rgba = new byte[W * H * 4];
        for (int i = 0; i < px.length; i++) {
            rgba[i * 4] = (byte) ((px[i] >> 16) & 0xFF);
            rgba[i * 4 + 1] = (byte) ((px[i] >> 8) & 0xFF);
            rgba[i * 4 + 2] = (byte) (px[i] & 0xFF);
            rgba[i * 4 + 3] = (byte) 0xFF;
        }
        return rgba;
    }

    // 供主界面生成预览帧用
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
