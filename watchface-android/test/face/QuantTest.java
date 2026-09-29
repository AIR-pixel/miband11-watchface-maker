package face;

import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;

/** 桌面验证：读 PNG → 量化 → 编码 P8 PNG 落盘，供外部（PIL）校验合法性。 */
public final class QuantTest {

    public static void main(String[] args) throws Exception {
        String in = args[0];
        String out = args[1];
        int colors = args.length > 2 ? Integer.parseInt(args[2]) : 256;
        boolean dither = args.length <= 3 || !"0".equals(args[3]);

        BufferedImage img = ImageIO.read(new File(in));
        int w = img.getWidth(), h = img.getHeight();
        int[] rgb = new int[w * h];
        img.getRGB(0, 0, w, h, rgb, 0, w);
        for (int i = 0; i < rgb.length; i++) rgb[i] &= 0xFFFFFF; // 去 alpha

        long t0 = System.currentTimeMillis();
        Quantizer.Result r = Quantizer.quantize(rgb, w, h, colors, dither);
        byte[] png = PngEncoder.encodeP8(w, h, r.palette, r.indices);
        long ms = System.currentTimeMillis() - t0;

        java.nio.file.Files.write(java.nio.file.Paths.get(out), png);
        System.out.println("输入 " + w + "x" + h + " 色彩=" + colors + " dither=" + dither
            + " 调色板=" + (r.palette.length / 3) + " 色 PNG=" + png.length + "B 耗时=" + ms + "ms");
    }
}
