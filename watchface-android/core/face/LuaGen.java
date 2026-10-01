package face;

import java.util.ArrayList;
import java.util.List;

/**
 * 生成 main.lua。与 PC 端 Python 参考实现 {@code watchface_tool/lua.py} 输出**逐字节一致**
 * （12 例 × 20 字段差分，12/12 通过；12 份输出另经 {@code luaparser} 语法校验）。
 * 改动本文件后请重跑该差分 —— 参见 {@code docs/项目经验.md} 方法论第 5 条。
 *
 * <h2>壁纸与帧的命名</h2>
 * 第 1 张壁纸 {@code face_01.png…}，第 2 张起 {@code w2_01.png}、{@code w3_01.png}…
 * Lua 侧每张壁纸一个 Image + 一个 Timer，只显示/运行当前那张。
 *
 * <h2>为什么同时要 pageOnPause 和 ScreenStateChangedCB</h2>
 * 只剩 {@code pageOnPause} 不够：**进 AOD 时表盘页面并没有被切走**，这个钩子很可能不触发，
 * 动画会在息屏下继续跑，续航直接崩。框架给的正确信号是全局回调
 * {@code ScreenStateChangedCB(pre, now, reason)}（官方表盘 {@code smash.lua}、社区
 * {@code FlyingCat} 都在用）。两个都保留：前者管切页、后者兜息屏。
 *
 * <p><b>顺序不能动</b>：省电块必须在点击块之前 —— 点击处理要用到 {@code pauseAll}/
 * {@code resumeActive}（Lua 里是 local，声明在后会被解析成 nil）。
 */
public final class LuaGen {

    private LuaGen() {}

    /** 一张壁纸：资源前缀 + 帧数 + 每帧毫秒。 */
    public static final class Wall {
        public final String prefix;
        public final int count;
        public final int periodMs;

        public Wall(String prefix, int count, int periodMs) {
            this.prefix = prefix;
            this.count = count;
            this.periodMs = periodMs;
        }
    }

    /** 全部可配项。默认值与 Python 端 {@code generate_lua} 的形参默认值一致。 */
    public static final class Opts {
        /** 空表示退回单张 face 壁纸。 */
        public List<Wall> walls = new ArrayList<Wall>();
        /** 仅用于注释里的帧率描述。 */
        public int periodMs;
        public String ext = "png";
        /** 为空则自动生成 "%d 张壁纸 / 共 %d 帧"。 */
        public String fpsDesc;

        public boolean showTime = true;
        public boolean showDate = false;

        public String timeAlign = "TOP_MID";
        public int timeX = 0, timeY = 30;
        public int timeSize = 48;
        public int timeColor = 0xFFFFFF;
        public String timeFmt = "%H:%M";

        public String dateAlign = "TOP_MID";
        public int dateX = 0, dateY = 86;
        public int dateSize = 16;
        public int dateColor = 0xEEEEEE;
        public String dateFmt = "%m/%d";

        /** none / cycle / info / anim。 */
        public String tapAction = "none";
    }

    /** 旧签名：单壁纸 + 单一时间日期开关。 */
    public static String generate(int nFrames, int periodMs, boolean showTime, String ext) {
        Opts o = new Opts();
        o.walls.add(new Wall("face", nFrames, periodMs));
        o.periodMs = periodMs;
        o.ext = ext;
        o.showTime = showTime;
        o.showDate = false;
        return generate(o);
    }

    public static String generate(int nFrames, int periodMs, boolean showTime) {
        return generate(nFrames, periodMs, showTime, "png");
    }

