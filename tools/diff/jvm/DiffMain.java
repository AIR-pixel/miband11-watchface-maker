import face.AodGen;
import face.FaceBuilder;
import face.LuaGen;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 跨语言差分回归 —— **JVM 侧**。
 *
 * 跟 Python 侧（tools/diff/reference.py + 生产模块）用**同一份用例表**各跑一遍，
 * 产物交给 tools/diff_face.py 逐字节比对。
 *
 * 用法（由 tools/diff_face.py 调用，一般不手跑）：
 *     java -cp &lt;classes&gt; DiffMain lua  &lt;luaCases&gt;  &lt;outDir&gt;
 *     java -cp &lt;classes&gt; DiffMain aod  &lt;aodCases&gt;  &lt;outDir&gt;
 *     java -cp &lt;classes&gt; DiffMain asm  &lt;asmCases&gt;  &lt;outDir&gt; &lt;aodCases&gt;
 *
 * 编译：
 *     javac -d &lt;out&gt; watchface-android/core/face/*.java tools/diff/jvm/DiffMain.java
 *
 * ⚠️ 本文件里的**用例表字段定义**与**装配素材生成规则**必须与 Python 侧一字不差，
 *    改任何一边都要同步改另一边 —— 否则比的是两套不同的输入，差分就没意义了。
 */
public final class DiffMain {

    // ------------------------------------------------------------------ 装配素材

    /**
     * 装配用例的「主文件清单」生成规则（Python 侧 reference.py 的 files_for() 必须一致）。
     *
     * 名字与长度都是 k 的确定函数，最后一个文件额外加 extraLast 字节 ——
     * extraLast 就是用来把「文件数据区总长」的模 4 余数走遍 0/1/2/3 的，
     * 那正是「尾部对齐只做了一半」那个 bug 的触发条件。
     */
    static List<FaceBuilder.FileEntry> filesFor(int nFiles, int extraLast) {
        List<FaceBuilder.FileEntry> out = new ArrayList<FaceBuilder.FileEntry>();
        for (int k = 0; k < nFiles; k++) {
            int len = 41 + 13 * k + (k == nFiles - 1 ? extraLast : 0);
            byte[] data = new byte[len];
            for (int i = 0; i < len; i++) data[i] = (byte) ((k * 37 + i * 7) & 0xFF);
            out.add(new FaceBuilder.FileEntry(String.format("lua/f%02d.bin", k), data));
        }
        return out;
    }

    /** 预览位图（212*520*4，BGRA）。规则同样必须与 Python 侧一致。 */
    static byte[] previewFor() {
        byte[] p = new byte[FaceBuilder.PREVIEW_W * FaceBuilder.PREVIEW_H * 4];
        for (int i = 0; i < p.length; i++) p[i] = (byte) ((i * 11 + 7) & 0xFF);
        return p;
    }

    static final String TITLE = "DiffDemo";
    static final String FACE_ID = "99887766";

    // ------------------------------------------------------------------ 用例解析

    static List<String[]> rows(Path cases) throws Exception {
        List<String[]> out = new ArrayList<String[]>();
        for (String raw : Files.readAllLines(cases, StandardCharsets.UTF_8)) {
            String t = raw.trim();
            if (t.isEmpty() || t.startsWith("#")) continue;
            out.add(raw.split("\\|", -1));
        }
        return out;
    }

    static LuaGen.Opts luaOpts(String[] p) {
        LuaGen.Opts o = new LuaGen.Opts();
        if (!p[1].isEmpty()) {
            for (String w : p[1].split(",")) {
                String[] t = w.split(":");
                o.walls.add(new LuaGen.Wall(t[0], Integer.parseInt(t[1]), Integer.parseInt(t[2])));
            }
        }
        o.periodMs = Integer.parseInt(p[2]);
        o.ext = p[3];
        o.showTime = "1".equals(p[4]);
        o.showDate = "1".equals(p[5]);
        o.timeAlign = p[6];
        o.timeX = Integer.parseInt(p[7]);
        o.timeY = Integer.parseInt(p[8]);
        o.timeSize = Integer.parseInt(p[9]);
        o.timeColor = Integer.decode(p[10]);
        o.timeFmt = p[11];
        o.dateAlign = p[12];
        o.dateX = Integer.parseInt(p[13]);
        o.dateY = Integer.parseInt(p[14]);
        o.dateSize = Integer.parseInt(p[15]);
        o.dateColor = Integer.decode(p[16]);
        o.dateFmt = p[17];
        o.tapAction = p[18];
        o.fpsDesc = p[19].isEmpty() ? null : p[19];
        return o;
    }

    static AodGen.Cfg aodCfg(String[] f) {
        AodGen.Cfg c = new AodGen.Cfg();
        c.enabled = "1".equals(f[1]);
        c.bgMode = f[2];
        c.hasCustomBg = "1".equals(f[3]);
        c.timeMode = f[4];
        c.timeY = Integer.parseInt(f[5]);
        c.dateY = Integer.parseInt(f[6]);
        c.color = f[7];
        c.timeDigitW = Integer.parseInt(f[8]);
        c.timeDigitH = Integer.parseInt(f[9]);
        c.dateDigitW = Integer.parseInt(f[10]);
        c.dateDigitH = Integer.parseInt(f[11]);
        c.colonW = Integer.parseInt(f[12]);
        return c;
    }

