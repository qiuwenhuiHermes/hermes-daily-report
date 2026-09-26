#!/usr/bin/env python3
"""
build_site.py — Hermes 每日报告静态站生成器 · kami 设计语言版 v3
从 ~/.hermes/cron/output/ 读取盘后/盘前评估报告，脱敏后渲染成静态 HTML 站点。

v3 变化（design-taste-frontend + redesign-existing-projects 审计后落地）：
  P0-1 字体本地化：18MB TTF×2 → 1.86MB woff2×2（tools/subset_fonts.py 产物）+ preload
  P0-2 宽表提示：CSS 滚动阴影（仅真溢出时出现）+ ≥6 列附文字提示
  P0-3 分享/图标：favicon(svg+png) / apple-touch-icon / og 三件套 / theme-color / description
  P0-4 报告页加 上一条·下一条 导航 + 回到顶部
  P1-5 卡片层次：暖调投影替代"白盒堆叠"，圆角/描边分级
  P1-6 数据表 tabular-nums + 数值列右对齐（按列自动判定）
  P1-7 首页按日期分组 + 栏目标签 + 渐进展开（不再 8000px 长滚动找报告）
  P1-8 指标卡 → 一行紧凑元信息（去掉 inline 字号 hack）
  P1-9 去重：报告页去掉重复眉标；卡片不再重复"栏目+栏目"
  P1-10 小字 12.5px → 13px

设计约束（kami / tw93）: 羊皮纸底 #f5f4ed / 墨蓝 #1B365D 唯一强调色 /
暖灰文本层级 / 单一衬线字体 TsangerJinKai02 / 实色标签底。
用法: python3 build_site.py
"""
import os, re, glob, html
from datetime import datetime

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "docs"))
CRON_OUT = os.path.expanduser("~/.hermes/cron/output")
SITE_URL = "https://qiuwenhuihermes.github.io/hermes-daily-report/"
INITIAL_DAYS = 10  # 首页默认展开最近多少个自然日

# ── 报告源配置 ──
SOURCES = {
    "post_market": {"dir": "aa2ea1b9eeca", "name": "美股盘后评估", "short": "盘后",
                    "icon": "📈", "desc": "四大师视角 × 温度计 × 定投信号"},
    "pre_market":  {"dir": "ce28e750cde0", "name": "美股盘前评估", "short": "盘前",
                    "icon": "🌅", "desc": "盘前宏观与市场预热"},
}
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

MISMATCH = []  # 构建期表格列数异常记录（用于发现源文行粘连等问题）

# ── 脱敏规则 ──
# 注意：分隔符一律用 [ \t]* 而非 \s*，否则会吞掉换行把相邻两行粘成一行（表格串行 bug）
SANITIZE_RULES = [
    (re.compile(r'(¥|￥|\bRMB\b)[ \t]*[\d,]+(?:\.\d+)?[ \t]*(万|千|元)?'), '【金额已脱敏】'),
    (re.compile(r'[\d,]+(?:\.\d+)?[ \t]*万(?:元|块)?(?=[，。;；\s]|$)'), '【金额已脱敏】'),
    (re.compile(r'弹药[ \t]*[\d,-]+[ \t]*[万千]'), '弹药【已脱敏】'),
]


def sanitize(text: str) -> str:
    for pat, rep in SANITIZE_RULES:
        text = pat.sub(rep, text)
    return text


