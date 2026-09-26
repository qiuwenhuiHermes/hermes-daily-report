#!/usr/bin/env python3
"""设计缺陷数值扫描（对比度 / 点击区 / 字号 / 溢出）

用法:  python3 tools/check_design.py [base_url]   # 默认线上站

为什么用数值: 视觉模型对"字够不够灰"这类判断不可靠且不可复现；对比度、
点击区尺寸都是可计算的量，能进回归。检查项：
  1. WCAG 对比度 < 4.5 的正文/标题/元信息文字（列表页与报告页都测）
  2. 可点元素 < 44px 点击区（iPhone 触控下限）
  3. 正文 < 15px（移动端可读性）
  4. 页面级横向溢出（应为 0）
需要 Hermes venv 的 python3（带 websockets）。
"""
import asyncio
import json
import os
import sys
import urllib.request

import websockets

PORTFILE = os.path.expanduser("~/.hermes/browser-profile/chrome/DevToolsActivePort")
BASE = sys.argv[1] if len(sys.argv) > 1 else "https://qiuwenhuihermes.github.io/hermes-daily-report"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")

# 采样要测的"文字 × 背景"组合
SPEC = """
(() => {
  const out = [];
  const seen = new Set();
  const add = (label, el) => {
    if (!el) return;
    const cs = getComputedStyle(el);
    const bg = (function find(el){ while (el) { const c = getComputedStyle(el).backgroundColor;
      if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c; el = el.parentElement; } return 'rgb(255,255,255)'; })(el);
    const key = label + cs.color + bg + cs.fontSize;
    if (seen.has(key)) return; seen.add(key);
    out.push({label, color: cs.color, bg, size: parseFloat(cs.fontSize),
              text: (el.textContent || '').trim().slice(0, 18)});
  };
  add('正文', document.querySelector('.rpt-body p, .card p, p'));
  add('卡片标题', document.querySelector('.card h3, .card .title, .rpt-h1'));
  add('元信息', document.querySelector('.meta, .date, .sub, .foot-note'));
  add('表头', document.querySelector('th'));
  add('表格单元', document.querySelector('td'));
  add('链接', document.querySelector('a'));
  return out;
})()
"""

TAP_SPEC = """
(() => {
  const bad = [];
  document.querySelectorAll('a, button, [role=button]').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    if (r.height < 44 || r.width < 44) {
      bad.push({t: (el.textContent || '').trim().slice(0, 20), w: Math.round(r.width), h: Math.round(r.height)});
    }
  });
  return {bad: bad.slice(0, 12), n: bad.length};
})()
"""


def rgb(s):
    nums = [float(x) for x in s[s.find("(") + 1:s.find(")")].replace("/", " ").split(",")[:3]]
    return nums


def lum(c):
    def f(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = map(f, c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg, bg):
    l1, l2 = sorted([lum(rgb(fg)), lum(rgb(bg))], reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


class CDP:
    def __init__(self, ws):
        self.ws, self.i = ws, 0

    async def send(self, method, **params):
        self.i += 1
        await self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), 60))
            if msg.get("id") == self.i:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    async def ev(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr,
                            returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")


def ws_url():
    """从本机 Chrome 的 DevTools 端口取 page target（/json/new 已禁用，必须走 /json/list）"""
    port = open(PORTFILE).read().split("\n")[0].strip()
    targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10))
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        raise SystemExit("没有可用的 page target")
    return pages[0]["webSocketDebuggerUrl"]


async def settle(c, timeout=15):
    for _ in range(int(timeout * 4)):
        try:
            if await c.ev("document.readyState") == "complete":
                return
        except Exception:
            pass
        await asyncio.sleep(0.25)


async def main():
    async with websockets.connect(ws_url(), max_size=64 * 1024 * 1024) as ws:
        c = CDP(ws)
        await c.send("Page.enable")
        await c.send("Runtime.enable")
        # 必须禁用缓存: 站点的 CSS 内联在 HTML 里, Chrome 磁盘缓存会让 CDP 量到旧样式,
        # 于是"改完重新测量数字纹丝不动"——曾经因此误判修复未生效
        await c.send("Network.enable")
        await c.send("Network.setCacheDisabled", cacheDisabled=True)
        await c.send("Emulation.setDeviceMetricsOverride", width=402, height=874,
                     deviceScaleFactor=3, mobile=True)
        results = {}
        for name, url in [("首页", BASE + "/index.html"),
                          ("报告页", BASE + "/reports/2026-09-25-post_market.html")]:
            await c.send("Page.navigate", url=url)
            await settle(c)
            await asyncio.sleep(2)
            specs = await c.ev(SPEC) or []
            taps = await c.ev(TAP_SPEC) or {}
            overflow = await c.ev(
                "document.documentElement.scrollWidth - document.documentElement.clientWidth")
            results[name] = (specs, taps, overflow)

    low, small, tiny = [], [], []
    for page, (specs, taps, overflow) in results.items():
        for s in specs:
            r = ratio(s["color"], s["bg"])
            if r < 4.5:
                low.append(f"[{page}] {s['label']} 对比度 {r:.2f} <4.5 ({s['color']} on {s['bg']}) “{s['text']}”")
            # 正文字号底线 15px；次级信息（元信息/表格/小字）底线 13px——13px 是刻意的细字层级
            floor = 15 if s["label"] == "正文" else 13
            if s["size"] and s["size"] < floor:
                tiny.append(f"[{page}] {s['label']} 字号 {s['size']}px <{floor}px “{s['text']}”")
        if overflow:
            low.append(f"[{page}] 页面级横向溢出 {overflow}px")
        for b in taps.get("bad", []):
            small.append(f"[{page}] 点击区 {b['w']}×{b['h']} <44px “{b['t']}”")

    print(f"对比度<4.5: {len(low)}")
    for x in low[:10]:
        print("  " + x)
    print(f"点击区<44px: {len(small)}（含行内链接属正常，重点看按钮）")
    for x in small[:8]:
        print("  " + x)
    print(f"字号<15px: {len(tiny)}")
    for x in tiny[:6]:
        print("  " + x)
    return 1 if (low or tiny) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
