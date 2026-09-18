# -*- coding: utf-8 -*-
# TEMPLATE-FROM: my-diy-tool-template/modules/appconfig/appconfig.py | TEMPLATE-VER: 1.0.0
# opencodex-helper 参数区（T1：拷贝后唯一允许修改的文件）。
# VERSION 不在此处：单一事实源在 main.py（build.bat / release.yml findstr 读取，D15）。
APP_ID = "opencodex-helper"
APP_NAME = "opencodex-helper"
REPO_OWNER = "KenneLu"
REPO_NAME = "opencodex-helper"
EXE_NAME = "opencodex-helper.exe"


def _draw_icon(size):
    """G5 图标：圆 + 白色上箭头（隧道/服务语义），与 main.py 托盘同形状；
    绿 = 已连接（默认展示态），运行态着色由托盘的 make_icon_image 承担。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = size / 64.0
    d.ellipse((4 * f, 4 * f, 60 * f, 60 * f), fill=(76, 175, 80, 255))
    d.polygon([(32 * f, 12 * f), (48 * f, 30 * f), (39 * f, 30 * f),
               (39 * f, 52 * f), (25 * f, 52 * f), (25 * f, 30 * f),
               (16 * f, 30 * f)], fill=(255, 255, 255, 255))
    return img


ICON_ASSET = None
ICON_DRAW = _draw_icon