def extract_response(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return ""
    m = re.search(r'^## Response\s*$', raw, re.M)
    if not m:
        return ""
    return sanitize(raw[m.end():].strip())


def parse_report(path: str, meta: dict):
    body = extract_response(path)
    if len(body) < 200:
        return None
    fn = os.path.basename(path)
    m = re.match(r'(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})', fn)
    if not m:
        return None
    date, hh, mm = m.group(1), m.group(2), m.group(3)
    title_m = re.search(r'\*\*(.+?)\*\*', body)
    title = title_m.group(1) if title_m else f"{meta['name']} {date}"
    mkt = ""
    mkt_m = re.search(r'\*\*市场[：:]\*\*\s*(.+)', body)
    if mkt_m:
        mkt = mkt_m.group(1).strip()[:150]
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        dow = WEEKDAYS[dt.weekday()]
        day_label = f"{dt.month}月{dt.day}日"
    except Exception:
        dow, day_label = "", date
    return {"date": date, "day_label": day_label, "dow": dow,
            "time": f"{hh}:{mm}", "title": html.escape(title), "title_raw": title,
            "market": html.escape(mkt), "body": body, "type": meta["name"],
            "short": meta["short"], "icon": meta["icon"]}


def md_to_html(text: str) -> str:
    """极简 markdown → HTML（表格/加粗/标题/列表），kami 样式类"""
    lines = text.split("\n")
    out, in_table, table_rows = [], 0, []

    # ── 表格行识别 ──
    # 标准表格: | a | b |（首尾竖线）; 伪表格: a | b | c（空格包围竖线）
    # 分隔行两种形态: | --- | --- | 与 ---|---|---（无空格）
    SEP_CELL = re.compile(r'^:?-{2,}:?$')
    NUM_CELL = re.compile(r'^[+\-−]?\s*[\d,]+(?:\.\d+)?\s*(%|％|港|倍|亿|万|美元|块|点)?$')

    def split_cells(s: str) -> list:
        """切出单元格（首尾竖线包裹时空首格是真实空列，不做 trim）"""
        if s.startswith('|') and s.endswith('|') and len(s) > 2:
            s = s[1:-1]
        return [inline(c.strip()) for c in s.split('|')]

    def normalize(cells, ncol):
        """统一到表头列数：不足补空列，超出并入最后一列（避免撑出虚拟列）"""
        cells = list(cells)
        if len(cells) > ncol:
            cells = cells[:ncol - 1] + [' '.join(cells[ncol - 1:])]
        while len(cells) < ncol:
            cells.append('')
        return cells

    PROSE_LABEL = re.compile(r'^\*{0,2}[^|*：:]{1,12}[：:]')

    def is_sep_row(cells) -> bool:
        non_empty = [c for c in cells if c]
        return bool(non_empty) and all(SEP_CELL.fullmatch(c) for c in non_empty)

    # 表格块识别: 连续 ≥2 行、含竖线、且**单元格数相同**的"等列数块"才算表格。
    # 为什么不用逐行判定: 曾按"本行是否像表格行 + 相邻行是否也像"来标记，结果遇到
    #     代码|评分|梯队|卡位逻辑
    #     🔴 TSM|77.4|一|先进制程+CoWoS双卡位，AI供给真瓶颈   ← 末格 20 字，超出紧凑式 16 字闸
    # 表头会因"下一行不像表格行"被降级成段落，首行数据反被当成表头（整表列名错位）。
    # 改判整块列数一致，与单行长什么样无关；单行含竖线的散文（如"📊 **美股盘后评估 | 2026-09-25**"）
    # 因凑不出 ≥2 行同类行而不成表。
    BAD_PREFIX = ('- ', '* ', '> ', '#', '1. ', '2. ', '3. ')
    # 括号内的竖线（"NVDA（200.75 | 51%）：AI核心基建…"）+ 句尾标点，都是散文特征而非表格行
    PIPE_IN_PAREN = re.compile(r'（[^（）]{0,24}\|[^（）]{0,24}）')
    rows_cells = []
    for line in lines:
        s = line.strip()
        cells = split_cells(s) if '|' in s and s.count('|') >= 1 and len(s) > 2 else None
        if cells and len(cells) < 2:
            cells = None
        if cells and (PROSE_LABEL.match(s) or s.startswith(BAD_PREFIX)
                      or s.endswith(('。', '！', '？'))
                      or PIPE_IN_PAREN.search(s)):
            cells = None        # "标签：xx | yy" 式散文 / 列表 / 引用 / 括号内竖线 一律不算表格行
        rows_cells.append(cells)

    table_flags = [False] * len(lines)
    i, nlines = 0, len(lines)
    while i < nlines:
        if not rows_cells[i]:
            i += 1
            continue
        ncol = len(rows_cells[i])
        j = i
        while j < nlines and rows_cells[j] and (
                len(rows_cells[j]) == ncol or is_sep_row(rows_cells[j])):
            j += 1
        # 块内夹一行列数不符（LLM 偶尔多/少一个竖线）不打断整块: 下一行回到 ncol 就继续
        while j < nlines - 1 and rows_cells[j] and rows_cells[j + 1] \
                and len(rows_cells[j + 1]) == ncol:
            j += 2
            while j < nlines and rows_cells[j] and (
                    len(rows_cells[j]) == ncol or is_sep_row(rows_cells[j])):
                j += 1
        if j - i >= 2:
            for k in range(i, j):
                table_flags[k] = True
            i = j
        else:
            i += 1

    def plain(c: str) -> str:
        """去标签取纯文本（用于数值列判定）"""
        return re.sub(r'<[^>]+>', '', c).replace('**', '').strip()

    def flush_table():
        nonlocal table_rows
        if not table_rows:
            return
        # 只有表头/分隔行而无数据行 → 实为散文，按段落输出
        if len(table_rows) < 2:
            for s, _ in table_rows:
                out.append(f'<p>{inline(s)}</p>')
            table_rows = []
            return
        header = list(table_rows[0][1])
        ncol = len(header)
        rows = []
        for _, cells in table_rows[1:]:
            if len(cells) > ncol:
                MISMATCH.append((ncol, len(cells), cells[:3]))
            rows.append(normalize(cells, ncol))
        # 数值列判定: 该列 ≥60% 单元格为纯数值形态
        numeric = []
        for j in range(ncol):
            vals = [plain(r[j]) for r in rows if j < len(r) and plain(r[j])]
            if vals and sum(1 for v in vals if NUM_CELL.match(v)) / len(vals) >= 0.6:
                numeric.append(j)
        out.append('<div class="tbl-wrap"><table class="kami-tb striped"><thead><tr>' + ''.join(
            f'<th class="{"num" if j in numeric else ""}">{c}</th>'
            for j, c in enumerate(header)) + '</tr></thead><tbody>')
        for r in rows:
            if len(r) != ncol:
                MISMATCH.append((ncol, len(r), r[:3]))
            out.append('<tr>' + ''.join(
                f'<td class="{"num" if j in numeric else ""}">{c}</td>'
                for j, c in enumerate(r)) + '</tr>')
        out.append('</tbody></table></div>')
        table_rows = []

    for i, line in enumerate(lines):
        s = line.strip()
        if table_flags[i]:
            cells = split_cells(s)
            if is_sep_row(cells):
                continue  # 分隔行丢弃(表头信息保留在上一条)
            # 表格块内: 无首尾竖线且列数多于表头的 "a | b | c" 行实为散文，终止表格
            if (in_table and table_rows and len(cells) > len(table_rows[0][1])
                    and not (s.startswith('|') and s.endswith('|'))):
                flush_table()
                out.append(f'<p>{inline(s)}</p>')
                in_table = 0
                continue
            table_rows.append((s, cells))
            in_table = 1
            continue
        else:
            if in_table:
                flush_table()
                in_table = 0
        if not s:
            out.append('')
            continue
        if s.startswith('###'):
            out.append(f'<h4>{inline(s.lstrip("# ").strip())}</h4>')
        elif s.startswith('##'):
            out.append(f'<h3>{inline(s.lstrip("# ").strip())}</h3>')
        elif re.fullmatch(r'-{3,}', s):
            out.append('<hr>')
        elif s.startswith('**') and s.endswith('**'):
            out.append(f'<p class="lead">{inline(s)}</p>')
        elif re.match(r'^[-·]\s', s):
            out.append(f'<p class="li">{inline(s)}</p>')
        else:
            out.append(f'<p>{inline(s)}</p>')
    if in_table:
        flush_table()
    return '\n'.join(out)


def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    return s


# ── kami Web 字体与基础样式（全部页面共享） ──
# __FONTS__ 为字体相对路径前缀（首页 "fonts/"、报告页 "../fonts/"）
KAMI_CSS = '''
@font-face{font-family:"TsangerJinKai02";src:url("__FONTS__kami-400.woff2") format("woff2");font-weight:400;font-style:normal;font-display:swap}
@font-face{font-family:"TsangerJinKai02";src:url("__FONTS__kami-500.woff2") format("woff2");font-weight:500;font-style:normal;font-display:swap}
:root{--parchment:#f5f4ed;--ivory:#fbfaf6;--sand:#e2dfd1;--near-black:#141413;--dark-warm:#3d3d3a;--olive:#504e49;--stone:#6b6a64;--brand:#1B365D;--brand-ink-light:#2D5A8A;--border:#e4e1d4;--border-soft:#e8e6dc;--tag-bg:#E4ECF5;
--shadow:0 1px 2px rgba(27,54,93,.045),0 10px 24px -14px rgba(27,54,93,.13);
--serif:"TsangerJinKai02","Source Han Serif SC","Noto Serif CJK SC","Songti SC","STSong",Georgia,serif;--sans:var(--serif)}
*{margin:0;padding:0;box-sizing:border-box}
html{background:var(--parchment);-webkit-text-size-adjust:100%;text-size-adjust:100%;scroll-behavior:smooth}
body{background:var(--parchment);color:var(--near-black);font-family:var(--serif);font-size:15px;line-height:1.6;letter-spacing:.15px;-webkit-font-smoothing:antialiased;-webkit-tap-highlight-color:transparent}
strong{font-weight:500;color:var(--near-black)}
a{color:var(--brand-ink-light);text-decoration:none}
.wrap{max-width:1120px;margin:0 auto;padding:72px 48px 88px}
.eyebrow{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--brand);letter-spacing:.25em;font-weight:500;text-transform:uppercase;margin-bottom:14px}
.eyebrow::before{content:"";width:12px;height:2px;border-radius:1px;background:var(--brand);flex-shrink:0}
.foot-note{margin-top:64px;padding-top:14px;border-top:1px dotted var(--border);font-size:13px;color:var(--stone);text-align:center;line-height:1.9;overflow-wrap:anywhere;text-wrap:balance}
/* 表格：横向溢出仅作兜底；滚动阴影只在真溢出时可见（Roman Komarov 技法） */
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:4px;
  background:linear-gradient(to right,var(--parchment) 40%,rgba(245,244,237,0)),
    linear-gradient(to left,var(--parchment) 40%,rgba(245,244,237,0)) 100% 0,
    radial-gradient(farthest-side at 0% 50%,rgba(27,54,93,.16),rgba(27,54,93,0)),
    radial-gradient(farthest-side at 100% 50%,rgba(27,54,93,.16),rgba(27,54,93,0)) 100% 0;
  background-repeat:no-repeat;background-size:32px 100%,32px 100%,14px 100%,14px 100%;
  background-attachment:local,local,scroll,scroll}
.tbl-wrap::-webkit-scrollbar{height:4px}
.tbl-wrap::-webkit-scrollbar-thumb{background:var(--sand);border-radius:2px}
.tbl-hint{font-size:12.5px;color:var(--stone);text-align:center;margin:-6px 0 16px}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}
'''


def css(font_prefix: str) -> str:
    return KAMI_CSS.replace('__FONTS__', font_prefix)


HEAD_COMMON = '''<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<meta name="theme-color" content="#f5f4ed">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="每日观察">
<meta name="format-detection" content="telephone=no">
<link rel="icon" href="__ROOT__favicon.svg" type="image/svg+xml">
<link rel="icon" href="__ROOT__favicon.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="__ROOT__apple-touch-icon.png">
<link rel="preconnect" href="__SITE__" crossorigin>
<link rel="preload" href="__FONTS__kami-400.woff2" as="font" type="font/woff2" crossorigin>
<meta property="og:type" content="website">
<meta property="og:site_name" content="Hermes 每日观察">
<meta property="og:url" content="__OGURL__">
<meta property="og:title" content="__OGTITLE__">
<meta property="og:description" content="__OGDESC__">
<meta property="og:image" content="__OGIMAGE__">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="__OGTITLE__">
<meta name="twitter:description" content="__OGDESC__">
<meta name="twitter:image" content="__OGIMAGE__">'''

DESC_SITE = "美股盘后 / 盘前评估 · 价格温度计 · 定投信号。每交易日由 Hermes Agent 自动生成并部署。"

INDEX_TPL = '''<!DOCTYPE html>
<html lang="zh">
<head>
__HEAD__
<title>Hermes 每日观察</title>
<meta name="description" content="__OGDESC__">
<style>__CSS__
header{margin-bottom:34px}
h1{font-size:40px;font-weight:500;line-height:1.15;color:var(--near-black);margin-bottom:12px;text-wrap:balance}
.sub{font-size:15px;color:var(--olive);line-height:1.6;max-width:52ch;text-wrap:pretty}
.statusline{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px;margin-top:22px;font-size:13px;color:var(--stone);font-variant-numeric:tabular-nums}
.statusline b{font-weight:500;color:var(--near-black);font-size:19px;margin-right:2px}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:26px 0 4px}
.chipf{border:1px solid var(--border);background:var(--ivory);color:var(--olive);font-family:inherit;font-size:13px;padding:7px 14px;border-radius:3px;cursor:pointer;transition:background .18s,color .18s,border-color .18s;display:inline-flex;align-items:center;min-height:44px}
.chipf:hover{border-color:var(--dark-warm);color:var(--near-black)}
.chipf[aria-pressed="true"]{background:var(--brand);border-color:var(--brand);color:#fff}
.chipf:focus-visible{outline:2px solid var(--brand-ink-light);outline-offset:2px}
.day{margin-top:34px}
.day-h{position:sticky;top:0;z-index:5;display:flex;align-items:baseline;gap:9px;font-size:14px;font-weight:500;color:var(--dark-warm);background:var(--parchment);padding:9px 0 8px;border-bottom:1px solid var(--border);margin-bottom:14px}
.day-h .dow{font-size:12.5px;color:var(--stone);font-weight:400;letter-spacing:.06em}
.day-h .n{margin-left:auto;font-size:12.5px;color:var(--stone);font-weight:400;font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.card{display:flex;flex-direction:column;gap:11px;background:var(--ivory);border:1px solid var(--border);border-radius:6px;padding:17px 19px;color:inherit;box-shadow:var(--shadow);transition:transform .18s,border-color .18s,box-shadow .18s}
.card:hover{border-color:#cfcaba;transform:translateY(-1px);box-shadow:0 2px 4px rgba(27,54,93,.05),0 14px 30px -16px rgba(27,54,93,.2)}
.card:active{transform:translateY(0);background:var(--tag-bg)}
.card:focus-visible{outline:2px solid var(--brand-ink-light);outline-offset:2px}
.card-top{display:flex;align-items:center;gap:9px;font-size:13px}
.chip{background:var(--tag-bg);color:var(--brand);font-size:12.5px;font-weight:500;padding:3px 8px;border-radius:3px;letter-spacing:.04em}
.card-time{color:var(--stone);font-variant-numeric:tabular-nums}
.card-go{margin-left:auto;color:var(--stone);font-size:15px;line-height:1}
.card-mkt{font-size:13.5px;color:var(--olive);line-height:1.6;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;text-wrap:pretty}
.more{margin:38px auto 0;display:flex;align-items:center;justify-content:center;min-height:44px;border:1px solid var(--border);background:var(--ivory);color:var(--brand);font-family:inherit;font-size:13.5px;padding:11px 22px;border-radius:3px;cursor:pointer;transition:border-color .18s,background .18s}
.more:hover{border-color:var(--brand);background:var(--tag-bg)}
.more:focus-visible{outline:2px solid var(--brand-ink-light);outline-offset:2px}
.totop{position:fixed;right:18px;bottom:calc(18px + env(safe-area-inset-bottom));width:44px;height:44px;border-radius:50%;background:var(--ivory);border:1px solid var(--border);color:var(--brand);font-size:17px;line-height:1;display:flex;align-items:center;justify-content:center;box-shadow:var(--shadow);opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;z-index:20}
.totop.on{opacity:1;pointer-events:auto}
.totop:hover{transform:translateY(-2px)}
[data-hidden="1"]{display:none!important}
@media(max-width:640px){
.wrap{padding:calc(40px + env(safe-area-inset-top)) 20px calc(56px + env(safe-area-inset-bottom))}
.grid{grid-template-columns:1fr;gap:12px}
h1{font-size:32px}
.statusline{gap:4px 14px}
.day-h{padding:8px 0 7px}
.card{padding:15px 17px}
}
@supports(padding:max(0px)){.wrap{padding-left:max(20px,env(safe-area-inset-left));padding-right:max(20px,env(safe-area-inset-right))}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="eyebrow">Hermes Daily Review</div>
  <h1>每日观察</h1>
  <p class="sub">美股盘后 / 盘前评估 · 价格温度计 · 定投信号。每交易日由 Hermes Agent 自动生成并部署。</p>
  <p class="statusline"><span><b>__COUNT__</b>份报告</span><span>__DAYS__ 个交易日</span><span>__COLUMNS__ 个栏目</span><span>最近更新 __UPDATED__</span></p>
  <div class="filters" role="group" aria-label="按栏目筛选">
    <button class="chipf" type="button" data-filter="all" aria-pressed="true">全部 __COUNT__</button>
    __FILTERS__
  </div>
</header>
<main>
__DAYS_HTML__
__MORE__
</main>
<footer class="foot-note">⚠️ 内容基于公开信息的研究推演，非投资建议 · 金额数据已脱敏<br>Hermes Agent · qiuwenhuiHermes/hermes-daily-report · kami design</footer>
</div>
<a class="totop" href="#" aria-label="回到顶部">↑</a>
<script>
(function(){
  var cards=[].slice.call(document.querySelectorAll('.card'));
  var btns=[].slice.call(document.querySelectorAll('.chipf'));
  var days=[].slice.call(document.querySelectorAll('.day'));
  var more=document.querySelector('.more');
  var revealed=false;
  function apply(f){
    btns.forEach(function(x){x.setAttribute('aria-pressed',String(x.getAttribute('data-filter')===f))});
    cards.forEach(function(c){
      var keep=(f==='all'||c.getAttribute('data-type')===f);
      if(keep){c.removeAttribute('data-hidden')}else{c.setAttribute('data-hidden','1')}
    });
    days.forEach(function(d){
      var collapsible=!!d.querySelector('.card[data-hidden]');
      if(f==='all'&&!revealed&&d.hasAttribute('data-old')){d.setAttribute('data-hidden','1');return}
      var vis=d.querySelectorAll('.card:not([data-hidden])').length;
      d.setAttribute('data-hidden',vis?'0':'1');
    });
    if(more){more.setAttribute('data-hidden',(!revealed&&f==='all')?'0':'1')}
  }
  btns.forEach(function(b){b.addEventListener('click',function(){apply(b.getAttribute('data-filter'))})});
  if(more){more.addEventListener('click',function(){
    revealed=true;
    [].slice.call(document.querySelectorAll('.day[data-old]')).forEach(function(d){d.removeAttribute('data-old');d.removeAttribute('data-hidden')});
    more.setAttribute('data-hidden','1');
  })}
  var tt=document.querySelector('.totop');
  window.addEventListener('scroll',function(){
    if(window.scrollY>600){tt.classList.add('on')}else{tt.classList.remove('on')}
  },{passive:true});
})();
</script>
</body>
</html>'''


def build_index(reports):
    # 按日期分组（reports 已按 date desc 排序）
    days, order = {}, []
    for r in reports:
        d = r["date"]
        if d not in days:
            days[d] = []
            order.append(d)
        days[d].append(r)
    filter_counts = {}
    for r in reports:
        filter_counts[r["type_key"]] = filter_counts.get(r["type_key"], 0) + 1
    chips = ''.join(
        f'<button class="chipf" type="button" data-filter="{k}" aria-pressed="false">'
        f'{SOURCES[k]["icon"]} {SOURCES[k]["short"]} {v}</button>'
        for k, v in filter_counts.items())

    blocks = []
    for idx, d in enumerate(order):
        rs = days[d]
        old = ' data-old="1" data-hidden="1"' if idx >= INITIAL_DAYS else ''
        cards = []
        for r in rs:
            cards.append(f'''<a class="card" data-type="{r['type_key']}" href="reports/{r['date']}-{r['type_key']}.html">
  <div class="card-top"><span class="chip">{r['icon']} {r['short']}</span><span class="card-time">{r['time']}</span><span class="card-go" aria-hidden="true">›</span></div>
  <div class="card-mkt">{r['market'] or r['type']}</div>
</a>''')
        blocks.append(f'''<section class="day"{old} data-date="{d}">
  <h2 class="day-h">{rs[0]['day_label']}<span class="dow">{rs[0]['dow']}</span><span class="n">{len(rs)} 份</span></h2>
  <div class="grid">
{chr(10).join(cards)}
  </div>
</section>''')
    hidden_n = sum(len(days[d]) for d in order[INITIAL_DAYS:])
    more = (f'<button class="more" type="button">显示更早的报告（{hidden_n} 份 / {len(order) - INITIAL_DAYS} 天）</button>'
            if hidden_n else '')
    head = (HEAD_COMMON.replace('__ROOT__', '').replace('__FONTS__', 'fonts/')
            .replace('__SITE__', SITE_URL).replace('__OGURL__', SITE_URL)
            .replace('__OGTITLE__', 'Hermes 每日观察 · 美股盘后/盘前评估')
            .replace('__OGDESC__', DESC_SITE)
            .replace('__OGIMAGE__', SITE_URL + 'assets/og.png'))
    return (INDEX_TPL
            .replace('__HEAD__', head).replace('__CSS__', css('fonts/'))
            .replace('__OGDESC__', DESC_SITE)
            .replace('__COUNT__', str(len(reports)))
            .replace('__DAYS__', str(len(order)))
            .replace('__COLUMNS__', str(len(filter_counts)))
            .replace('__UPDATED__', datetime.now().strftime('%m-%d %H:%M'))
            .replace('__FILTERS__', chips)
            .replace('__DAYS_HTML__', '\n'.join(blocks))
            .replace('__MORE__', more))


def build_report_page(r, prev_r, next_r):
    """prev_r = 较新一篇, next_r = 较早一篇"""
    def link(rr, arrow, cls):
        if not rr:
            lab = '已是最新' if cls == 'pn-a' else '已是最早'
            return (f'<span class="pn-x {cls}">'
                    f'<span class="pn-lab">{arrow}</span>'
                    f'<span class="pn-none">{lab}</span></span>')
        return (f'<a class="{cls}" href="{rr["date"]}-{rr["type_key"]}.html">'
                f'<span class="pn-lab">{arrow}</span>'
                f'{rr["day_label"]} {rr["short"]}</a>')
    og_desc = re.sub(r'\s+', ' ', r["market"] or r["type"])[:150]
    head = (HEAD_COMMON.replace('__ROOT__', '../').replace('__FONTS__', '../fonts/')
            .replace('__SITE__', SITE_URL)
            .replace('__OGURL__', f'{SITE_URL}reports/{r["date"]}-{r["type_key"]}.html')
            .replace('__OGTITLE__', f'{r["title_raw"]}')
            .replace('__OGDESC__', og_desc)
            .replace('__OGIMAGE__', SITE_URL + 'assets/og.png'))
    return (REPORT_TPL
            .replace('__HEAD__', head).replace('__CSS__', css('../fonts/'))
            .replace('__TITLE__', f'{r["icon"]} {r["title_raw"]}')
            .replace('__DESC__', og_desc)
            .replace('__DATE__', f'{r["day_label"]} {r["time"]}')
            .replace('__BODY__', md_to_html(r["body"]))
            .replace('__PREV__', link(prev_r, '← 较新', 'pn-a'))
            .replace('__NEXT__', link(next_r, '较早 →', 'pn-b')))


REPORT_TPL = '''<!DOCTYPE html>
<html lang="zh">
<head>
__HEAD__
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<style>__CSS__
.wrap{max-width:860px}
.top{position:sticky;top:0;z-index:10;display:flex;justify-content:space-between;align-items:baseline;gap:12px;background:var(--parchment);padding:12px 0 13px;margin-bottom:24px;border-bottom:.5px solid var(--border)}
.back{font-size:14px;color:var(--brand-ink-light);white-space:nowrap;padding:11px 2px}
.back:focus-visible,a:focus-visible{outline:2px solid var(--brand-ink-light);outline-offset:2px;border-radius:2px}
.meta{font-size:13px;color:var(--stone);font-variant-numeric:tabular-nums;white-space:nowrap}
h1{font-size:28px;font-weight:500;line-height:1.3;margin-bottom:26px;text-wrap:balance}
.rpt-body{font-size:15px;line-height:1.75;letter-spacing:.15px;color:var(--near-black);overflow-wrap:anywhere}
.rpt-body p{margin:0 0 13px}
.rpt-body .li{padding-left:18px;position:relative}
.rpt-body h3,.rpt-body h4{margin:26px 0 10px;font-weight:500;color:var(--near-black)}
.rpt-body h3{font-size:20px}
.rpt-body h4{font-size:16.5px;color:var(--dark-warm)}
.rpt-body hr{border:none;border-top:.5px solid var(--border);margin:24px 0}
.rpt-body .lead{font-size:16px;font-weight:500;color:var(--near-black)}
.kami-tb{width:100%;border-collapse:collapse;margin:14px 0;font-size:13.5px;font-variant-numeric:tabular-nums}
.kami-tb th{text-align:left;font-weight:500;color:var(--near-black);padding:9px 10px;border-bottom:1px solid var(--border);white-space:nowrap}
.kami-tb td{padding:9px 10px;border-bottom:.5px solid var(--border-soft);vertical-align:top;color:var(--near-black);overflow-wrap:break-word}
.kami-tb .num{text-align:right}
.kami-tb.striped tbody tr:nth-child(even) td{background:rgba(61,59,53,.045)}
.pn{display:flex;justify-content:space-between;gap:14px;align-items:stretch;margin:44px 0 8px;padding-top:18px;border-top:.5px solid var(--border);font-size:13.5px}
.pn a{flex:1;background:var(--ivory);border:1px solid var(--border);border-radius:6px;padding:14px 16px;box-shadow:var(--shadow);transition:border-color .18s,transform .18s;font-size:15px;color:var(--brand);display:block}
.pn a:hover{border-color:#cfcaba;transform:translateY(-1px)}
.pn .pn-b{text-align:right}
.pn .pn-lab{display:block;font-size:11.5px;color:var(--stone);letter-spacing:.06em;margin-bottom:5px}
.pn .pn-x{flex:1;padding:14px 16px;border:1px dashed var(--border);border-radius:6px;display:block}
.pn .pn-b.pn-x{text-align:right}
.pn .pn-none{display:block;font-size:14px;color:#a9a498}
.totop{position:fixed;right:18px;bottom:calc(18px + env(safe-area-inset-bottom));width:42px;height:42px;border-radius:50%;background:var(--ivory);border:1px solid var(--border);color:var(--brand);font-size:17px;display:flex;align-items:center;justify-content:center;box-shadow:var(--shadow);opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;z-index:20}
.totop.on{opacity:1;pointer-events:auto}
.totop:hover{transform:translateY(-2px)}
@media(max-width:640px){
.wrap{padding:calc(22px + env(safe-area-inset-top)) 18px calc(52px + env(safe-area-inset-bottom))}
h1{font-size:23px;margin-bottom:22px}
.rpt-body{font-size:16px;line-height:1.85}
.rpt-body h3{font-size:19px}
.rpt-body h4{font-size:17px}
.kami-tb{font-size:13px}
.pn{flex-direction:column;gap:10px}
.pn .pn-b{text-align:left}
.top{padding:10px 0 12px}
}
</style>
</head>
<body>
<div class="wrap">
<div class="top"><a class="back" href="../index.html">← 返回首页</a><span class="meta">__DATE__</span></div>
<h1>__TITLE__</h1>
<div class="rpt-body">
__BODY__
</div>
<nav class="pn" aria-label="报告导航">__PREV__ __NEXT__</nav>
<footer class="foot-note">非投资建议 · 金额已脱敏 · Hermes Agent 自动部署 · kami design</footer>
</div>
<a class="totop" href="#" aria-label="回到顶部">↑</a>
<script>
(function(){var t=document.querySelector('.totop');
window.addEventListener('scroll',function(){if(window.scrollY>600){t.classList.add('on')}else{t.classList.remove('on')}},{passive:true});
// 宽表提示：运行时按真实溢出量决定（构建期预估不准）
function mark(){[].slice.call(document.querySelectorAll('.tbl-wrap')).forEach(function(w){
  var over=(w.scrollWidth-w.clientWidth)>2, nx=w.nextElementSibling, has=nx&&nx.className==='tbl-hint';
  if(over&&!has){var p=document.createElement('p');p.className='tbl-hint';p.textContent='← 左右滑动查看完整表格 →';w.parentNode.insertBefore(p,w.nextSibling);}
  else if(!over&&has){nx.remove();}});}
mark();window.addEventListener('resize',mark,{passive:true});window.addEventListener('orientationchange',mark,{passive:true});
if(document.fonts&&document.fonts.ready){document.fonts.ready.then(mark);}})();
</script>
</body>
</html>'''


def main():
    os.makedirs(os.path.join(OUT, "reports"), exist_ok=True)
    reports = []
    for key, meta in SOURCES.items():
        d = os.path.join(CRON_OUT, meta["dir"])
        for f in sorted(glob.glob(os.path.join(d, "*.md")), reverse=True):
            r = parse_report(f, meta)
            if r:
                r["type_key"] = key
                reports.append(r)
    reports.sort(key=lambda r: (r["date"], r["type"] == "美股盘后评估"), reverse=True)
    seen, final = set(), []
    for r in reports:
        k = (r["date"], r["type_key"])
        if k in seen:
            continue
        seen.add(k)
        final.append(r)
    # 报告页（含上一条/下一条）
    for i, r in enumerate(final):
        page = build_report_page(r, final[i - 1] if i > 0 else None,
                                 final[i + 1] if i + 1 < len(final) else None)
        with open(os.path.join(OUT, "reports", f"{r['date']}-{r['type_key']}.html"), "w") as f:
            f.write(page)
    with open(os.path.join(OUT, "index.html"), "w") as f:
        f.write(build_index(final))
    print(f"OK: {len(final)} reports -> {OUT}")
    if MISMATCH:
        print(f"⚠️ 表格列数不一致 {len(MISMATCH)} 处（可能源文行被粘连）:")
        for h, n, sample in MISMATCH[:5]:
            print(f"   表头 {h} 列 / 数据行 {n} 列 | {sample}")


if __name__ == "__main__":
    main()
