package face;

/**
 * 生成 main.lua 源码（全屏序列帧动画 + 时间日期叠加）。
 * 与 PC 端 Python 参考实现 lua.py 输出一致。
 */
public final class LuaGen {

    private LuaGen() {}

    public static String generate(int nFrames, int periodMs, boolean showTime) {
        return generate(nFrames, periodMs, showTime, "png");
    }

    public static String generate(int nFrames, int periodMs, boolean showTime, String ext) {
        String fpsDesc = periodMs > 0 ? String.format("%.1fFPS", 1000.0 / periodMs) : "static";
        StringBuilder sb = new StringBuilder();
        sb.append("-- 小米手环 11 动态表盘（序列帧 212x520）\n");
        sb.append("-- ").append(nFrames).append(" 帧 @ ").append(periodMs)
          .append("ms/帧 ≈ ").append(fpsDesc).append("\n");
        sb.append("local lvgl = require(\"lvgl\")\n");
        sb.append("local dataman = require(\"dataman\")\n\n");
        sb.append("local SCRIPT_PATH = rawget(_G, \"SCRIPT_PATH\") or \"\"\n\n");
        sb.append("local function imgPath(src)\n");
        sb.append("    return SCRIPT_PATH .. src\n");
        sb.append("end\n\n");
        sb.append("-- 根对象\n");
        sb.append("local root = lvgl.Object(nil, {\n");
        sb.append("    w = lvgl.HOR_RES(),\n");
        sb.append("    h = lvgl.VER_RES(),\n");
        sb.append("    bg_color = 0x000000,\n");
        sb.append("    bg_opa = lvgl.OPA(100),\n");
        sb.append("    border_width = 0,\n");
        sb.append("    pad_all = 0,\n");
        sb.append("})\n");
        sb.append("root:clear_flag(lvgl.FLAG.SCROLLABLE)\n");
        sb.append("root:add_flag(lvgl.FLAG.EVENT_BUBBLE)\n\n");
        sb.append("-- ===== 全屏序列帧动画 =====\n");
        sb.append("local FRAMES = {}\n");
        sb.append("for i = 1, ").append(nFrames).append(" do\n");
        sb.append("    FRAMES[i] = string.format(\"face_%02d.").append(ext).append("\", i)\n");
        sb.append("end\n");
        sb.append("local frameIndex = 1\n\n");
        sb.append("local animImg = root:Image { src = imgPath(FRAMES[1]) }\n");
        sb.append("animImg:set {\n");
        sb.append("    w = lvgl.HOR_RES(),\n");
        sb.append("    h = lvgl.VER_RES(),\n");
        sb.append("    align = { type = lvgl.ALIGN.TOP_MID, x_ofs = 0, y_ofs = 0 },\n");
        sb.append("}\n\n");
        sb.append("local animTimer = lvgl.Timer {\n");
        sb.append("    period = ").append(periodMs).append(",\n");
        sb.append("    cb = function(t)\n");
        sb.append("        frameIndex = frameIndex % #FRAMES + 1\n");
        sb.append("        animImg:set { src = imgPath(FRAMES[frameIndex]) }\n");
        sb.append("    end,\n");
        sb.append("}\n");
        if (showTime) {
            sb.append(timeBlock());
        }
        sb.append("-- ===== 生命周期钩子：切走暂停动画省电 =====\n");
        sb.append("pageOnPause = function()\n");
        sb.append("    if animTimer then pcall(function() animTimer:pause() end) end\n");
        sb.append("end\n\n");
        sb.append("pageOnResume = function()\n");
        sb.append("    if animTimer then pcall(function() animTimer:resume() end) end\n");
        sb.append("end\n");
        return sb.toString();
    }

    private static String timeBlock() {
        return "\n"
            + "-- ===== 时间标签（顶部居中，叠加在动图上）=====\n"
            + "local timeLabel = lvgl.Label(root, {\n"
            + "    text = \"00:00\",\n"
            + "    text_font = lvgl.Font(\"montserrat\", 48, \"normal\"),\n"
            + "    text_color = 0xFFFFFF,\n"
            + "    align = { type = lvgl.ALIGN.TOP_MID, y_ofs = 30 },\n"
            + "})\n\n"
            + "-- 日期标签\n"
            + "local dateLabel = lvgl.Label(root, {\n"
            + "    text = \"\",\n"
            + "    text_font = lvgl.Font(\"montserrat\", 16, \"normal\"),\n"
            + "    text_color = 0xEEEEEE,\n"
            + "    align = { type = lvgl.ALIGN.TOP_MID, y_ofs = 86 },\n"
            + "})\n\n"
            + "local function refreshTime()\n"
            + "    local t = os.time()\n"
            + "    timeLabel:set { text = os.date(\"%H:%M\", t) }\n"
            + "    dateLabel:set { text = os.date(\"%m/%d\", t) }\n"
            + "end\n\n"
            + "refreshTime()\n\n"
            + "dataman.subscribe(\"timeMinuteLow\", root, function(obj, value)\n"
            + "    refreshTime()\n"
            + "end)\n";
    }
}
