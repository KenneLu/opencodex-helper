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
    基图 = 服务健康绿（default 兜底帧与 exe ico 来源）；运行态四种着色由
    ICON_STATE_ARTISTS 覆盖。"""
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


def _state_icon(size, color, tunnel=False):
    """W6 状态贴图：与 _draw_icon 同形状，圆底色参数化；tunnel=True 加右下黄点。

    黄点几何照 reme-helper `icon_pipeline.make_icon`：直径 0.26×画布、白描边
    0.03×画布，贴右下角——角标语义 = 隧道链路在，与服务健康正交。
    """
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = size / 64.0
    d.ellipse((4 * f, 4 * f, 60 * f, 60 * f), fill=color)
    d.polygon([(32 * f, 12 * f), (48 * f, 30 * f), (39 * f, 39 * f),
               (39 * f, 52 * f), (25 * f, 52 * f), (25 * f, 30 * f),
               (16 * f, 30 * f)], fill=(255, 255, 255, 255))
    if tunnel:
        dot = max(4, round(size * 0.26))
        d.ellipse((size - dot - 1, size - dot - 1, size - 1, size - 1),
                  fill="#f5c211", outline="#ffffff", width=max(1, round(size * 0.03)))
    return img


# W6 状态贴图（构建期产帧，运行时 tray_icons 加载）
# 四态 = 服务健康 × 任一启用隧道连通；键名与 reme-helper 同款（kit 对状态名无硬编码）。
ICON_STATE_ARTISTS = {
    "ok": lambda base: _state_icon(256, (76, 175, 80, 255)),                  # 绿：服务健康
    "ok_tunnel": lambda base: _state_icon(256, (76, 175, 80, 255), tunnel=True),   # 绿+黄点：服务健康且隧道在
    "down": lambda base: _state_icon(256, (108, 117, 125, 255)),              # 灰 #6c757d：未连接
    "down_tunnel": lambda base: _state_icon(256, (108, 117, 125, 255), tunnel=True),  # 灰+黄点：隧道在、服务断
}
