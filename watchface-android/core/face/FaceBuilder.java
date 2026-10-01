package face;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * 纯代码生成小米手环 11 表盘 .face（零 Android 依赖，桌面 JVM / 真机都能编）。
 *
 * <p>格式已完整逆向，并与 Compiler.exe 产物做过**逐字节**比对（无 AOD / 带 AOD 各若干样本）。
 * 全部小端序。
 *
 * <h2>布局（无 AOD）</h2>
 * <pre>
 *   [0,172)          头部 + Title
 *   [172,272)        元数据
 *   [272, 272+n*16)  索引表（n 条，tag 0x0500）
 *   [.., firstFile)  描述块（只剩一条 0x0500 哨兵）
 *   [firstFile,..)   文件数据区（条目起点 4 字节对齐，末条也补齐到 4 字节）
 *   [末尾]           预览位图（12B 头 + 212*520*4，**BGRA**）
 * </pre>
 *
 * <h2>布局（带 AOD 息屏子工程）</h2>
 * <pre>
 *   [0,172)          头部 + Title
 *   [172,260)        元数据·主屏（22 个 u32，索引表基址变成 360、屏数变 2）
 *   [260,360)        元数据·AOD 尾部（25 个 u32）
 *   [360, 360+n*16)  索引表（n 条，tag 0x0500）
 *   [d0, descEnd)    描述块：锚(0x0000)×控件数 → 位图(0x0200) → 位图数组(0x0300) → 小件(0x0700) → 哨兵(0x0500)
 *   [descEnd,..)     文件数据区（最后一条**不**补尾部对齐）
 *   [assetsStart,..) AOD 素材区，紧随数据区（4 字节对齐）；实排顺序：锚 → 小件 → 位图 → 数组
 *   [末尾]           预览位图（BGRA）
 * </pre>
 *
 * <p>关键细节（都是实测踩出来的，别随手改）：
 * <ul>
 *   <li>描述块从 {@code idx + n*16} 开始，不是 {@code idx + (n+1)*16}。索引表只有 n 条。</li>
 *   <li>素材像素是 <b>BGRA8888、直通（非预乘）alpha</b>。尾部预览位图同样是 BGRA。</li>
 *   <li>记录里的 {@code idx} 是**该类内序号**；锚 payload 的首字段也是类内序号。</li>
 *   <li>blob 头统一 12 字节：位图 {@code u32 0,u16 w,u16 h,u32 len}；
 *       数组 {@code u8 0,u8 图数,u16 0,u16 w,u16 h,u32 len}。</li>
 *   <li>小件 20 字节：{@code Value_Src(2 字节原样) + 位数 + 0x16 + u32 0 + u16 数组序号 + u16 0x0300 + u32 0 + u32 0}。</li>
 * </ul>
 */
public final class FaceBuilder {

    public static final int PREVIEW_W = 212;
    public static final int PREVIEW_H = 520;
    /** 无 AOD 时的索引表起点。 */
    public static final int INDEX_START = 272;
    /** 有 AOD 子工程时的索引表起点（元数据区多 88 字节）。 */
    public static final int INDEX_START_AOD = 360;

    private static final byte[] MAGIC = {(byte) 0x5A, (byte) 0xA5, 0x34, 0x12};
    private static final int INDEX_ENTRY_SIZE = 16;
    private static final int ID_LEN = 10;
    private static final int TITLE_LEN = 16;
    private static final int TAG_SENTINEL = 0x0500;

    /** 一个要打进 .face 的资源文件。name 形如 "lua/face_01.png"、"lua/main.lua"。 */
    public static final class FileEntry {
        public final String name;
        public final byte[] data;
        public FileEntry(String name, byte[] data) {
            this.name = name;
            this.data = data;
        }
    }

    /** AOD 描述块里的一条记录。payload 既是记录载荷、也是素材区里的那段字节。 */
    public static final class Rec {
        public final int idx;
        public final int tag;
        public final byte[] payload;
        public Rec(int idx, int tag, byte[] payload) {
            this.idx = idx;
            this.tag = tag;
            this.payload = payload;
        }
    }

    private FaceBuilder() {}

    /** 不带 AOD。 */
    public static byte[] build(String title, String faceId,
                               List<FileEntry> files, byte[] previewBgra) {
        return build(title, faceId, files, previewBgra, false, null);
    }

