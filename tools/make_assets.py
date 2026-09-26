#!/usr/bin/env python3
"""
make_assets.py — 生成站点品牌资产（Pillow + kami 字体）
  docs/favicon.svg          矢量图标（温度计意象，16px 下可辨识）
  docs/favicon.png          32x32 兜底
  docs/apple-touch-icon.png 180x180（iOS 添加到主屏）
  docs/assets/og.png        1200x630 分享预览卡
用法: python3 tools/make_assets.py
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
ASSETS = os.path.join(DOCS, "assets")
FONT_MED = os.path.expanduser("~/.hermes/assets/fonts/kami/TsangerJinKai02-W05.ttf")
FONT_REG = os.path.expanduser("~/.hermes/assets/fonts/kami/TsangerJinKai02-W04.ttf")

PARCHMENT = (245, 244, 237)
IVORY = (250, 249, 245)
BRAND = (27, 54, 93)
DARKWARM = (61, 61, 58)
OLIVE = (80, 78, 73)
STONE = (107, 106, 100)
SAND = (226, 223, 209)

FAVICON_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#1B365D"/>
  <rect x="27" y="12" width="10" height="30" rx="5" fill="#f5f4ed"/>
  <circle cx="32" cy="49" r="9" fill="#f5f4ed"/>
  <circle cx="32" cy="49" r="5" fill="#1B365D"/>
  <rect x="27" y="30" width="10" height="12" fill="#1B365D" opacity=".35"/>
</svg>'''


def _font(path, size):
    return ImageFont.truetype(path, size)


def icon(size: int) -> Image.Image:
    """圆角墨蓝底 + 羊皮纸温度计意象"""
    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(S * 0.22)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=BRAND)
    bar_w = int(S * 0.156)
    bar_x = (S - bar_w) // 2
    top, bot = int(S * 0.19), int(S * 0.79)
    d.rounded_rectangle([bar_x, top, bar_x + bar_w, bot], radius=bar_w // 2, fill=PARCHMENT)
    d.ellipse([bar_x - int(S * 0.015), top - int(S * 0.06),
               bar_x + bar_w + int(S * 0.015), top + int(S * 0.10)], fill=PARCHMENT)
    cw = int(S * 0.44)
    cx, cy = S // 2, int(S * 0.66)
    d.ellipse([cx - cw // 2, cy - cw // 2, cx + cw // 2, cy + cw // 2], fill=PARCHMENT)
    iw = int(cw * 0.5)
    d.ellipse([cx - iw // 2, cy - iw // 2, cx + iw // 2, cy + iw // 2], fill=BRAND)
    d.rounded_rectangle([bar_x, cy - int(S * 0.14), bar_x + bar_w, cy], radius=0,
                        fill=(140, 150, 160, 90))
    return img.resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")


def og_card() -> Image.Image:
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), PARCHMENT)
    d = ImageDraw.Draw(img)
    # 左侧墨蓝竖条（kami 的规则线语言）
    d.rectangle([0, 0, 10, H], fill=BRAND)
    # 细微噪点质感（打破纯平）
    import random
    random.seed(7)
    for _ in range(2600):
        x, y = random.randrange(W), random.randrange(H)
        d.point((x, y), fill=(232, 230, 220))
    # 眉标
    d.rectangle([92, 118, 124, 122], fill=BRAND)
    d.text((140, 104), "HERMES DAILY REVIEW", font=_font(FONT_MED, 25), fill=BRAND)
    # 主标题
    d.text((92, 168), "每日观察", font=_font(FONT_MED, 108), fill=(20, 20, 19))
    # 副标题
    d.text((96, 316), "美股盘后 / 盘前评估 · 价格温度计 · 定投信号",
           font=_font(FONT_REG, 34), fill=OLIVE)
    # 分隔线
    d.line([92, 404, W - 92, 404], fill=SAND, width=2)
    # 底部信息
    d.text((96, 436), "61 份历史报告 · 每交易日自动生成并部署",
           font=_font(FONT_REG, 30), fill=STONE)
    d.text((96, 500), "qiuwenhuihermes.github.io/hermes-daily-report",
           font=_font(FONT_REG, 26), fill=BRAND)
    d.text((96, 552), "⚠ 内容基于公开信息的研究推演，非投资建议",
           font=_font(FONT_REG, 24), fill=STONE)
    return img


def main():
    os.makedirs(ASSETS, exist_ok=True)
    if not os.path.exists(FONT_MED) or not os.path.exists(FONT_REG):
        print(f"✗ 缺字体: {FONT_MED}")
        return 1
    with open(os.path.join(DOCS, "favicon.svg"), "w", encoding="utf-8") as f:
        f.write(FAVICON_SVG)
    icon(180).save(os.path.join(DOCS, "apple-touch-icon.png"))
    icon(32).save(os.path.join(DOCS, "favicon.png"))
    og_card().save(os.path.join(ASSETS, "og.png"), optimize=True)
    for f in ["favicon.svg", "favicon.png", "apple-touch-icon.png", "assets/og.png"]:
        p = os.path.join(DOCS, f)
        print(f"  {f:26s} {os.path.getsize(p)/1024:7.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
