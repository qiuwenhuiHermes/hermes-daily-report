#!/usr/bin/env python3
"""
build_site.py — Hermes 每日报告静态站生成器
从 ~/.hermes/cron/output/ 读取盘后评估报告，脱敏后渲染成静态 HTML 站点。
用法: python3 build_site.py [--out ./docs]
"""
import os, re, json, glob, html
from datetime import datetime

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "docs"))
CRON_OUT = os.path.expanduser("~/.hermes/cron/output")

# ── 报告源配置 ──
SOURCES = {
    "post_market": {"dir": "aa2ea1b9eeca", "name": "美股盘后评估", "icon": "📈", "desc": "四大师视角 × 温度计 × 定投信号"},
    "pre_market":  {"dir": "ce28e750cde0", "name": "美股盘前评估", "icon": "🌅", "desc": "盘前宏观与市场预热"},
}

# ── 脱敏规则 ──
SANITIZE_RULES = [
    # 具体金额 → 区间化/移除（¥2000 / 4000元 / 6600 等）
    (re.compile(r'(¥|￥|\bRMB\b)\s*[\d,]+(?:\.\d+)?\s*(万|千|元)?'), '【金额已脱敏】'),
    # 持仓总额
    (re.compile(r'[\d,]+(?:\.\d+)?\s*万(?:元|块)?(?=[，。;；\s]|$)'), '【金额已脱敏】'),
    # 弹药表述中的具体数
    (re.compile(r'弹药\s*[\d,-]+\s*[万千]'), '弹药【已脱敏】'),
]


def sanitize(text: str) -> str:
    for pat, rep in SANITIZE_RULES:
        text = pat.sub(rep, text)
    return text