    /**
     * @param previewBgra 212*520*4 的预览位图，<b>BGRA</b> 序
     * @param hasAod      是否带息屏子工程（即使一个控件都没有也要置 true，元数据与屏数会变）
     * @param aodRecs     AOD 描述记录，可空
     */
    public static byte[] build(String title, String faceId,
                               List<FileEntry> files, byte[] previewBgra,
                               boolean hasAod, List<Rec> aodRecs) {
        final int n = files.size();
        final List<Rec> recs = aodRecs == null ? new ArrayList<Rec>() : aodRecs;
        final int idx = (hasAod ? INDEX_START_AOD : INDEX_START);
        final int d0 = idx + n * INDEX_ENTRY_SIZE;                 // 描述块起点
        final int ndesc = recs.size() + 1;                          // + 哨兵
        final int descEnd = d0 + ndesc * INDEX_ENTRY_SIZE;

        // ---- 主文件数据区（条目起点 4 字节对齐，末条也要补齐到 4 字节） ----
        int[] offsets = new int[n];
        int[] sizes = new int[n];
        int cur = descEnd;
        for (int i = 0; i < n; i++) {
            byte[] nb = files.get(i).name.getBytes(StandardCharsets.US_ASCII);
            int size = 20 + nb.length + files.get(i).data.length;
            offsets[i] = cur;
            sizes[i] = size;
            cur = align4(cur + size);
        }
        final int filesEnd = cur;                                   // 已 4 字节对齐

        // ---- AOD 素材区：紧随数据区（也即 4 字节对齐）；实排顺序 锚 → 小件 → 位图 → 数组 ----
        final int assetStart = filesEnd;
        int[] blobOff = new int[recs.size()];
        byte[] asset;
        {
            ByteArrayOutputStream a = new ByteArrayOutputStream();
            for (int k : assetOrder(recs)) {
                blobOff[k] = assetStart + a.size();
                a.write(recs.get(k).payload, 0, recs.get(k).payload.length);
            }
            asset = a.toByteArray();
        }
        final int assetsEnd = assetStart + asset.length;
        final int sentinelOff = d0 + (ndesc - 1) * INDEX_ENTRY_SIZE;

        // ---- 元数据 ----
        final int firstBitmap = firstRecOff(recs, 0x0200, d0);
        int firstNonAnchor = -1;
        for (int k = 0; k < recs.size(); k++) {
            if (recs.get(k).tag != 0x0000) { firstNonAnchor = d0 + k * INDEX_ENTRY_SIZE; break; }
        }
        final int A = firstBitmap >= 0 ? firstBitmap
                    : (firstNonAnchor >= 0 ? firstNonAnchor : sentinelOff);

        ByteArrayOutputStream o = new ByteArrayOutputStream();

        // 头部 64B
        o.write(MAGIC, 0, 4);
        o.write(0); o.write(0);                      // [4],[5] 实测都是 0
        zeros(o, 10);
        u32(o, 0x800);
        zeros(o, 8);
        u16(o, hasAod ? 2 : 1);                      // [28] 屏数
        u16(o, hasAod ? 4 : 0);                      // [30]
        u32(o, assetsEnd);                           // [32]
        zeros(o, 4);
        ascii(o, faceId, ID_LEN);
        zeros(o, 14);
        // Title 区
        zeros(o, 40);
        ascii(o, title, TITLE_LEN);
        zeros(o, 52);

        if (hasAod) {
            // [172,260) 主屏元数据 22 槽
            u32(o, assetsEnd); u32(o, 1); u32(o, idx - 16); u32(o, 0);
            u32(o, idx); u32(o, 0); u32(o, idx); u32(o, 0);
            u32(o, idx); u32(o, 0); u32(o, idx);
            u32(o, n); u32(o, idx); u32(o, 0);
            for (int k = 0; k < 4; k++) { u32(o, d0); u32(o, 0); }
            // [260,360) AOD 尾部 25 槽
            u32(o, 0xFFFFFFFF);
            u32(o, count(recs, 0x0000));
            u32(o, d0); u32(o, 0);
            u32(o, A); u32(o, count(recs, 0x0200));
            u32(o, A); u32(o, count(recs, 0x0300));
            u32(o, orSentinel(firstRecOff(recs, 0x0300, d0), sentinelOff)); u32(o, 0);
            int dOff = orSentinel(firstRecOff(recs, 0x0700, d0), sentinelOff);
            u32(o, dOff); u32(o, 0);
            u32(o, dOff); u32(o, 0);
            u32(o, dOff); u32(o, count(recs, 0x0700));
            u32(o, dOff); u32(o, 0);
            u32(o, sentinelOff); u32(o, 0);
            u32(o, sentinelOff); u32(o, 0);
            u32(o, 0);
            u32(o, sentinelOff);
            u32(o, INDEX_ENTRY_SIZE);
        } else {
            // 无条件分支（268 字节元数据）——与无 AOD 的历史产物逐字节一致
            u32(o, assetsEnd); u32(o, 1); u32(o, idx - 16); u32(o, 0);
            u32(o, idx); u32(o, 0); u32(o, idx); u32(o, 0);
            u32(o, idx); u32(o, 0); u32(o, idx);
            u32(o, n); u32(o, idx); u32(o, 0);
            for (int k = 0; k < 4; k++) { u32(o, d0); u32(o, 0); }
            u32(o, 0); u32(o, d0); u32(o, INDEX_ENTRY_SIZE);
        }

        // ---- 索引表（n 条） ----
        for (int i = 0; i < n; i++) {
            u16(o, i); u16(o, TAG_SENTINEL); u32(o, 0);
            u32(o, offsets[i]); u32(o, sizes[i]);
        }

        // ---- 描述块：有效记录 + 哨兵 ----
        for (int k = 0; k < recs.size(); k++) {
            Rec r = recs.get(k);
            u16(o, r.idx); u16(o, r.tag); u32(o, 0);
            u32(o, blobOff[k]); u32(o, r.payload.length);
        }
        u16(o, n - 1); u16(o, TAG_SENTINEL); u32(o, 0); u32(o, 0); u32(o, 0);

        // ---- 文件数据区 ----
        for (int i = 0; i < n; i++) {
            FileEntry fe = files.get(i);
            byte[] nb = fe.name.getBytes(StandardCharsets.US_ASCII);
            u24(o, fe.data.length);
            o.write(nb.length);
            zeros(o, 16);
            o.write(nb, 0, nb.length);
            o.write(fe.data, 0, fe.data.length);
            zeros(o, align4(offsets[i] + sizes[i]) - (offsets[i] + sizes[i]));
        }

        // ---- AOD 素材 + 尾部预览（BGRA） ----
        o.write(asset, 0, asset.length);
        zeros(o, 4);
        u16(o, PREVIEW_W);
        u16(o, PREVIEW_H);
        u32(o, previewBgra.length);
        o.write(previewBgra, 0, previewBgra.length);

        return o.toByteArray();
    }

