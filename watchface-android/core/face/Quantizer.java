package face;

import java.util.ArrayList;
import java.util.List;

/**
 * 中位切分调色板量化 + Floyd-Steinberg 抖动（纯 Java，零依赖）。
 * 对应 PC 端 Pillow 的 quantize(method=MEDIANCUT, dither=FLOYDSTEINBERG)。
 */
public final class Quantizer {

    public static final class Result {
        public final byte[] palette;   // N*3 RGB
        public final byte[] indices;   // w*h，每像素一个调色板索引
        Result(byte[] p, byte[] i) { palette = p; indices = i; }
    }

    private Quantizer() {}

    /** rgb：每像素 0x00RRGGBB。colors：目标颜色数（256/128/64）。 */
    public static Result quantize(int[] rgb, int w, int h, int colors, boolean dither) {
        int[][] pal = medianCut(rgb, colors);

        byte[] idx = new byte[rgb.length];
        if (dither) {
            ditherMap(rgb, w, h, pal, idx);
        } else {
            for (int i = 0; i < rgb.length; i++) {
                idx[i] = (byte) nearest(pal, rgb[i]);
            }
        }

        byte[] palBytes = new byte[pal.length * 3];
        for (int i = 0; i < pal.length; i++) {
            palBytes[i * 3] = (byte) ((pal[i][0] >> 16) & 0xFF);
            palBytes[i * 3 + 1] = (byte) ((pal[i][0] >> 8) & 0xFF);
            palBytes[i * 3 + 2] = (byte) (pal[i][0] & 0xFF);
        }
        return new Result(palBytes, idx);
    }

    // ---- 中位切分 ----
    private static int[][] medianCut(int[] pixels, int colors) {
        List<int[]> boxes = new ArrayList<>();
        boxes.add(pixels.clone());
        int distinct = distinctCount(pixels);
        int target = Math.min(colors, distinct);

        while (boxes.size() < target) {
            int bi = -1, maxLen = 0;
            for (int i = 0; i < boxes.size(); i++) {
                if (boxes.get(i).length > maxLen) { maxLen = boxes.get(i).length; bi = i; }
            }
            if (bi < 0 || boxes.get(bi).length <= 1) break;
            int[] box = boxes.get(bi);
            int ch = widestChannel(box);
            countingSort(box, ch);
            int mid = box.length / 2;
            int[] a = new int[mid];
            int[] b = new int[box.length - mid];
            System.arraycopy(box, 0, a, 0, mid);
            System.arraycopy(box, mid, b, 0, box.length - mid);
            boxes.set(bi, a);
            boxes.add(b);
        }

        int[][] pal = new int[boxes.size()][1];
        for (int i = 0; i < boxes.size(); i++) {
            pal[i][0] = average(boxes.get(i));
        }
        return pal;
    }

    private static int distinctCount(int[] px) {
        java.util.HashSet<Integer> s = new java.util.HashSet<>();
        for (int p : px) s.add(p);
        return s.size();
    }

    private static int widestChannel(int[] box) {
        int rmin = 255, rmax = 0, gmin = 255, gmax = 0, bmin = 255, bmax = 0;
        for (int p : box) {
            int r = (p >> 16) & 0xFF, g = (p >> 8) & 0xFF, b = p & 0xFF;
            if (r < rmin) rmin = r; if (r > rmax) rmax = r;
            if (g < gmin) gmin = g; if (g > gmax) gmax = g;
            if (b < bmin) bmin = b; if (b > bmax) bmax = b;
        }
        int rr = rmax - rmin, gg = gmax - gmin, bb = bmax - bmin;
        if (rr >= gg && rr >= bb) return 0;
        if (gg >= rr && gg >= bb) return 1;
        return 2;
    }

    private static int chv(int p, int ch) {
        return ch == 0 ? ((p >> 16) & 0xFF) : ch == 1 ? ((p >> 8) & 0xFF) : (p & 0xFF);
    }

    private static void countingSort(int[] arr, int ch) {
        int[] count = new int[256];
        for (int v : arr) count[chv(v, ch)]++;
        int[] pos = new int[256];
        int sum = 0;
        for (int i = 0; i < 256; i++) { pos[i] = sum; sum += count[i]; }
        int[] out = new int[arr.length];
        for (int v : arr) out[pos[chv(v, ch)]++] = v;
        System.arraycopy(out, 0, arr, 0, arr.length);
    }

    private static int average(int[] box) {
        long r = 0, g = 0, b = 0;
        for (int p : box) { r += (p >> 16) & 0xFF; g += (p >> 8) & 0xFF; b += p & 0xFF; }
        int n = box.length;
        return (((int) (r / n)) << 16) | (((int) (g / n)) << 8) | ((int) (b / n));
    }

    // ---- 最近邻 ----
    private static int nearest(int[][] pal, int p) {
        int best = 0, bestD = Integer.MAX_VALUE;
        int pr = (p >> 16) & 0xFF, pg = (p >> 8) & 0xFF, pb = p & 0xFF;
        for (int i = 0; i < pal.length; i++) {
            int c = pal[i][0];
            int dr = pr - ((c >> 16) & 0xFF), dg = pg - ((c >> 8) & 0xFF), db = pb - (c & 0xFF);
            int d = dr * dr + dg * dg + db * db;
            if (d < bestD) { bestD = d; best = i; }
        }
        return best;
    }

    // ---- Floyd-Steinberg ----
    private static void ditherMap(int[] rgb, int w, int h, int[][] pal, byte[] idx) {
        int n = rgb.length;
        float[] r = new float[n], g = new float[n], b = new float[n];
        for (int i = 0; i < n; i++) {
            r[i] = (rgb[i] >> 16) & 0xFF;
            g[i] = (rgb[i] >> 8) & 0xFF;
            b[i] = rgb[i] & 0xFF;
        }
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                int i = y * w + x;
                float fr = clampF(r[i]), fg = clampF(g[i]), fb = clampF(b[i]);
                int pi = nearestFloat(pal, fr, fg, fb);
                idx[i] = (byte) pi;
                int c = pal[pi][0];
                float er = fr - ((c >> 16) & 0xFF);
                float eg = fg - ((c >> 8) & 0xFF);
                float eb = fb - (c & 0xFF);
                if (x + 1 < w) {
                    r[i + 1] += er * 7 / 16; g[i + 1] += eg * 7 / 16; b[i + 1] += eb * 7 / 16;
                }
                if (y + 1 < h) {
                    int d = i + w;
                    if (x > 0) { r[d - 1] += er * 3 / 16; g[d - 1] += eg * 3 / 16; b[d - 1] += eb * 3 / 16; }
                    r[d] += er * 5 / 16; g[d] += eg * 5 / 16; b[d] += eb * 5 / 16;
                    if (x + 1 < w) { r[d + 1] += er * 1 / 16; g[d + 1] += eg * 1 / 16; b[d + 1] += eb * 1 / 16; }
                }
            }
        }
    }

    private static int nearestFloat(int[][] pal, float pr, float pg, float pb) {
        int best = 0; float bestD = Float.MAX_VALUE;
        for (int i = 0; i < pal.length; i++) {
            int c = pal[i][0];
            float dr = pr - ((c >> 16) & 0xFF), dg = pg - ((c >> 8) & 0xFF), db = pb - (c & 0xFF);
            float d = dr * dr + dg * dg + db * db;
            if (d < bestD) { bestD = d; best = i; }
        }
        return best;
    }

    private static float clampF(float v) {
        return v < 0 ? 0 : v > 255 ? 255 : v;
    }
}
