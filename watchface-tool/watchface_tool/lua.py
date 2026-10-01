# -*- coding: utf-8 -*-
"""生成 main.lua：全屏序列帧动画 + 时间/日期叠加 + 点击交互 + 省电钩子。

## 为什么改掉了 pageOnPause

老版本只靠 `pageOnPause/pageOnResume` 停定时器。但**进 AOD 时表盘页面并没有被切走**，
这个钩子很可能不触发 → 动画在息屏下继续跑，续航直接崩。
框架给的正确信号是全局回调 `ScreenStateChangedCB(pre, now, reason)`
（官方表盘 `smash.lua`、社区 `FlyingCat` 都在用）。

现在两个都保留：`pageOnPause/Resume` 兼容切页，`ScreenStateChangedCB` 兜息屏。

## 壁纸与帧的命名

- 第 1 张壁纸：`face_01.png`…（与单壁纸版本字节级一致，保持向后兼容）
- 第 2 张起：`w2_01.png`、`w3_01.png`…

Lua 侧每张壁纸一个 Image + 一个 Timer，只显示/运行当前那张。
"""
from .constants import SCREEN_H, SCREEN_W

_HEAD = """-- 小米手环 11 动态表盘
-- {desc}
local lvgl = require("lvgl")
local dataman = require("dataman")

local SCRIPT_PATH = rawget(_G, "SCRIPT_PATH") or ""

local function imgPath(src)
    return SCRIPT_PATH .. src
end

-- 根对象
local root = lvgl.Object(nil, {{
    w = lvgl.HOR_RES(),
    h = lvgl.VER_RES(),
    bg_color = 0x000000,
    bg_opa = lvgl.OPA(100),
    border_width = 0,
    pad_all = 0,
}})
root:clear_flag(lvgl.FLAG.SCROLLABLE)
root:add_flag(lvgl.FLAG.EVENT_BUBBLE)
"""

_WALL_BLOCK = """
-- ===== 壁纸（{n_walls} 张，点击可切换）=====
local EXT = "{ext}"
local WALLS = {{
{wall_table}
}}
local wallObjs = {{}}
local activeWall = 1

for wi, w in ipairs(WALLS) do
    local srcs = {{}}
    for i = 1, w.count do
        srcs[i] = imgPath(string.format("%s_%02d." .. EXT, w.prefix, i))
    end
    w.srcs = srcs
    w.cur = 1

    local img = root:Image {{ src = srcs[1] }}
    img:set {{
        w = lvgl.HOR_RES(),
        h = lvgl.VER_RES(),
        align = {{ type = lvgl.ALIGN.TOP_MID, x_ofs = 0, y_ofs = 0 }},
    }}
    if wi ~= 1 then img:add_flag(lvgl.FLAG.HIDDEN) end

    local timer = lvgl.Timer {{
        period = w.period,
        cb = function()
            w.cur = w.cur % #srcs + 1
            img:set {{ src = srcs[w.cur] }}
        end,
    }}
    if wi ~= 1 then pcall(function() timer:pause() end) end

    wallObjs[wi] = {{ img = img, timer = timer }}
end

local function showWall(k)
    if k < 1 or k > #wallObjs then return end
    for i, o in ipairs(wallObjs) do
        if i == k then
            o.img:clear_flag(lvgl.FLAG.HIDDEN)
            pcall(function() o.timer:resume() end)
        else
            o.img:add_flag(lvgl.FLAG.HIDDEN)
            pcall(function() o.timer:pause() end)
        end
    end
    activeWall = k
end
"""

_INFO_BLOCK = """
-- ===== 时间 / 日期（叠加在动图上，位置由工具生成）=====
local infoVisible = true
{decls}
local function refreshTime()
{refresh_body}
end

refreshTime()
pcall(function()
    dataman.subscribe("timeMinuteLow", root, function(obj, value)
        refreshTime()
    end)
end)

local function setInfoVisible(v)
    infoVisible = v
{vis_body}
end
"""

_TAP_BLOCK = """
-- ===== 点击交互：{tap_desc} =====
root:add_flag(lvgl.FLAG.CLICKABLE)

root:onevent(lvgl.EVENT.SHORT_CLICKED, function(obj, code)
{tap_body}
end)
"""