    // ---- 内部 helper ----

    private static final int[] TAG_PRIORITY = {0x0000, 0x0700, 0x0200, 0x0300};

    /** 素材区实排顺序：锚 → 小件 → 位图 → 数组（同类保持相对次序）。 */
    private static int[] assetOrder(List<Rec> recs) {
        int[] order = new int[recs.size()];
        int w = 0;
        for (int tag : TAG_PRIORITY) {
            for (int k = 0; k < recs.size(); k++) {
                if (recs.get(k).tag == tag) order[w++] = k;
            }
        }
        for (int k = 0; k < recs.size(); k++) {          // 兜底：未知 tag 排在最后
            boolean seen = false;
            for (int j = 0; j < w; j++) if (order[j] == k) { seen = true; break; }
            if (!seen) order[w++] = k;
        }
        return order;
    }

    private static int firstRecOff(List<Rec> recs, int tag, int d0) {
        for (int k = 0; k < recs.size(); k++) {
            if (recs.get(k).tag == tag) return d0 + k * INDEX_ENTRY_SIZE;   // 绝对偏移
        }
        return -1;
    }

    private static int orSentinel(int v, int sentinelOff) {
        return v < 0 ? sentinelOff : v;
    }

    private static int count(List<Rec> recs, int tag) {
        int c = 0;
        for (Rec r : recs) if (r.tag == tag) c++;
        return c;
    }

    private static int align4(int x) { return x + ((4 - x % 4) % 4); }

    private static void u16(ByteArrayOutputStream o, int v) {
        o.write(v & 0xFF); o.write((v >>> 8) & 0xFF);
    }
    private static void u24(ByteArrayOutputStream o, int v) {
        o.write(v & 0xFF); o.write((v >>> 8) & 0xFF); o.write((v >>> 16) & 0xFF);
    }
    private static void u32(ByteArrayOutputStream o, int v) {
        o.write(v & 0xFF); o.write((v >>> 8) & 0xFF);
        o.write((v >>> 16) & 0xFF); o.write((v >>> 24) & 0xFF);
    }
    private static void zeros(ByteArrayOutputStream o, int n) {
        for (int i = 0; i < n; i++) o.write(0);
    }
    private static void ascii(ByteArrayOutputStream o, String s, int len) {
        byte[] b = s.getBytes(StandardCharsets.US_ASCII);
        for (int i = 0; i < len; i++) o.write(i < b.length ? b[i] : 0);
    }
}
