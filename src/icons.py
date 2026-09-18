# -*- coding: utf-8 -*-
"""图标生成：圆环 + 白色向上箭头（隧道/服务语义），代码绘制，零美术素材。

生成两个 .ico：
  opencodex-helper.ico          托盘态：16/24/32/48/64/256 帧
  opencodex-helper-taskbar.ico  任务栏/窗口/exe：按 Windows 外壳真实索取的像素铺帧，
                                覆盖 100%~200% DPI（标题栏/任务栏/Alt-Tab），避免缩小发糊。

颜色语义与运行时托盘一致（main.py make_icon_image）：绿 = 已连接，灰 = 空闲；
ico 用绿色（默认展示态），运行态着色由托盘的 make_icon_image 承担。
"""
import os

from PIL import Image, ImageDraw

APP_ID = "opencodex-helper"
GREEN = (76, 175, 80, 255)
WHITE = (255, 255, 255, 255)


def draw_icon(size, fill=GREEN):
    """在 size×size 画布上画「圆 + 上箭头」（与 main.py 托盘图标同一设计）。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64.0  # 设计稿按 64 坐标
    d.ellipse((4 * s, 4 * s, 60 * s, 60 * s), fill=fill)
    d.polygon([(32 * s, 12 * s), (48 * s, 30 * s), (39 * s, 30 * s),
               (39 * s, 52 * s), (25 * s, 52 * s), (25 * s, 30 * s),
               (16 * s, 30 * s)], fill=WHITE)
    return img


TRAY_SIZES = (16, 24, 32, 48, 64, 256)
# 100%~200% DPI 下外壳真实索取的像素档（reme-helper 同款清单）
TASKBAR_SIZES = (16, 20, 24, 28, 30, 32, 36, 40, 42, 48, 56, 64, 96, 128, 256)


def make_icons(base_dir):
    """在 base_dir 下生成托盘态与任务栏态两个 ico，返回 (托盘, 任务栏) 路径。"""
    tray_path = os.path.join(base_dir, f"{APP_ID}.ico")
    taskbar_path = os.path.join(base_dir, f"{APP_ID}-taskbar.ico")
    img = draw_icon(256, GREEN)
    img.save(tray_path, sizes=[(s, s) for s in TRAY_SIZES])
    img.save(taskbar_path, sizes=[(s, s) for s in TASKBAR_SIZES])
    return tray_path, taskbar_path


if __name__ == "__main__":
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根（ico 落根，构建按根取）
    t, k = make_icons(base)
    print("OK", t, k, "exists:", os.path.exists(t), os.path.exists(k))