    /** 零像素素材：两边都不需要真像素，尺寸对上即可（像素字节的搬运是平凡逻辑）。 */
    static Map<String, AodGen.Img> zeroImages(List<AodGen.Widget> ws) {
        Map<String, AodGen.Img> m = new LinkedHashMap<String, AodGen.Img>();
        for (Map.Entry<String, int[]> e : AodGen.neededImages(ws).entrySet()) {
            int w = e.getValue()[0], h = e.getValue()[1];
            m.put(e.getKey(), new AodGen.Img(w, h, new byte[w * h * 4]));
        }
        return m;
    }

    /** 控件表 + 描述记录的规范文本（Python 侧 canon() 必须产出同样的行）。 */
    static String canon(List<AodGen.Widget> ws, List<FaceBuilder.Rec> recs) {
        StringBuilder s = new StringBuilder();
        for (AodGen.Widget w : ws) {
            if (w.kind == 30) {
                s.append(String.format("W|30|%s|%d|%d|%d|%d||||%s%n",
                        w.name, w.x, w.y, w.w, w.h, w.img));
            } else {
                StringBuilder l = new StringBuilder();
                for (int i = 0; i < w.bitmapList.size(); i++) {
                    if (i > 0) l.append(',');
                    l.append(w.bitmapList.get(i));
                }
                s.append(String.format("W|32|%s|%d|%d|%d|%d|%d|%s||%s%n",
                        w.name, w.x, w.y, w.digitW * w.digits, w.digitH,
                        w.digits, w.valueSrc, l));
            }
        }
        for (FaceBuilder.Rec r : recs) {
            s.append(String.format("R|%d|%d|%d|%s%n", r.idx, r.tag, r.payload.length, hex(r.payload)));
        }
        return s.toString();
    }

    static String hex(byte[] b) {
        StringBuilder s = new StringBuilder(b.length * 2);
        for (byte x : b) s.append(String.format("%02x", x));
        return s.toString();
    }

    // ------------------------------------------------------------------ 主流程

    public static void main(String[] a) throws Exception {
        String mode = a[0];
        Path cases = Paths.get(a[1]);
        Path out = Paths.get(a[2]);
        Files.createDirectories(out);

        if (mode.equals("lua")) {
            runLua(cases, out);
        } else if (mode.equals("aod")) {
            runAod(cases, out);
        } else if (mode.equals("asm")) {
            runAsm(cases, Paths.get(a[3]), out);
        } else {
            System.out.println("未知模式 " + mode);
            System.exit(2);
        }
    }

    static void runLua(Path cases, Path out) throws Exception {
        int n = 0;
        for (String[] p : rows(cases)) {
            if (p.length != 20) throw new IllegalStateException("lua 用例字段数 " + p.length);
            byte[] made = LuaGen.generate(luaOpts(p)).getBytes(StandardCharsets.UTF_8);
            Files.write(out.resolve(p[0] + ".lua"), made);
            n++;
        }
        System.out.printf("  java: lua %d 份%n", n);
    }

    static void runAod(Path cases, Path out) throws Exception {
        int n = 0;
        for (String[] f : rows(cases)) {
            if (f.length != 13) throw new IllegalStateException("aod 用例字段数 " + f.length);
            AodGen.Cfg c = aodCfg(f);
            String got;
            if (!c.enabled) {
                got = "";                       // 没有 AOD 子工程
            } else {
                List<AodGen.Widget> ws = AodGen.planAll(c);
                got = canon(ws, AodGen.buildRecords(ws, zeroImages(ws)));
            }
            Files.write(out.resolve(f[0] + ".txt"), got.getBytes(StandardCharsets.UTF_8));
            n++;
        }
        System.out.printf("  java: aod %d 份%n", n);
    }

    static void runAsm(Path cases, Path aodCases, Path out) throws Exception {
        Map<String, String[]> aodByName = new LinkedHashMap<String, String[]>();
        for (String[] f : rows(aodCases)) aodByName.put(f[0], f);

        int n = 0;
        for (String[] p : rows(cases)) {
            if (p.length != 5) throw new IllegalStateException("asm 用例字段数 " + p.length);
            String name = p[0];
            boolean hasAod = "1".equals(p[1]);
            int nFiles = Integer.parseInt(p[3]);
            int extraLast = Integer.parseInt(p[4]);

            List<FaceBuilder.FileEntry> files = filesFor(nFiles, extraLast);
            byte[] preview = previewFor();

            byte[] made;
            if (hasAod) {
                String[] f = aodByName.get(p[2]);
                if (f == null) throw new IllegalStateException("asm 引用了不存在的 aod 用例 " + p[2]);
                AodGen.Cfg c = aodCfg(f);
                List<AodGen.Widget> ws = AodGen.planAll(c);
                made = FaceBuilder.build(TITLE, FACE_ID, files, preview, true,
                        AodGen.buildRecords(ws, zeroImages(ws)));
            } else {
                made = FaceBuilder.build(TITLE, FACE_ID, files, preview);
            }
            Files.write(out.resolve(name + ".face"), made);
            n++;
        }
        System.out.printf("  java: asm %d 份%n", n);
    }
}