_POWER_BLOCK = """
-- ===== 省电：切页 + 息屏双钩子 =====
-- pageOnPause/Resume 负责"切走表盘页"；进 AOD 时页面没被切走，
-- 必须靠框架级的 ScreenStateChangedCB —— 否则动画在息屏下继续跑。
local animPaused = false

local function pauseAll()
    for _, o in ipairs(wallObjs) do
        pcall(function() o.timer:pause() end)
    end
end

local function resumeActive()
    local o = wallObjs[activeWall]
    if o then pcall(function() o.timer:resume() end) end
end

pageOnPause = function()
    pauseAll()
end

pageOnResume = function()
    if animPaused then return end
    resumeActive()
end

function ScreenStateChangedCB(pre, now, reason)
    if pre ~= "ON" and now == "ON" then
        if not animPaused then resumeActive() end
    elseif pre == "ON" and now ~= "ON" then
        pauseAll()
    end
end
"""


def _label_decl(name, align, ofs, size, color):
    return ('local %s = lvgl.Label(root, {\n'
            '    text = "",\n'
            '    text_font = lvgl.Font("montserrat", %d, "normal"),\n'
            '    text_color = 0x%06X,\n'
            '    align = { type = lvgl.ALIGN.%s, x_ofs = %d, y_ofs = %d },\n'
            '})\n' % (name, size, color, align, ofs[0], ofs[1]))


def _vis_line(var, value):
    """生成一行显隐控制。"""
    return ('    if %s then\n'
            '        if %s then %s:clear_flag(lvgl.FLAG.HIDDEN) '
            'else %s:add_flag(lvgl.FLAG.HIDDEN) end\n'
            '    end' % (var, value, var, var))


def generate_lua(walls, period_ms, ext="png", show_time=True, show_date=False,
                 time_align="TOP_MID", time_ofs=(0, 30), time_size=48,
                 time_color=0xFFFFFF, time_fmt="%H:%M",
                 date_align="TOP_MID", date_ofs=(0, 86), date_size=16,
                 date_color=0xEEEEEE, date_fmt="%m/%d",
                 tap_action="none", fps_desc=None):
    """生成 main.lua。

    walls: [{prefix, count, period_ms}, ...]，至少一条。
    period_ms: 仅用于注释里的帧率描述（各壁纸可有各自的 period）。
    """
    walls = list(walls) or [{"prefix": "face", "count": 1, "period_ms": period_ms or 0}]
    show_time = bool(show_time)
    show_date = bool(show_date)
    if tap_action == "cycle" and len(walls) < 2:
        tap_action = "none"          # 只有一张壁纸，"切换"没有意义

    desc = fps_desc or ("%d 张壁纸 / 首张 %d 帧" % (len(walls), walls[0]["count"]))
    out = [_HEAD.format(desc=desc)]

    rows = []
    for w in walls:
        rows.append('    { prefix = "%s", count = %d, period = %d },'
                    % (w["prefix"], w["count"], w.get("period_ms") or 0))
    out.append(_WALL_BLOCK.format(n_walls=len(walls), ext=ext,
                                  wall_table="\n".join(rows)))

    # ---- 时间 / 日期 ----
    if show_time or show_date:
        decls, body, vis = [], [], []
        if show_time:
            decls.append(_label_decl("timeLabel", time_align, time_ofs, time_size,
                                     time_color))
            body.append('    timeLabel:set { text = os.date("%s", t) }' % time_fmt)
            vis.append(_vis_line("timeLabel", "v"))
        if show_date:
            decls.append(_label_decl("dateLabel", date_align, date_ofs, date_size,
                                     date_color))
            body.append('    dateLabel:set { text = os.date("%s", t) }' % date_fmt)
            vis.append(_vis_line("dateLabel", "v"))
        out.append(_INFO_BLOCK.format(
            decls="".join(decls),
            refresh_body="    local t = os.time()\n" + "\n".join(body),
            vis_body="\n".join(vis)))

    # ---- 省电钩子（必须在点击处理之前：点击处理要用 pauseAll/resumeActive）----
    out.append(_POWER_BLOCK)

    # ---- 点击交互 ----
    if tap_action == "cycle":
        tap_desc = "短按切换壁纸"
        tap_body = ("    if #wallObjs > 1 then\n"
                    "        showWall(activeWall % #wallObjs + 1)\n"
                    "    end")
    elif tap_action == "info" and (show_time or show_date):
        tap_desc = "短按显示 / 隐藏时间日期"
        tap_body = "    setInfoVisible(not infoVisible)"
    elif tap_action == "anim":
        tap_desc = "短按暂停 / 继续动画"
        tap_body = ("    animPaused = not animPaused\n"
                    "    if animPaused then pauseAll() else resumeActive() end")
    else:
        tap_action, tap_desc, tap_body = "none", "", ""
    if tap_action != "none":
        out.append(_TAP_BLOCK.format(tap_desc=tap_desc, tap_body=tap_body))

    return "".join(out)
