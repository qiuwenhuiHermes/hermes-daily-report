#!/usr/bin/env python3
"""Apple Stocks 风格迷你趋势线（sparkline）生成器 + 行情抓取

配色遵循 iOS 系统色：涨 #34C759 / 跌 #FF3B30（绿涨红跌，美股语境）
纯标准库，无第三方依赖。供 build_site.py 在构建时调用。
"""
import json
import math
import os
import urllib.request

UP = "#34C759"      # iOS 系统绿（涨）
DOWN = "#FF3B30"    # iOS 系统红（跌）
FONT = "'TsangerJinKai02','TsangerJinKai','Kaiti SC','STKaiti',serif"

# 评估池（13 只，与 ~/designs/stock-portfolio-dashboard/data.js 同源）
POOL = [
    ("TSM", "台积电"), ("MU", "美光"), ("AVGO", "博通"), ("NVDA", "英伟达"),
    ("GOOGL", "谷歌"), ("MSFT", "微软"), ("AMD", "超微"), ("AMZN", "亚马逊"),
    ("META", "Meta"), ("AAPL", "苹果"), ("PLTR", "Palantir"), ("ORCL", "甲骨文"),
    ("TSLA", "特斯拉"),
]

_QT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{n},qfq"


def fetch_days(ticker, n=30, timeout=12):
    """抓腾讯美股前复权日K。返回 [[date,open,close,high,low,vol],...] 或 None。
    交易所后缀逐个尝试（.OQ 纳斯达克 / .N 纽交所 / 无后缀），取首个有数据的。"""
    for sym in (f"us{ticker}.OQ", f"us{ticker}.N", f"us{ticker}"):
        try:
            req = urllib.request.Request(_QT.format(sym=sym, n=n),
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            data = d.get("data") or {}
            if isinstance(data, list) or not data:
                continue
            blk = data.get(list(data.keys())[0]) or {}
            days = blk.get("qfqday") or blk.get("day")
            if days and len(days) >= 5:
                return days
        except Exception:
            continue
    return None


def _smooth_path(pts):
    """Catmull-Rom → 三次贝塞尔，得到苹果那种柔顺曲线（过点、不过度拟合）"""
    if len(pts) < 2:
        return f"M {pts[0][0]:.1f} {pts[0][1]:.1f}" if pts else ""
    out = [f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"]
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        out.append(f"C {x0 + (x1 - x0) / 3:.1f} {y0 + (y1 - y0) / 3:.1f} "
                   f"{x1 - (x1 - x0) / 3:.1f} {y1 - (y1 - y0) / 3:.1f} {x1:.1f} {y1:.1f}")
    return " ".join(out)


def sparkline_svg(closes, w=132, h=42, label=""):
    """Apple Stocks 风格：平滑曲线 + 柔和渐变填充 + 末端呼吸点。无网格无坐标轴。"""
    closes = [float(c) for c in closes]
    if len(closes) < 2:
        return ""
    lo, hi = min(closes), max(closes)
    rng = (hi - lo) or 1
    pad = 4
    n = len(closes)
    pts = [(pad + i * (w - 2 * pad) / (n - 1),
            h - pad - (c - lo) / rng * (h - 2 * pad)) for i, c in enumerate(closes)]
    chg = (closes[-1] - closes[0]) / closes[0] * 100
    color = UP if chg >= 0 else DOWN
    uid = "sp" + str(abs(hash((round(closes[0], 2), round(closes[-1], 2), w, h))) % 10 ** 8)
    path = _smooth_path(pts)
    area = f"{path} L {pts[-1][0]:.1f} {h} L {pts[0][0]:.1f} {h} Z"
    lx, ly = pts[-1]
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{label} 近30日 {chg:+.1f}%" class="spk">'
        f'<defs><linearGradient id="{uid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.22"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
        f'</linearGradient></defs>'
        f'<path d="{area}" fill="url(#{uid})"/>'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{2.4 + 2.6}" fill="{color}" opacity="0.22"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.4" fill="{color}"/></svg>'
    )


def render_watchlist(rows):
    """rows: [(ticker, name, closes, last, chg30, chg1), ...] → 首页自选池板块 HTML"""
    if not rows:
        return ""
    items = []
    for ticker, name, closes, last, chg30, chg1 in rows:
        col = UP if chg30 >= 0 else DOWN
        items.append(f'''<div class="wl-row">
  <img class="wl-logo" src="assets/logos/{ticker}.svg" alt="" width="24" height="24" loading="lazy" decoding="async">
  <div class="wl-tk"><b>{ticker}</b><span>{name}</span></div>
  <div class="wl-sp">{sparkline_svg(closes, label=ticker)}</div>
  <div class="wl-num"><b>{last:,.2f}</b><span style="color:{col}">30日 {chg30:+.1f}%</span></div>
</div>''')
    return f'''<section class="wl">
  <h2 class="wl-h">自选池 · 近 30 个交易日<span class="wl-note">绿涨红跌 · 数据源 腾讯财经</span></h2>
  <div class="wl-grid">
{chr(10).join(items)}
  </div>
</section>'''


def build_watchlist_html(verbose=True):
    """抓池内行情并渲染；任何失败都优雅降级（返回 '' 或跳过个别标的）。"""
    rows = []
    for ticker, name in POOL:
        days = fetch_days(ticker, n=30)
        if not days:
            if verbose:
                print(f"  ⚠️ {ticker} 行情抓取失败，跳过")
            continue
        closes = [float(d[2]) for d in days][-30:]
        if len(closes) < 5:
            continue
        last = closes[-1]
        chg30 = (last - closes[0]) / closes[0] * 100
        chg1 = (last - closes[-2]) / closes[-2] * 100 if len(closes) > 1 else 0.0
        rows.append((ticker, name, closes, last, chg30, chg1))
    if verbose:
        print(f"  ✅ 自选池：{len(rows)}/{len(POOL)} 只标的行情就绪")
    return render_watchlist(rows)
