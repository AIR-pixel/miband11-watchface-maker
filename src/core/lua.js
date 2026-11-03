/**
 * 生成 main.lua —— 序列帧动画 + 时间/日期叠加 + 点击交互 + 省电钩子。
 *
 * 结构与 watchface-tool/watchface_tool/lua.py 对齐（包括两个省电钩子：
 * pageOnPause/Resume 管切页、ScreenStateChangedCB 管息屏 —— 只用前者会让
 * 动画在 AOD 下继续跑，续航直接崩）。
 */

const HEAD = (desc) => `-- 小米手环 11 动态表盘
-- ${desc}
local lvgl = require("lvgl")
local dataman = require("dataman")

local SCRIPT_PATH = rawget(_G, "SCRIPT_PATH") or ""

local function imgPath(src)
    return SCRIPT_PATH .. src
end

-- 根对象
local root = lvgl.Object(nil, {
    w = lvgl.HOR_RES(),
    h = lvgl.VER_RES(),
    bg_color = 0x000000,
    bg_opa = lvgl.OPA(100),
    border_width = 0,
    pad_all = 0,
})
root:clear_flag(lvgl.FLAG.SCROLLABLE)
root:add_flag(lvgl.FLAG.EVENT_BUBBLE)
`;

const WALL_BLOCK = (ext, rows, nWalls) => `
-- ===== 壁纸（${nWalls} 张，点击可切换）=====
local EXT = "${ext}"
local WALLS = {
${rows}
}
local wallObjs = {}
local activeWall = 1

for wi, w in ipairs(WALLS) do
    local srcs = {}
    for i = 1, w.count do
        srcs[i] = imgPath(string.format("%s_%02d." .. EXT, w.prefix, i))
    end
    w.srcs = srcs
    w.cur = 1

    local img = root:Image { src = srcs[1] }
    img:set {
        w = lvgl.HOR_RES(),
        h = lvgl.VER_RES(),
        align = { type = lvgl.ALIGN.TOP_MID, x_ofs = 0, y_ofs = 0 },
    }
    if wi ~= 1 then img:add_flag(lvgl.FLAG.HIDDEN) end

    local timer = lvgl.Timer {
        period = w.period,
        cb = function()
            w.cur = w.cur % #srcs + 1
            img:set { src = srcs[w.cur] }
        end,
    }
    if wi ~= 1 then pcall(function() timer:pause() end) end

    wallObjs[wi] = { img = img, timer = timer }
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
`;

const labelDecl = (name, align, ofs, size, color) => `local ${name} = lvgl.Label(root, {
    text = "",
    text_font = lvgl.Font("montserrat", ${size}, "normal"),
    text_color = 0x${color.toString(16).toUpperCase().padStart(6, '0')},
    align = { type = lvgl.ALIGN.${align}, x_ofs = ${ofs[0]}, y_ofs = ${ofs[1]} },
})
`;

const INFO_BLOCK = (decls, body, vis) => `
-- ===== 时间 / 日期（叠加在动图上）=====
local infoVisible = true
${decls}
local function refreshTime()
    local t = os.time()
${body}
end

refreshTime()
pcall(function()
    dataman.subscribe("timeMinuteLow", root, function(obj, value)
        refreshTime()
    end)
end)

local function setInfoVisible(v)
    infoVisible = v
${vis}
end
`;

const POWER_BLOCK = `
-- ===== 省电：切页 + 息屏双钩子 =====
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
`;

const TAP_BLOCK = (tapDesc, tapBody) => `
-- ===== 点击交互：${tapDesc} =====
root:add_flag(lvgl.FLAG.CLICKABLE)

root:onevent(lvgl.EVENT.SHORT_CLICKED, function(obj, code)
${tapBody}
end)
`;

const visLine = (varName) => `    if ${varName} then
        if v then ${varName}:clear_flag(lvgl.FLAG.HIDDEN) else ${varName}:add_flag(lvgl.FLAG.HIDDEN) end
    end`;

/**
 * @param {object} o
 * @param {{prefix:string, count:number, periodMs:number}[]} o.walls
 * @param {string} o.ext
 * @param {boolean} o.showTime
 * @param {boolean} o.showDate
 * @param {string} o.timeAlign
 * @param {[number,number]} o.timeOfs
 * @param {number} o.timeSize
 * @param {number} o.timeColor
 * @param {string} o.timeFmt
 * @param {string} o.dateAlign
 * @param {[number,number]} o.dateOfs
 * @param {number} o.dateSize
 * @param {number} o.dateColor
 * @param {string} o.dateFmt
 * @param {'none'|'cycle'|'info'|'anim'} o.tap
 * @param {string} [o.desc]
 */
export function generateLua(o) {
  const walls = o.walls && o.walls.length ? o.walls : [{ prefix: 'face', count: 1, periodMs: 100 }];
  const showTime = o.showTime !== false;
  const showDate = !!o.showDate;
  let tap = o.tap || 'none';
  if (tap === 'cycle' && walls.length < 2) tap = 'none';

  const desc = o.desc || `${walls.length} 张壁纸 / 首张 ${walls[0].count} 帧`;
  const out = [HEAD(desc)];

  const rows = walls
    .map((w) => `    { prefix = "${w.prefix}", count = ${w.count}, period = ${Math.round(w.periodMs || 0)} },`)
    .join('\n');
  out.push(WALL_BLOCK(o.ext || 'png', rows, walls.length));

  if (showTime || showDate) {
    const decls = [];
    const body = [];
    const vis = [];
    if (showTime) {
      decls.push(labelDecl('timeLabel', o.timeAlign || 'TOP_MID', o.timeOfs || [0, 30], o.timeSize || 48, o.timeColor ?? 0xffffff));
      body.push(`    timeLabel:set { text = os.date("${o.timeFmt || '%H:%M'}", t) }`);
      vis.push(visLine('timeLabel'));
    }
    if (showDate) {
      decls.push(labelDecl('dateLabel', o.dateAlign || 'TOP_MID', o.dateOfs || [0, 86], o.dateSize || 16, o.dateColor ?? 0xeeeeee));
      body.push(`    dateLabel:set { text = os.date("${o.dateFmt || '%m/%d'}", t) }`);
      vis.push(visLine('dateLabel'));
    }
    out.push(INFO_BLOCK(decls.join(''), body.join('\n'), vis.join('\n')));
  }

  out.push(POWER_BLOCK);

  let tapDesc = '';
  let tapBody = '';
  if (tap === 'cycle') {
    tapDesc = '短按切换壁纸';
    tapBody = `    if #wallObjs > 1 then
        showWall(activeWall % #wallObjs + 1)
    end`;
  } else if (tap === 'info' && (showTime || showDate)) {
    tapDesc = '短按显示 / 隐藏时间日期';
    tapBody = '    setInfoVisible(not infoVisible)';
  } else if (tap === 'anim') {
    tapDesc = '短按暂停 / 继续动画';
    tapBody = `    animPaused = not animPaused
    if animPaused then pauseAll() else resumeActive() end`;
  }
  if (tapDesc) out.push(TAP_BLOCK(tapDesc, tapBody));

  return out.join('');
}
