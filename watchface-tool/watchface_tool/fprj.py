# -*- coding: utf-8 -*-
"""生成 .fprj 项目文件（UTF-16 LE + BOM，LF 换行，与实机验证文件字节级一致）。"""
from .constants import DEVICE_TYPE, SCREEN_H, SCREEN_W, WIDGET_SHAPE

_XML = (
    '<?xml version="1.0" encoding="utf-16" ?>\n'
    '<FaceProject DeviceType="{device}">\n'
    '    <Screen Title="{name}" Bitmap="preview.png">\n'
    '        <Widget Shape="{shape}" Name="app_lua%2Fmain.lua" '
    'X="0" Y="0" Width="{w}" Height="{h}" Alpha="0" Visible_Src="0" />\n'
    '    </Screen>\n'
    '</FaceProject>\n'
)


def generate_fprj(name):
    xml = _XML.format(
        device=DEVICE_TYPE, shape=WIDGET_SHAPE, w=SCREEN_W, h=SCREEN_H, name=name
    )
    return xml.encode("utf-16")  # utf-16 编码器 = UTF-16 LE 且自动加 BOM
