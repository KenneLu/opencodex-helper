# -*- coding: utf-8 -*-
"""opencodex-helper 参数卡：kit 出厂默认值由 template.appconfig 提供，本文件覆盖工具差异。

本文件由工具自持（在 src/template 借条之外），template.appconfig 运行时
`try: import app_params` 读取覆盖；未写的键保留 kit 出厂默认值。
VERSION 不入卡：单一事实源在 src/main.py（build.bat / release.yml findstr 读取）。
"""
APP_ID = "opencodex-helper"
APP_NAME = "opencodex-helper"
AUTOSTART_KEY = APP_NAME
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


def _state_icon(size, color):
    """W6 状态贴图：与 _draw_icon 同形状，圆底色参数化（connected=绿/disconnected=灰）。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = size / 64.0
    d.ellipse((4 * f, 4 * f, 60 * f, 60 * f), fill=color)
    d.polygon([(32 * f, 12 * f), (48 * f, 30 * f), (39 * f, 39 * f),
               (39 * f, 52 * f), (25 * f, 52 * f), (25 * f, 30 * f),
               (16 * f, 30 * f)], fill=(255, 255, 255, 255))
    return img


# W6 状态贴图（构建期产帧，运行时 tray_icons 加载）
ICON_STATE_ARTISTS = {
    "connected": lambda base: _state_icon(256, (76, 175, 80, 255)),
    "disconnected": lambda base: _state_icon(256, (158, 158, 158, 255)),
}
