#!/usr/bin/env python3
"""
audit_pages.py — 全站审计：横向溢出 / 宽表提示一致性 / 字体加载 / 脱敏泄漏

直接通过 CDP 驱动本机 Chrome（Hermes 浏览器 profile），不依赖 browser-harness 守护进程。
用法:
    python3 -m http.server 8099 -d docs &     # 或传线上地址
    python3 tools/audit_pages.py [base_url]
"""
import asyncio, json, os, sys, urllib.request
import websockets

PROFILE = os.path.expanduser('~/.hermes/browser-profile/chrome')
UA = dict(deviceScaleFactor=2, mobile=True, width=402, height=874)

MEASURE = r"""(() => {
  const de = document.documentElement;
  let fp=0, fn=0, ok=0, t=0; const ovf=[];
  document.querySelectorAll('.tbl-wrap').forEach(w=>{
    t++;
    const over = (w.scrollWidth - w.clientWidth) > 2;
    const nx = w.nextElementSibling;
    const hint = !!(nx && nx.className === 'tbl-hint');
    if (over && hint) ok++; else if (over && !hint) fn++; else if (!over && hint) fp++;
    if (over) ovf.push(w.scrollWidth - w.clientWidth);
  });
  const fonts = [...document.fonts].filter(f=>/Tsanger/.test(f.family)).map(f=>f.weight+':'+f.status);
  const h1 = document.querySelector('h1');
  return {doc: de.scrollWidth - de.clientWidth, tables: t, ok, fp, fn, ovf,
          fonts, cards: document.querySelectorAll('.card').length,
          h1font: h1 ? getComputedStyle(h1).fontFamily.split(',')[0] : ''};
})()"""

CARDS = "[...document.querySelectorAll('a.card')].map(a=>a.getAttribute('href'))"


class CDP:
    def __init__(self, ws):
        self.ws, self.i = ws, 0

    async def send(self, method, **params):
        self.i += 1
        await self.ws.send(json.dumps({'id': self.i, 'method': method, 'params': params}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), 60))
            if msg.get('id') == self.i:
                if 'error' in msg:
                    raise RuntimeError(msg['error'])
                return msg.get('result', {})

    async def ev(self, expr):
        r = await self.send('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
        res = r.get('result', {})
        if res.get('subtype') == 'error':
            raise RuntimeError(res.get('description'))
        return res.get('value')


def ws_url():
    port = open(os.path.join(PROFILE, 'DevToolsActivePort')).read().split('\n')[0].strip()
    targets = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=10))
    pages = [t for t in targets if t.get('type') == 'page']
    if not pages:
        raise SystemExit('没有可用的 page target')
    return pages[0]['webSocketDebuggerUrl']


async def settle(c, timeout=15):
    """等页面导航完成（readyState=complete），避免在文档替换竞态中取数"""
    for _ in range(int(timeout * 4)):
        try:
            if await c.ev('document.readyState') == 'complete':
                return
        except Exception:
            pass
        await asyncio.sleep(0.25)


async def main(base):
    async with websockets.connect(ws_url(), max_size=64 * 1024 * 1024) as ws:
        c = CDP(ws)
        await c.send('Page.enable')
        await c.send('Runtime.enable')
        # 同一坑: 站点 CSS 内联在 HTML 里, 不清缓存会量到旧页面, 导致"改完数字不变"
        await c.send('Network.enable')
        await c.send('Network.setCacheDisabled', cacheDisabled=True)
        await c.send('Emulation.setDeviceMetricsOverride', **UA)
        await c.send('Page.navigate', url=base + '/index.html')
        await settle(c)
        await asyncio.sleep(1)
        links = await c.ev(CARDS) or []
        print(f'base={base}  卡片 {len(links)}')
        doc_bad, hint = [], [0, 0, 0]
        tabs = 0
        fonts_seen = set()
        for href in links:
            await c.send('Page.navigate', url=f'{base}/{href}')
            await settle(c)
            r = {}
            for _ in range(3):
                try:
                    r = await c.ev(MEASURE) or {}
                    break
                except Exception:
                    await asyncio.sleep(1.0)  # 导航竞态：文档被替换，重试
            tabs += r.get('tables', 0)
            if r.get('doc', 0) > 2:
                doc_bad.append((href, r['doc']))
            hint[0] += r.get('ok', 0)
            hint[1] += r.get('fn', 0)
            hint[2] += r.get('fp', 0)
            fonts_seen.update(r.get('fonts', []))
        print(f'页面 {len(links)} 份 | 表格 {tabs} 张')
        print(f'页面级横向溢出: {len(doc_bad)}  {doc_bad[:4]}')
        print(f'宽表提示  正确={hint[0]}  漏判={hint[1]}  过报={hint[2]}')
        print(f'kami 字重加载: {sorted(fonts_seen)}')


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8099'))