    public static String generate(Opts o) {
        List<Wall> walls = new ArrayList<Wall>(o.walls);
        if (walls.isEmpty()) {
            walls.add(new Wall("face", 1, o.periodMs));
        }
        boolean showTime = o.showTime;
        boolean showDate = o.showDate;
        String tap = o.tapAction == null ? "none" : o.tapAction;
        if ("cycle".equals(tap) && walls.size() < 2) tap = "none";   // 只有一张壁纸，切换没意义

        String desc = o.fpsDesc != null && !o.fpsDesc.isEmpty()
                    ? o.fpsDesc
                    : String.format("%d 张壁纸 / 首张 %d 帧", walls.size(), walls.get(0).count);

        StringBuilder out = new StringBuilder();
        out.append(_HEAD.replace("@DESC@", desc));

        StringBuilder rows = new StringBuilder();
        for (int i = 0; i < walls.size(); i++) {
            Wall w = walls.get(i);
            if (i > 0) rows.append('\n');
            rows.append(String.format("    { prefix = \"%s\", count = %d, period = %d },",
                                      w.prefix, w.count, w.periodMs));
        }
        out.append(_WALL.replace("@NW@", String.valueOf(walls.size()))
                        .replace("@EXT@", o.ext)
                        .replace("@WALLTABLE@", rows.toString()));

        // ---- 时间 / 日期 ----
        if (showTime || showDate) {
            StringBuilder decls = new StringBuilder(), body = new StringBuilder(), vis = new StringBuilder();
            boolean firstBody = true, firstVis = true;
            if (showTime) {
                decls.append(labelDecl("timeLabel", o.timeAlign, o.timeX, o.timeY,
                                       o.timeSize, o.timeColor));
                if (!firstBody) body.append('\n');
                body.append("    timeLabel:set { text = os.date(\"").append(o.timeFmt).append("\", t) }");
                firstBody = false;
                if (!firstVis) vis.append('\n');
                vis.append(visLine("timeLabel", "v"));
                firstVis = false;
            }
            if (showDate) {
                decls.append(labelDecl("dateLabel", o.dateAlign, o.dateX, o.dateY,
                                       o.dateSize, o.dateColor));
                if (!firstBody) body.append('\n');
                body.append("    dateLabel:set { text = os.date(\"").append(o.dateFmt).append("\", t) }");
                firstBody = false;
                if (!firstVis) vis.append('\n');
                vis.append(visLine("dateLabel", "v"));
                firstVis = false;
            }
            out.append(_INFO.replace("@DECLS@", decls.toString())
                            .replace("@REFRESH@", "    local t = os.time()\n" + body)
                            .replace("@VIS@", vis.toString()));
        }

        // ---- 省电钩子（必须在点击处理之前）----
        out.append(_POWER);

        // ---- 点击交互 ----
        String tapDesc = null, tapBody = null;
        if ("cycle".equals(tap)) {
            tapDesc = "短按切换壁纸";
            tapBody = "    if #wallObjs > 1 then\n"
                    + "        showWall(activeWall % #wallObjs + 1)\n"
                    + "    end";
        } else if ("info".equals(tap) && (showTime || showDate)) {
            tapDesc = "短按显示 / 隐藏时间日期";
            tapBody = "    setInfoVisible(not infoVisible)";
        } else if ("anim".equals(tap)) {
            tapDesc = "短按暂停 / 继续动画";
            tapBody = "    animPaused = not animPaused\n"
                    + "    if animPaused then pauseAll() else resumeActive() end";
        }
        if (tapDesc != null) {
            out.append(_TAP.replace("@TAPDESC@", tapDesc).replace("@TAPBODY@", tapBody));
        }
        return out.toString();
    }

    // ---- 片段 ----

    private static String labelDecl(String name, String align, int x, int y, int size, int color) {
        return "local " + name + " = lvgl.Label(root, {\n"
             + "    text = \"\",\n"
             + "    text_font = lvgl.Font(\"montserrat\", " + size + ", \"normal\"),\n"
             + "    text_color = 0x" + String.format("%06X", color) + ",\n"
             + "    align = { type = lvgl.ALIGN." + align + ", x_ofs = " + x + ", y_ofs = " + y + " },\n"
             + "})\n";
    }

    /** 生成一行显隐控制。 */
    private static String visLine(String var, String value) {
        return "    if " + var + " then\n"
             + "        if " + value + " then " + var + ":clear_flag(lvgl.FLAG.HIDDEN) "
             + "else " + var + ":add_flag(lvgl.FLAG.HIDDEN) end\n"
             + "    end";
    }

    private static final String _HEAD =
        "-- 小米手环 11 动态表盘\n"
      + "-- @DESC@\n"
      + "local lvgl = require(\"lvgl\")\n"
      + "local dataman = require(\"dataman\")\n"
      + "\n"
      + "local SCRIPT_PATH = rawget(_G, \"SCRIPT_PATH\") or \"\"\n"
      + "\n"
      + "local function imgPath(src)\n"
      + "    return SCRIPT_PATH .. src\n"
      + "end\n"
      + "\n"
      + "-- 根对象\n"
      + "local root = lvgl.Object(nil, {\n"
      + "    w = lvgl.HOR_RES(),\n"
      + "    h = lvgl.VER_RES(),\n"
      + "    bg_color = 0x000000,\n"
      + "    bg_opa = lvgl.OPA(100),\n"
      + "    border_width = 0,\n"
      + "    pad_all = 0,\n"
      + "})\n"
      + "root:clear_flag(lvgl.FLAG.SCROLLABLE)\n"
      + "root:add_flag(lvgl.FLAG.EVENT_BUBBLE)\n";

