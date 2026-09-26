#!/usr/bin/env python3
"""抓线上/本地站点截图（iPhone 17 Pro 视口），用于人工复核渲染效果

用法:  python3 tools/live_shots.py [base_url] [out_dir]

默认抓 3 张: 首页上半、首页下半、报告页表格区。截图用于视觉复核——
数值检查全绿但"表格被当文字渲染"这类问题，往往是截图上先看出来。
需要 Hermes venv 的 python（含 websockets）:
  /Users/qiuwenhui/.hermes/hermes-agent/venv/bin/python3 tools/live_shots.py
"""
import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import websockets  # noqa: E402
from audit_pages import CDP, UA, settle, ws_url  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else 'https://qiuwenhuihermes.github.io/hermes-daily-report'
OUT = sys.argv[2] if len(sys.argv) > 2 else '/tmp'
SHOTS = [
    ('index.html', 0, 1150, 'live_idx1.png'),
    ('index.html', 1150, 1150, 'live_idx2.png'),
    ('reports/2026-09-25-post_market.html', 2350, 1500, 'live_tbl.png'),
]


async def main():
    async with websockets.connect(ws_url(), max_size=64 * 1024 * 1024) as ws:
        c = CDP(ws)
        await c.send('Page.enable')
        await c.send('Runtime.enable')
        await c.send('Emulation.setDeviceMetricsOverride', **UA)

        for rel, y, h, name in SHOTS:
            await c.send('Page.navigate', url=f'{BASE}/{rel}')
            await settle(c)
            r = None
            for _ in range(3):
                try:
                    r = await c.send('Page.captureScreenshot', format='png',
                                     captureBeyondViewport=True,
                                     clip={'x': 0, 'y': y, 'width': 402, 'height': h, 'scale': 1})
                    break
                except Exception:
                    await asyncio.sleep(1.0)
            if not r:
                print('skip (截图失败)', name)
                continue
            p = os.path.join(OUT, name)
            open(p, 'wb').write(base64.b64decode(r['data']))
            print('saved', p)

        info = await c.ev(
            "document.querySelectorAll('.tbl-wrap').length + '|' + "
            "document.querySelectorAll('th').length + '|' + "
            "(document.documentElement.scrollWidth-document.documentElement.clientWidth)")
        print('末页 表格|th|页面级溢出 =', info)

asyncio.run(main())
