#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 assets/social-preview.svg 渲染成 assets/social-preview.png。

GitHub 仓库的社交预览图只收 PNG（1280×640），但手写 PNG 不现实，
所以真身是 SVG，这个脚本负责出图。改了 SVG 里的文案之后跑一次即可：

    python scripts/render_social_preview.py

需要本机装有 Chrome 或 Edge（脚本会自己找）。纯标准库，无第三方依赖。

为什么不用 AI 生图：卡片上的中文、金额（37.50 元）和拱门形状必须逐字
准确，生成式模型做不到稳定可控。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "social-preview.svg"
PNG = ROOT / "assets" / "social-preview.png"

WIDTH, HEIGHT = 1280, 640

# 常见安装位置；PATH 里的可执行名也一并尝试
CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "chrome",
    "chromium",
    "google-chrome",
]


def find_browser() -> str | None:
    for name in CANDIDATES:
        if Path(name).exists():
            return name
        found = shutil.which(name)
        if found:
            return found
    return None


def main() -> int:
    if not SVG.exists():
        print(f"[错误] 找不到源文件：{SVG}", file=sys.stderr)
        return 1

    browser = find_browser()
    if browser is None:
        print("[错误] 没找到 Chrome 或 Edge，无法渲染。"
              "请安装任一浏览器后重试。", file=sys.stderr)
        return 1

    # Chrome 偶尔会在页面还没画完时就截图，出成一张几乎空白的小图。
    # 单张 1280×640 的实拍结果应该在 100 KB 以上，低于这个量级按失败处理。
    for attempt in range(1, 4):
        subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-sandbox",
                "--force-device-scale-factor=1",
                f"--window-size={WIDTH},{HEIGHT}",
                f"--screenshot={PNG}",
                SVG.as_uri(),
            ],
            check=True,
            capture_output=True,
        )

        if not PNG.exists():
            print(f"[错误] 第 {attempt} 次渲染没有产出文件。", file=sys.stderr)
            continue

        size = PNG.stat().st_size
        if size >= 100_000:
            print(f"已生成 {PNG.relative_to(ROOT)}"
                  f"（{WIDTH}×{HEIGHT}，{size / 1024:.1f} KB）")
            return 0
        print(f"[警告] 第 {attempt} 次只渲染出 {size / 1024:.1f} KB，"
              f"疑似没有画完，重试……", file=sys.stderr)

    print("[错误] 连续三次渲染结果都异常偏小。"
          "请检查 SVG 是否是合法 XML（XML 注释里不允许出现双连字符）。",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