    private static final String _WALL =
        "\n-- ===== 壁纸（@NW@ 张，点击可切换）=====\n"
      + "local EXT = \"@EXT@\"\n"
      + "local WALLS = {\n"
      + "@WALLTABLE@\n"
      + "}\n"
      + "local wallObjs = {}\n"
      + "local activeWall = 1\n"
      + "\n"
      + "for wi, w in ipairs(WALLS) do\n"
      + "    local srcs = {}\n"
      + "    for i = 1, w.count do\n"
      + "        srcs[i] = imgPath(string.format(\"%s_%02d.\" .. EXT, w.prefix, i))\n"
      + "    end\n"
      + "    w.srcs = srcs\n"
      + "    w.cur = 1\n"
      + "\n"
      + "    local img = root:Image { src = srcs[1] }\n"
      + "    img:set {\n"
      + "        w = lvgl.HOR_RES(),\n"
      + "        h = lvgl.VER_RES(),\n"
      + "        align = { type = lvgl.ALIGN.TOP_MID, x_ofs = 0, y_ofs = 0 },\n"
      + "    }\n"
      + "    if wi ~= 1 then img:add_flag(lvgl.FLAG.HIDDEN) end\n"
      + "\n"
      + "    local timer = lvgl.Timer {\n"
      + "        period = w.period,\n"
      + "        cb = function()\n"
      + "            w.cur = w.cur % #srcs + 1\n"
      + "            img:set { src = srcs[w.cur] }\n"
      + "        end,\n"
      + "    }\n"
      + "    if wi ~= 1 then pcall(function() timer:pause() end) end\n"
      + "\n"
      + "    wallObjs[wi] = { img = img, timer = timer }\n"
      + "end\n"
      + "\n"
      + "local function showWall(k)\n"
      + "    if k < 1 or k > #wallObjs then return end\n"
      + "    for i, o in ipairs(wallObjs) do\n"
      + "        if i == k then\n"
      + "            o.img:clear_flag(lvgl.FLAG.HIDDEN)\n"
      + "            pcall(function() o.timer:resume() end)\n"
      + "        else\n"
      + "            o.img:add_flag(lvgl.FLAG.HIDDEN)\n"
      + "            pcall(function() o.timer:pause() end)\n"
      + "        end\n"
      + "    end\n"
      + "    activeWall = k\n"
      + "end\n";

    private static final String _INFO =
        "\n-- ===== 时间 / 日期（叠加在动图上，位置由工具生成）=====\n"
      + "local infoVisible = true\n"
      + "@DECLS@\n"
      + "local function refreshTime()\n"
      + "@REFRESH@\n"
      + "end\n"
      + "\n"
      + "refreshTime()\n"
      + "pcall(function()\n"
      + "    dataman.subscribe(\"timeMinuteLow\", root, function(obj, value)\n"
      + "        refreshTime()\n"
      + "    end)\n"
      + "end)\n"
      + "\n"
      + "local function setInfoVisible(v)\n"
      + "    infoVisible = v\n"
      + "@VIS@\n"
      + "end\n";

    private static final String _POWER =
        "\n-- ===== 省电：切页 + 息屏双钩子 =====\n"
      + "-- pageOnPause/Resume 负责\"切走表盘页\"；进 AOD 时页面没被切走，\n"
      + "-- 必须靠框架级的 ScreenStateChangedCB —— 否则动画在息屏下继续跑。\n"
      + "local animPaused = false\n"
      + "\n"
      + "local function pauseAll()\n"
      + "    for _, o in ipairs(wallObjs) do\n"
      + "        pcall(function() o.timer:pause() end)\n"
      + "    end\n"
      + "end\n"
      + "\n"
      + "local function resumeActive()\n"
      + "    local o = wallObjs[activeWall]\n"
      + "    if o then pcall(function() o.timer:resume() end) end\n"
      + "end\n"
      + "\n"
      + "pageOnPause = function()\n"
      + "    pauseAll()\n"
      + "end\n"
      + "\n"
      + "pageOnResume = function()\n"
      + "    if animPaused then return end\n"
      + "    resumeActive()\n"
      + "end\n"
      + "\n"
      + "function ScreenStateChangedCB(pre, now, reason)\n"
      + "    if pre ~= \"ON\" and now == \"ON\" then\n"
      + "        if not animPaused then resumeActive() end\n"
      + "    elseif pre == \"ON\" and now ~= \"ON\" then\n"
      + "        pauseAll()\n"
      + "    end\n"
      + "end\n";

    private static final String _TAP =
        "\n-- ===== 点击交互：@TAPDESC@ =====\n"
      + "root:add_flag(lvgl.FLAG.CLICKABLE)\n"
      + "\n"
      + "root:onevent(lvgl.EVENT.SHORT_CLICKED, function(obj, code)\n"
      + "@TAPBODY@\n"
      + "end)\n";
}
