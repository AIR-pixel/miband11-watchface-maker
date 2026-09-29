package face;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * 纯代码生成小米手环 11 动态表盘 .face（零 Android 依赖，桌面 JVM / 真机都能编）。
 *
 * 格式已完整逆向（与 Python 参考实现 face_builder.py 逐字节等价）。
 * 全部小端序。
 */
public final class FaceBuilder {

    public static final int PREVIEW_W = 212;
    public static final int PREVIEW_H = 520;

    /** 一个要打进 .face 的资源文件。name 形如 "lua/face_01.png"、"lua/main.lua"。 */
    public static final class FileEntry {
        public final String name;
        public final byte[] data;
        public FileEntry(String name, byte[] data) {
            this.name = name;
            this.data = data;
        }
    }

    private static final byte[] MAGIC = {(byte) 0x5A, (byte) 0xA5, 0x34, 0x12};
    private static final int INDEX_START = 272;
    private static final int INDEX_ENTRY_SIZE = 16;
    private static final int ID_LEN = 10;
    private static final int TITLE_LEN = 16;

    private FaceBuilder() {}

    public static byte[] build(String title, String faceId,
                               List<FileEntry> files, byte[] previewRgba) {
        final int n = files.size();
        final int idxTableEnd = INDEX_START + (n + 1) * INDEX_ENTRY_SIZE;

        // 预计算每个文件项的 offset / size（size 不含 4 字节对齐 padding）
        int[] offsets = new int[n];
        int[] sizes = new int[n];
        int cur = idxTableEnd;
        for (int i = 0; i < n; i++) {
            byte[] nb = files.get(i).name.getBytes(StandardCharsets.US_ASCII);
            int size = 20 + nb.length + files.get(i).data.length;
            sizes[i] = size;
            offsets[i] = cur;
            cur += size + ((4 - size % 4) % 4);
        }
        final int dataEnd = cur;
        final int idxEnd = INDEX_START + n * INDEX_ENTRY_SIZE; // 有效索引表结束（不含哨兵）

        ByteArrayOutputStream o = new ByteArrayOutputStream();

        // ---- 文件头 64B ----
        o.write(MAGIC, 0, 4);
        o.write(0); o.write(ID_LEN);                 // [4]=0, [5]=ID 长度
        zeros(o, 10);                                // [6-15]
        u32(o, 0x800);                               // [16-19]
        zeros(o, 8);                                 // [20-27]
        u32(o, 1);                                   // [28-31]
        u32(o, dataEnd);                             // [32-35]
        zeros(o, 4);                                 // [36-39]
        ascii(o, faceId, ID_LEN);                    // [40-49]
        zeros(o, 14);                                // [50-63]

        // ---- Title 区 [64-119] ----
        zeros(o, 40);                                // [64-103]
        ascii(o, title, TITLE_LEN);                  // [104-119]
        zeros(o, 52);                                // [120-171]

        // ---- 元数据区 [172-271] ----
        u32(o, dataEnd);  u32(o, 1);  u32(o, 256);   u32(o, 0);
        u32(o, INDEX_START); u32(o, 0); u32(o, INDEX_START); u32(o, 0);
        u32(o, INDEX_START); u32(o, 0); u32(o, INDEX_START);
        u32(o, n);                                   // [216] 文件数
        u32(o, INDEX_START);
        u32(o, 0);
        u32(o, idxEnd); u32(o, 0);
        u32(o, idxEnd); u32(o, 0);
        u32(o, idxEnd); u32(o, 0);
        u32(o, idxEnd); u32(o, 0);
        u32(o, 0);
        u32(o, idxEnd);
        u32(o, INDEX_ENTRY_SIZE);

        // ---- 索引表 (n + 1 条，含哨兵) ----
        for (int i = 0; i < n; i++) {
            u16(o, i); u16(o, 0x0500); u32(o, 0);
            u32(o, offsets[i]); u32(o, sizes[i]);
        }
        u16(o, n - 1); u16(o, 0x0500); u32(o, 0); u32(o, 0); u32(o, 0); // 哨兵

        // ---- 文件数据区（4 字节对齐） ----
        for (int i = 0; i < n; i++) {
            FileEntry fe = files.get(i);
            byte[] nb = fe.name.getBytes(StandardCharsets.US_ASCII);
            u24(o, fe.data.length);
            o.write(nb.length);
            zeros(o, 16);
            o.write(nb, 0, nb.length);
            o.write(fe.data, 0, fe.data.length);
            zeros(o, (4 - sizes[i] % 4) % 4);
        }

        // ---- 尾部位图（预览图 RGBA8888） ----
        zeros(o, 4);
        u16(o, PREVIEW_W);
        u16(o, PREVIEW_H);
        u32(o, previewRgba.length);
        o.write(previewRgba, 0, previewRgba.length);

        return o.toByteArray();
    }

    // ---- 小端写 helper ----
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
        for (int i = 0; i < len; i++) {
            o.write(i < b.length ? b[i] : 0);
        }
    }
}