def extract_response(path: str) -> str:
    """提取 cron 输出里 ## Response 之后的正文"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return ""
    m = re.search(r'^## Response\s*$', raw, re.M)
    if not m:
        return ""
    body = raw[m.end():].strip()
    return sanitize(body)


def parse_report(path: str, meta: dict):
    body = extract_response(path)
    if len(body) < 200:
        return None
    fn = os.path.basename(path)
    m = re.match(r'(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})', fn)
    if not m:
        return None
    date, hh, mm = m.group(1), m.group(2), m.group(3)
    # 提取标题行（第一个 ** 加粗行或 # 标题）
    title_m = re.search(r'\*\*(.+?)\*\*', body)
    title = title_m.group(1) if title_m else f"{meta['name']} {date}"
    # 提取市场行
    mkt = ""
    mkt_m = re.search(r'\*\*市场[：:]\*\*\s*(.+)', body)
    if mkt_m:
        mkt = mkt_m.group(1).strip()[:120]
    return {"date": date, "time": f"{hh}:{mm}", "title": html.escape(title),
            "market": html.escape(mkt), "body": body, "type": meta["name"],
            "icon": meta["icon"]}


def md_to_html(text: str) -> str:
    """极简 markdown → HTML（表格/加粗/标题/列表），不依赖外部库"""
    lines = text.split("\n")
    out, i, in_table, table_rows = [], 0, 0, []
    def flush_table():
        nonlocal table_rows
        if table_rows:
            out.append('<table class="rpt-tb"><thead><tr>' + ''.join(
                f'<th>{c}</th>' for c in table_rows[0]) + '</tr></thead><tbody>')
            for row in table_rows[2:] if len(table_rows) > 2 else []:
                out.append('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>')
            out.append('</tbody></table>')
            table_rows = []

    for line in lines:
        s = line.strip()
        # 表格行
        if s.startswith('|') and s.endswith('|'):
            cells = [html.escape(c.strip()) for c in s.strip('|').split('|')]
            if all(re.fullmatch(r':?-{2,}:?', c) for c in cells):
                continue  # 分隔行
            table_rows.append(cells)
            in_table = 1
            continue
        else:
            if in_table:
                flush_table()
                in_table = 0
        if not s:
            out.append('')
            continue
        # 标题
        if s.startswith('###'):
            out.append(f'<h4>{inline(s.lstrip("# ").strip())}</h4>')
        elif s.startswith('##'):
            out.append(f'<h3>{inline(s.lstrip("# ").strip())}</h3>')
        # 分割线
        elif re.fullmatch(r'-{3,}', s):
            out.append('<hr>')
        # 加粗行
        elif s.startswith('**') and s.endswith('**'):
            out.append(f'<p class="lead">{inline(s)}</p>')
        else:
            out.append(f'<p>{inline(s)}</p>')
    if in_table:
        flush_table()
    return '\n'.join(out)


def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'⭐+', lambda m: f'<span class="stars">{m.group(0)}</span>', s)
    s = re.sub(r'(🟢|🔴|⛔|⚡|💰|📋|🔗|🌡|⚠)', r'<span class="em">\1</span>', s)
    return s


def build_index(reports):
    cards = []
    for r in reports[:60]:
        cards.append(f'''<a class="card" href="reports/{r['date']}-{r['type_key']}.html">
  <div class="card-top"><span class="card-icon">{r['icon']}</span>
    <span class="card-type">{r['type']}</span><span class="card-date">{r['date']}</span></div>
  <div class="card-title">{r['title']}</div>
  <div class="card-mkt">{r['market']}</div>
</a>''')
    return INDEX_TPL.replace('{{CARDS}}', '\n'.join(cards)).replace(
        '{{UPDATED}}', datetime.now().strftime('%Y-%m-%d %H:%M')).replace(
        '{{COUNT}}', str(len(reports)))


def build_report_page(r):
    return REPORT_TPL.replace('{{TITLE}}', f"{r['icon']} {r['title']}").replace(
        '{{DATE}}', f"{r['date']} {r['time']}").replace('{{TYPE}}', r['type']).replace(
        '{{BODY}}', md_to_html(r['body'])).replace(
        '{{HOME}}', '../index.html')


INDEX_TPL = '''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes 每日观察</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0b10;color:#e8eaf0;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;padding:24px 16px 60px}
.wrap{max-width:860px;margin:0 auto}
header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
h1{font-size:26px;font-weight:700}
h1 span{color:#4f7cff}
.sub{color:#8b90a0;font-size:13px;margin-bottom:24px}
.stats{display:flex;gap:12px;margin-bottom:22px}
.stat{flex:1;background:#141726;border:1px solid #262b3d;border-radius:10px;padding:12px 14px}
.stat .v{font-size:20px;font-weight:700;color:#4f7cff}
.stat .l{font-size:12px;color:#8b90a0;margin-top:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:14px}
.card{background:#141726;border:1px solid #262b3d;border-radius:12px;padding:16px 18px;text-decoration:none;color:#e8eaf0;transition:border-color .15s}
.card:hover{border-color:#4f7cff}
.card-top{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:12px}
.card-type{color:#4f7cff;font-weight:600}
.card-date{color:#5d6272;margin-left:auto}
.card-title{font-size:15px;font-weight:600;line-height:1.45;margin-bottom:6px}
.card-mkt{font-size:12px;color:#8b90a0;line-height:1.5;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
footer{margin-top:40px;text-align:center;color:#5d6272;font-size:12px}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
<header><h1>Hermes <span>每日观察</span></h1><span class="sub">自动更新</span></header>
<div class="sub">美股盘后/盘前评估 · 温度计 · 定投信号 · 由 Hermes Agent 自动生成并部署</div>
<div class="stats">
<div class="stat"><div class="v">{{COUNT}}</div><div class="l">已收录报告</div></div>
<div class="stat"><div class="v">2</div><div class="l">日更栏目</div></div>
<div class="stat"><div class="v">{{UPDATED}}</div><div class="l">最近构建</div></div>
</div>
<div class="grid">
{{CARDS}}
</div>
<footer>⚠️ 内容基于公开信息的研究推演，非投资建议 · 金额数据已脱敏<br>Hermes Agent · qiuwenhuiHermes/hermes-daily-report</footer>
</div>
</body>
</html>'''


REPORT_TPL = '''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0b10;color:#e8eaf0;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;padding:20px 16px 60px}
.wrap{max-width:860px;margin:0 auto}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.back{color:#4f7cff;text-decoration:none;font-size:14px}
.meta{color:#8b90a0;font-size:13px}
.rpt-body{font-size:15px;line-height:1.8}
.rpt-body p{margin:0 0 12px}
.rpt-body h3,.rpt-body h4{margin:18px 0 10px;font-size:17px;color:#fff}
.rpt-body hr{border:none;border-top:1px solid #262b3d;margin:18px 0}
.rpt-body .lead{font-size:16px;font-weight:600;color:#fff}
.rpt-body strong{color:#fff}
.stars{color:#e8c547;letter-spacing:2px}
.em{font-size:17px}
.rpt-tb{width:100%;border-collapse:collapse;margin:12px 0;font-size:13.5px}
.rpt-tb th{background:#1b1f31;color:#9aa2b8;padding:8px 10px;text-align:left;font-weight:600;border-bottom:1px solid #2a2f45}
.rpt-tb td{padding:7px 10px;border-bottom:1px solid #1e2334;color:#c3c8d8}
footer{margin-top:36px;color:#5d6272;font-size:12px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
<div class="top"><a class="back" href="{{HOME}}">← 返回首页</a><span class="meta">{{TYPE}} · {{DATE}}</span></div>
<h1 style="font-size:22px;margin-bottom:18px">{{TITLE}}</h1>
<div class="rpt-body">
{{BODY}}
</div>
<footer>⚠️ 非投资建议 · 金额已脱敏 · Hermes Agent 自动部署</footer>
</div>
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
    # 每天最多保留盘后+盘前各一
    seen, final = set(), []
    for r in reports:
        k = (r["date"], r["type_key"])
        if k in seen:
            continue
        seen.add(k)
        final.append(r)
    for r in final:
        page = build_report_page(r)
        with open(os.path.join(OUT, "reports", f"{r['date']}-{r['type_key']}.html"), "w") as f:
            f.write(page)
    with open(os.path.join(OUT, "index.html"), "w") as f:
        f.write(build_index(final))
    print(f"OK: {len(final)} reports -> {OUT}")
    print(f"index: {os.path.join(OUT, 'index.html')}")


if __name__ == "__main__":
    main()
