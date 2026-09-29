# -*- coding: utf-8 -*-
"""生成 main.lua（全屏序列帧动画 + 时间日期叠加）。

结构与已实机验证的 24fps 表盘一致：Timer 周期切帧 + pageOnPause/Resume 省电。
"""
from .constants import SCREEN_H, SCREEN_W

_TEMPLATE = """-- 小米手环 11 动态表盘（序列帧 {w}x{h}）
-- {n} 帧 @ {period}ms/帧 ≈ {fps_desc}
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

-- ===== 全屏序列帧动画 =====
local FRAMES = {{}}
for i = 1, {n} do
    FRAMES[i] = string.format("face_%02d.{ext}", i)
end
local frameIndex = 1

local animImg = root:Image {{ src = imgPath(FRAMES[1]) }}
animImg:set {{
    w = lvgl.HOR_RES(),
    h = lvgl.VER_RES(),
    align = {{ type = lvgl.ALIGN.TOP_MID, x_ofs = 0, y_ofs = 0 }},
}}

local animTimer = lvgl.Timer {{
    period = {period},
    cb = function(t)
        frameIndex = frameIndex % #FRAMES + 1
        animImg:set {{ src = imgPath(FRAMES[frameIndex]) }}
    end,
}}
{time_block}
-- ===== 生命周期钩子：切走暂停动画省电 =====
pageOnPause = function()
    if animTimer then pcall(function() animTimer:pause() end) end
end

pageOnResume = function()
    if animTimer then pcall(function() animTimer:resume() end) end
end
"""

_TIME_BLOCK = """
-- ===== 时间标签（顶部居中，叠加在动图上）=====
local timeLabel = lvgl.Label(root, {
    text = "00:00",
    text_font = lvgl.Font("montserrat", 48, "normal"),
    text_color = 0xFFFFFF,
    align = { type = lvgl.ALIGN.TOP_MID, y_ofs = 30 },
})

-- 日期标签
local dateLabel = lvgl.Label(root, {
    text = "",
    text_font = lvgl.Font("montserrat", 16, "normal"),
    text_color = 0xEEEEEE,
    align = { type = lvgl.ALIGN.TOP_MID, y_ofs = 86 },
})

local function refreshTime()
    local t = os.time()
    timeLabel:set { text = os.date("%H:%M", t) }
    dateLabel:set { text = os.date("%m/%d", t) }
end

refreshTime()

dataman.subscribe("timeMinuteLow", root, function(obj, value)
    refreshTime()
end)
"""


def generate_lua(n_frames, period_ms, show_time=True, ext="png"):
    fps_desc = f"{1000.0 / period_ms:.1f}FPS" if period_ms else "静态"
    time_block = _TIME_BLOCK if show_time else ""
    return _TEMPLATE.format(
        w=SCREEN_W,
        h=SCREEN_H,
        n=n_frames,
        period=period_ms,
        fps_desc=fps_desc,
        ext=ext,
        time_block=time_block,
    )
