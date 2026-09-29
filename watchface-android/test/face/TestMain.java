package face;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

/**
 * 桌面 JVM 验证：从样本 .face 解析 → FaceBuilder 重建 → 逐字节对比。
 * 也顺带打印 LuaGen 输出长度，供和 PC 端对比。
 */
public final class TestMain {

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.out.println("用法: TestMain <样本.face>");
            return;
        }
        byte[] data = Files.readAllBytes(Paths.get(args[0]));

        String title = asciiTrim(data, 104, 16);
        String faceId = asciiTrim(data, 40, 10);
        int n = u32(data, 216);
        int dataEnd = u32(data, 32);

        List<FaceBuilder.FileEntry> files = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            int off = 272 + i * 16;
            int eoff = u32(data, off + 8);
            int esize = u32(data, off + 12);
            int fnlen = data[eoff + 3] & 0xFF;
            String fn = new String(data, eoff + 20, fnlen, "US-ASCII");
            int dsize = esize - 20 - fnlen;
            byte[] payload = new byte[dsize];
            System.arraycopy(data, eoff + 20 + fnlen, payload, 0, dsize);
            files.add(new FaceBuilder.FileEntry(fn, payload));
        }
        byte[] rgba = new byte[data.length - (dataEnd + 12)];
        System.arraycopy(data, dataEnd + 12, rgba, 0, rgba.length);

        byte[] rebuilt = FaceBuilder.build(title, faceId, files, rgba);

        boolean same = java.util.Arrays.equals(rebuilt, data);
        System.out.println("title=" + title + " id=" + faceId + " files=" + n);
        System.out.println("rebuilt=" + rebuilt.length + " orig=" + data.length + " 逐字节一致=" + same);
        if (!same) {
            int m = Math.min(rebuilt.length, data.length);
            int first = -1;
            for (int i = 0; i < m; i++) {
                if (rebuilt[i] != data[i]) { first = i; break; }
            }
            System.out.println("首个差异@" + (first < 0 ? "长度" : Integer.toHexString(first)) +
                (first >= 0 ? String.format(" rebuilt=%02x orig=%02x", rebuilt[first], data[first]) : ""));
        }

        // LuaGen 输出长度（对比 PC 端）
        String lua = LuaGen.generate(46, 42, true);
        System.out.println("LuaGen(46,42) 长度=" + lua.getBytes("UTF-8").length);
    }

    static int u32(byte[] b, int off) {
        return (b[off] & 0xFF) | ((b[off + 1] & 0xFF) << 8)
             | ((b[off + 2] & 0xFF) << 16) | ((b[off + 3] & 0xFF) << 24);
    }

    static String asciiTrim(byte[] b, int off, int len) {
        int end = off + len;
        while (end > off && b[end - 1] == 0) end--;
        return new String(b, off, end - off, java.nio.charset.StandardCharsets.US_ASCII);
    }
}
