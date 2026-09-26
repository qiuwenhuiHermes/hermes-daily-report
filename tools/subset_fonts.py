#!/usr/bin/env python3
"""
subset_fonts.py — 把 kami 的 TsangerJinKai02 TTF 子集化成站点专用 woff2。

问题：上游 TTF 单字重 18 MB，两个字重共 36 MB，移动端首屏灾难。
做法：语料 = 站点自身全部文本 ∪ 常用字符基线，转 woff2。
输出：docs/fonts/kami-400.woff2 / kami-500.woff2

用法: python3 tools/subset_fonts.py [--extra-baseline]
"""
import os, re, sys, glob, html
from fontTools import subset
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
OUTDIR = os.path.join(DOCS, "fonts")
SRC = {
    400: os.path.expanduser("~/.hermes/assets/fonts/kami/TsangerJinKai02-W04.ttf"),
    500: os.path.expanduser("~/.hermes/assets/fonts/kami/TsangerJinKai02-W05.ttf"),
}

# ── 基线字符集：ASCII + 常用标点 + 全角标点 ──
def baseline_chars() -> set:
    cs = set(chr(c) for c in range(0x20, 0x7F))
    cs |= set("　！？。，、；：”“‘’（）《》〈〉【】〔〕—…·～＋－×÷＝％‰°±≤≥≠√∅←→↑↓↗↘■□●○◆◇★☆▲△▼▽⚡⚠✓✗")
    cs |= set("ⅰⅱⅲⅳⅴ①②③④⑤⑥⑦⑧⑨⑩")
    return cs


def cjk_baseline() -> set:
    """GB2312 一级+二级汉字（6763 字）——覆盖绝大多数金融/通用中文，防未来内容缺字。"""
    cs = set()
    for hi in range(0xB0, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                ch = bytes([hi, lo]).decode("gb2312")
                cs.add(ch)
            except Exception:
                pass
    return cs


def corpus_from_site() -> set:
    """站点生成物里出现过的所有字符。"""
    cs = set()
    for f in glob.glob(os.path.join(DOCS, "**", "*.html"), recursive=True):
        with open(f, encoding="utf-8", errors="ignore") as fh:
            txt = re.sub(r"<[^>]+>", " ", fh.read())
        cs |= set(html.unescape(txt))
    return cs


def build_unicodes() -> str:
    keep = baseline_chars() | cjk_baseline() | corpus_from_site()
    keep = {c for c in keep if c.isprintable() and c not in "\n\r\t"}
    u = sorted({ord(c) for c in keep})
    return ",".join(f"U+{x:04X}" for x in u)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    unicodes = build_unicodes()
    print(f"目标字符数: {len(unicodes.split(',')):,}")
    for weight, src in SRC.items():
        if not os.path.exists(src):
            print(f"✗ 缺源字体: {src}")
            return 1
        dst = os.path.join(OUTDIR, f"kami-{weight}.woff2")
        args = [
            src, f"--unicodes={unicodes}", f"--output-file={dst}",
            "--flavor=woff2", "--layout-features=", "--no-hinting",
            "--desubroutinize", "--drop-tables+=DSIG",
        ]
        subset.main(args)
        a, b = os.path.getsize(src) / 1048576, os.path.getsize(dst) / 1048576
        print(f"  {weight}: {a:6.2f} MB → {b:5.2f} MB  (省 {100*(1-b/a):.1f}%)")
    total = sum(os.path.getsize(os.path.join(OUTDIR, f)) for f in os.listdir(OUTDIR))
    print(f"两字重合计: {total/1048576:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
