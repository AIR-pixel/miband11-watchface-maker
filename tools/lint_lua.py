# -*- coding: utf-8 -*-
"""给生成的 main.lua 做语法校验（luaparser，Lua 5.3 语法）。

生成的 lua 是拼字符串拼出来的，最容易出的错就是括号/块不配对和
local 作用域顺序（例如点击处理里引用了后面才声明的 local function，
Lua 里会静默变成 nil，编译器不报错、真机才炸）。

用法：
    python lint_lua.py            # 跑所有组合
"""
import itertools
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "watchface-tool"))

from watchface_tool import lua as L                       # noqa: E402
from watchface_tool.constants import ALIGN_KEYS, TAP_ACTIONS   # noqa: E402

try:
    from luaparser import ast
except ImportError:
    print("需要 luaparser：pip install luaparser")
    sys.exit(2)

FAILS = []


def check(name, src):
    try:
        ast.parse(src)
        return True
    except Exception as e:                            # noqa: BLE001
        FAILS.append((name, str(e)[:400]))
        print("  FAIL %-46s %s" % (name, str(e)[:160].replace("\n", " ")))
        return False


def main():
    n = 0
    # 1) 单壁纸 / 多壁纸 × 各对齐位置 × 各交互
    for n_walls in (1, 2, 3):
        walls = [{"prefix": "face" if i == 0 else "w%d" % (i + 1),
                  "count": 4 + i, "period_ms": 83} for i in range(n_walls)]
        for align in ALIGN_KEYS:
            for tap in TAP_ACTIONS:
                for show_t, show_d in ((True, False), (True, True),
                                       (False, True), (False, False)):
                    src = L.generate_lua(
                        walls, 83, ext="png",
                        show_time=show_t, show_date=show_d,
                        time_align=align, time_ofs=(3, -7), time_size=48,
                        time_color=0xFFFFFF, time_fmt="%H:%M",
                        date_align=align, date_ofs=(-2, 11), date_size=16,
                        date_color=0xEEEEEE, date_fmt="%Y/%m/%d",
                        tap_action=tap)
                    n += 1
                    check("walls=%d align=%s tap=%s t=%d d=%d"
                          % (n_walls, align, tap, show_t, show_d), src)
    # 2) 极端参数
    for fmt, size in (("%H:%M:%S", 96), ("%p %I:%M", 12), ("%m/%d", 200)):
        n += 1
        check("fmt=%s size=%d" % (fmt, size),
              L.generate_lua([{"prefix": "face", "count": 1, "period_ms": 0}], 0,
                             show_time=True, show_date=True,
                             time_fmt=fmt, time_size=size, tap_action="anim"))
    print("\n共 %d 份，失败 %d 份" % (n, len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
