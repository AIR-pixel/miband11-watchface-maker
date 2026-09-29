package face;

import java.io.ByteArrayOutputStream;
import java.util.zip.CRC32;
import java.util.zip.Deflater;

/**
 * 纯 Java PNG 编码器（零依赖，支持 P8 调色板与 RGB 真彩两种）。
 * 供桌面 JVM 与 Android 共用，用于把量化后的帧编码成 PNG 打进 .face。
 */
public final class PngEncoder {

    private PngEncoder() {}

    private static final byte[] SIG = {
        (byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A
    };

    /** P8 调色板 PNG。palette 每 3 字节一组 RGB，最多 256 色。indices 每像素 1 字节。 */
    public static byte[] encodeP8(int w, int h, byte[] palette, byte[] indices) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.write(SIG, 0, 8);

        // IHDR: bitdepth=8, colortype=3 (indexed)
        byte[] ihdr = new byte[13];
        putIntBE(ihdr, 0, w);
        putIntBE(ihdr, 4, h);
        ihdr[8] = 8; ihdr[9] = 3; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
        chunk(out, "IHDR", ihdr);

        // PLTE
        chunk(out, "PLTE", palette);

        // IDAT: 每行前加 filter byte 0
        int rowLen = 1 + w;                       // filter + indices
        byte[] raw = new byte[rowLen * h];
        for (int y = 0; y < h; y++) {
            raw[y * rowLen] = 0;
            System.arraycopy(indices, y * w, raw, y * rowLen + 1, w);
        }
        chunk(out, "IDAT", deflate(raw));

        chunk(out, "IEND", new byte[0]);
        return out.toByteArray();
    }

    /** RGB 真彩 PNG。rgb 每像素 3 字节。 */
    public static byte[] encodeRGB(int w, int h, byte[] rgb) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.write(SIG, 0, 8);

        byte[] ihdr = new byte[13];
        putIntBE(ihdr, 0, w);
        putIntBE(ihdr, 4, h);
        ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
        chunk(out, "IHDR", ihdr);

        int rowLen = 1 + w * 3;
        byte[] raw = new byte[rowLen * h];
        for (int y = 0; y < h; y++) {
            raw[y * rowLen] = 0;
            System.arraycopy(rgb, y * w * 3, raw, y * rowLen + 1, w * 3);
        }
        chunk(out, "IDAT", deflate(raw));

        chunk(out, "IEND", new byte[0]);
        return out.toByteArray();
    }

    private static void chunk(ByteArrayOutputStream out, String type, byte[] data) {
        byte[] t = type.getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        putIntBE4(out, data.length);
        out.write(t, 0, 4);
        out.write(data, 0, data.length);
        CRC32 crc = new CRC32();
        crc.update(t, 0, 4);
        crc.update(data, 0, data.length);
        putIntBE4(out, (int) crc.getValue());
    }

    private static byte[] deflate(byte[] in) {
        Deflater d = new Deflater();
        d.setInput(in);
        d.finish();
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] tmp = new byte[8192];
        while (!d.finished()) {
            int n = d.deflate(tmp);
            buf.write(tmp, 0, n);
        }
        d.end();
        return buf.toByteArray();
    }

    private static void putIntBE(byte[] b, int off, int v) {
        b[off] = (byte) (v >>> 24);
        b[off + 1] = (byte) (v >>> 16);
        b[off + 2] = (byte) (v >>> 8);
        b[off + 3] = (byte) v;
    }

    private static void putIntBE4(ByteArrayOutputStream o, int v) {
        o.write((v >>> 24) & 0xFF);
        o.write((v >>> 16) & 0xFF);
        o.write((v >>> 8) & 0xFF);
        o.write(v & 0xFF);
    }
}
