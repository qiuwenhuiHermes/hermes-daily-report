#!/usr/bin/env python3
"""生成 docs/stats.html —— Agent 运营统计页（token / cron / 工具）。

数据源（全部只读）:
  ~/.hermes/state.db session_model_usage  -> token 用量(按模型/按天; 权威)
     注: messages.token_count 对智谱 provider 恒为 0, 不可用
  ~/.hermes/cron/executions.db            -> cron 执行史与故障
  ~/.hermes/cron/jobs.json                -> 任务名
  ~/.hermes/state.db messages.tool_calls  -> 工具调用排行

隐私: 错误文本中的绝对路径/姓名脱敏; 不展示任何金额(token 不是金额);
      meta robots noindex。
"""
import collections
import datetime
import importlib.util
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DB = Path.home() / ".hermes" / "state.db"
CRON_DB = Path.home() / ".hermes" / "cron" / "executions.db"
JOBS_JSON = Path.home() / ".hermes" / "cron" / "jobs.json"
OUT = ROOT / "docs" / "stats.html"


def load_kami_css():
    spec = importlib.util.spec_from_file_location("bs", ROOT / "build_site.py")
    assert spec and spec.loader
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)
    return bs.KAMI_CSS.replace("__FONTS__", "fonts/")


def sanitize(s: str, n=110):
    s = re.sub(r"/Users/[^\s'\"，。;]+", "[本地路径]", s or "")
    s = s.replace("文辉", "用户")
    s = s.replace("\n", " ")
    return s[:n] + ("…" if len(s) > n else "")


def fmt_k(n):  # 千分位
    return f"{n:,}" if n else "0"


def fmt_m(n):  # 百万缩写
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def dur(sec):
    if sec is None:
        return "-"
    if sec >= 3600:
        return f"{sec/3600:.1f}h"
    if sec >= 60:
        return f"{sec/60:.0f}m"
    return f"{sec:.0f}s"


def day(ts):
    return datetime.datetime.fromtimestamp(ts)


# ── token ──
def token_stats():
    db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    models = db.execute("""
        SELECT model, SUM(api_call_count), SUM(input_tokens), SUM(output_tokens),
               SUM(cache_read_tokens)
        FROM session_model_usage GROUP BY model ORDER BY SUM(api_call_count) DESC
    """).fetchall()
    win = db.execute("SELECT MIN(first_seen), MAX(first_seen) FROM session_model_usage").fetchone()
    daily = collections.defaultdict(lambda: [0, 0, 0])
    for ts, i, o, cr in db.execute(
            "SELECT first_seen, input_tokens, output_tokens, cache_read_tokens FROM session_model_usage"):
        d = day(ts).strftime("%Y-%m-%d")
        daily[d][0] += i or 0
        daily[d][1] += o or 0
        daily[d][2] += cr or 0
    db.close()
    span = (day(win[0]).strftime("%Y-%m-%d"), day(win[1]).strftime("%Y-%m-%d")) if win and win[0] else None
    return models, sorted(daily.items()), span


# ── cron ──
def cron_stats():
    name_of = {}
    try:
        j = json.load(open(JOBS_JSON))
        for job in (j if isinstance(j, list) else j.get("jobs", [])):
            if isinstance(job, dict):
                name_of[job.get("id")] = job.get("name") or (job.get("prompt") or "")[:24]
    except Exception:
        pass
    if not CRON_DB.exists():
        return [], [], 0
    db = sqlite3.connect(f"file:{CRON_DB}?mode=ro", uri=True)
    rows = db.execute("""
        SELECT job_id, status, COUNT(*),
               AVG((julianday(finished_at)-julianday(started_at))*86400)
        FROM executions
        WHERE finished_at IS NOT NULL AND started_at IS NOT NULL OR status!='completed'
        GROUP BY job_id, status
    """).fetchall()
    last_runs = {}
    for jid, st, started, status, err in db.execute(
            "SELECT job_id, MAX(started_at), MAX(started_at), status, error FROM executions "
            "GROUP BY job_id"):
        last_runs[jid] = (started, status, err)
    per_job = collections.defaultdict(lambda: {"ok": 0, "fail": 0, "dur": []})
    for jid, status, n, avg in rows:
        j = per_job[jid]
        if status == "completed":
            j["ok"] += n
            if avg is not None:
                j["dur"].append((n, avg))  # 加权用
        else:
            j["fail"] += n
    # 最近一次状态单独查（含无 finished 的）
    last2 = {}
    for jid in per_job:
        r = db.execute(
            "SELECT started_at, status, error FROM executions WHERE job_id=? "
            "ORDER BY started_at DESC LIMIT 1", (jid,)).fetchone()
        if r:
            # error 另取: 最近一次失败的 error
            e = db.execute(
                "SELECT error FROM executions WHERE job_id=? AND error IS NOT NULL "
                "ORDER BY started_at DESC LIMIT 1", (jid,)).fetchone()
            last2[jid] = (r[1], sanitize(e[0]) if e and e[0] else "")
    incidents = db.execute(
        "SELECT job_id, last_seen_at, error FROM cron_incidents "
        "WHERE closed_at IS NULL ORDER BY last_seen_at DESC LIMIT 6").fetchall()
    db.close()
    out = []
    for jid, j in per_job.items():
        total = j["ok"] + j["fail"]
        wavg = sum(n * a for n, a in j["dur"]) / max(sum(n for n, _ in j["dur"]), 1) if j["dur"] else None
        out.append({
            "name": name_of.get(jid) or f"（已删除 {jid[:8]}）",
            "ok": j["ok"], "fail": j["fail"], "total": total,
            "rate": round(j["ok"] / total * 100) if total else 0,
            "avg": wavg,
            "last": last2.get(jid, ("-", "")),
        })
    out.sort(key=lambda x: (-x["total"]))
    inc = [{"job": name_of.get(i[0]) or i[0][:8], "seen": i[1][:16], "err": sanitize(i[2], 90)}
           for i in incidents]
    return out, inc, len(inc)


# ── tools ──
def tool_stats():
    db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    c = collections.Counter()
    for (tc,) in db.execute(
            "SELECT tool_calls FROM messages WHERE tool_calls IS NOT NULL AND tool_calls != '[]'"):
        try:
            calls = json.loads(tc)
        except Exception:
            continue
        for call in calls:
            fn = (call.get("function") or {}).get("name", "")
            if fn:
                c[fn] += 1
    db.close()
    return c.most_common(14)


def main():
    models, daily, span = token_stats()
    crons, incidents, n_inc = cron_stats()
    tools = tool_stats()

    # token 模型表
    tot_in = sum(m[2] for m in models)
    tot_out = sum(m[3] for m in models)
    tot_cache = sum(m[4] for m in models)
    tot_calls = sum(m[1] for m in models)
    model_rows = "\n".join(
        f"<tr><td><b>{m[0]}</b></td><td>{fmt_k(m[1])}</td><td>{fmt_k(m[2])}</td>"
        f"<td>{fmt_k(m[3])}</td><td>{fmt_k(m[4])}</td></tr>" for m in models)

    # 近 30 天每日柱（in+out 一根，cache 另列）
    d30 = daily[-30:]
    peak = max((i + o for _, (i, o, _) in d30), default=1) or 1
    bars = []
    for d, (i, o, cr) in d30:
        h = max(round((i + o) / peak * 64), 1)
        bars.append(
            f'<div class="bcol" title="{d} · 输入 {fmt_k(i)} 输出 {fmt_k(o)} 缓存读 {fmt_k(cr)}">'
            f'<div class="bar" style="height:{h}px"></div>'
            f'<span class="blabel">{d[5:]}</span></div>')
    bars_html = "".join(bars)

    # cron 表
    cron_rows = []
    for j in crons:
        last_status, last_err = j["last"]
        st_cls = "ok" if last_status == "completed" else "bad"
        rate_cls = "r-good" if j["rate"] >= 90 else ("r-mid" if j["rate"] >= 60 else "r-bad")
        err = f'<div class="lasterr">{last_err}</div>' if last_err else ""
        cron_rows.append(
            f'<tr><td><b>{j["name"]}</b>{err}</td>'
            f'<td class="num">{j["total"]}</td>'
            f'<td class="num {rate_cls}">{j["rate"]}%</td>'
            f'<td class="num">{j["fail"]}</td>'
            f'<td class="num">{dur(j["avg"])}</td>'
            f'<td class="num"><span class="dot {st_cls}"></span>{"完成" if st_cls=="ok" else "失败"}</td></tr>')
    cron_html = "".join(cron_rows)

    inc_html = ""
    if incidents:
        items = "".join(
            f'<li><b>{i["job"]}</b><span class="idate">{i["seen"]}</span>'
            f'<div class="ierr">{i["err"] or "（见执行错误）"}</div></li>' for i in incidents)
        inc_html = f'<h2>未关闭的故障</h2><ul class="incList">{items}</ul>'

    # 工具排行
    tool_max = tools[0][1] if tools else 1
    tool_rows = "".join(
        f'<li><span class="tname">{n}</span><span class="tbar"><i style="width:{round(v/tool_max*100)}%"></i></span>'
        f'<b class="tnum">{fmt_k(v)}</b></li>' for n, v in tools)

    span_txt = f"{span[0]} → {span[1]}" if span else "无数据"
    today = datetime.date.today().strftime("%Y-%m-%d %H:%M")

    kami_css = load_kami_css()
    css = """
.wrap{max-width:1080px;margin:0 auto;padding:56px 24px 72px}
.eyebrow{font-size:12.5px;letter-spacing:.18em;color:var(--stone);text-transform:uppercase;margin-bottom:14px}
h1{font-family:"TsangerJinKai02",serif;font-size:34px;font-weight:500;color:var(--near-black);margin:0 0 12px}
h2{font-family:"TsangerJinKai02",serif;font-size:21px;font-weight:500;color:var(--near-black);margin:44px 0 14px;padding-top:10px;border-top:1px solid var(--border)}
.sub{font-size:14.5px;color:var(--olive);line-height:1.75;max-width:62ch;margin:0 0 16px}
.statusline{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--stone);font-variant-numeric:tabular-nums;margin-bottom:8px}
.statusline b{color:var(--brand);font-weight:500}
.back{font-size:14px;color:var(--brand-ink-light);padding:11px 2px;display:inline-block;min-height:44px}
.tbl-wrap{overflow-x:auto;margin:6px 0 4px;border:1px solid var(--border-soft);border-radius:6px;background:var(--ivory)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{font-weight:500;text-align:left;color:var(--olive);border-bottom:1.5px solid var(--brand);padding:10px 14px;white-space:nowrap;font-size:12.5px}
td{padding:10px 14px;border-bottom:.5px solid var(--border-soft);color:var(--dark-warm);vertical-align:top}
tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.lasterr{font-size:12px;color:var(--stone);margin-top:4px;max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.r-good{color:var(--brand)}
.r-mid{color:var(--olive)}
.r-bad{color:#8a3b2e}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:1px}
.dot.ok{background:var(--brand)}
.dot.bad{background:#8a3b2e}
.chart{display:flex;align-items:flex-end;gap:2px;background:var(--ivory);border:1px solid var(--border-soft);border-radius:6px;padding:16px 12px 8px;overflow-x:auto}
.bcol{display:flex;flex-direction:column;align-items:center;gap:4px;flex:1;min-width:16px}
.bar{width:100%;max-width:20px;background:var(--tag-bg);border:1px solid #c9d8e8;border-radius:2px 2px 0 0}
.blabel{font-size:9.5px;color:var(--stone);transform:rotate(-60deg) translate(3px,2px);white-space:nowrap;height:26px}
.chartnote{font-size:12px;color:var(--stone);margin-top:8px}
.toolList{list-style:none;padding:0;margin:10px 0 0;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:8px 22px}
.toolList li{display:flex;align-items:center;gap:10px}
.tname{width:132px;font-size:13px;color:var(--dark-warm);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tbar{flex:1;height:8px;background:transparent;border:0;position:relative}
.tbar i{display:block;height:100%;background:var(--tag-bg);border:1px solid #c9d8e8;border-radius:2px}
.tnum{font-size:12.5px;color:var(--brand);font-variant-numeric:tabular-nums;width:52px}
.incList{list-style:none;padding:0;margin:8px 0}
.incList li{background:var(--ivory);border:1px solid var(--border);border-left:2px solid #8a3b2e;border-radius:4px;padding:11px 15px;margin-bottom:8px;font-size:13.5px}
.idate{float:right;font-size:12px;color:var(--stone)}
.ierr{font-size:12.5px;color:var(--stone);margin-top:5px;overflow-wrap:anywhere}
.foot-note{margin-top:46px;font-size:12px;color:var(--stone);line-height:1.8;text-align:center}
.totip{font-size:11.5px;color:var(--stone);font-weight:400}
@media(max-width:640px){
.wrap{padding:calc(40px + env(safe-area-inset-top)) 20px calc(56px + env(safe-area-inset-bottom))}
h1{font-size:30px}
.kpis{grid-template-columns:1fr 1fr}
.toolList{grid-template-columns:1fr}
.tname{width:104px;font-size:12px}
}
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Agent 运营统计 · Hermes</title>
<meta name="description" content="Hermes Agent 运营统计：token 用量趋势、cron 定时任务健康度、工具调用排行。数据来自本机会话库，每次部署自动更新。">
<meta name="robots" content="noindex">
<link rel="preload" href="fonts/kami-400.woff2" as="font" type="font/woff2" crossorigin>
<style>{kami_css}
{css}</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="eyebrow">Hermes Operations</div>
  <h1>Agent 运营统计</h1>
  <p class="sub">token 消耗、定时任务健康度与工具调用的真实记录。统计窗口 {span_txt}，生成于 {today}。</p>
  <p class="statusline"><span><b>{fmt_m(tot_calls)}</b> 次 API 调用</span><span><b>{fmt_m(tot_in + tot_out)}</b> tokens 输入+输出</span><span><b>{fmt_m(tot_cache)}</b> tokens 缓存读</span><span><b>{len(crons)}</b> 个 cron 任务</span></p>
  <a class="back" href="index.html">← 返回报告首页</a>　<a class="back" href="skills.html">Skills 一览 →</a>
</header>
<main>
<h2>Token 用量 · 按模型</h2>
<div class="tbl-wrap"><table>
<thead><tr><th>模型</th><th class="num">API 调用</th><th class="num">输入 tokens</th><th class="num">输出 tokens</th><th class="num">缓存读</th></tr></thead>
<tbody>{model_rows}</tbody></table></div>

<h2>Token 用量 · 近 30 天 <span class="totip">（柱高 = 当日输入+输出；悬停看明细）</span></h2>
<div class="chart">{bars_html}</div>
<p class="chartnote">缓存读未计入柱高：上下文复用为主，与计费输入不同列。峰值日 {fmt_k(peak)} tokens。</p>

<h2>Cron 定时任务健康度</h2>
<div class="tbl-wrap"><table>
<thead><tr><th>任务</th><th class="num">执行</th><th class="num">成功率</th><th class="num">失败</th><th class="num">均耗时</th><th class="num">最近一次</th></tr></thead>
<tbody>{cron_html}</tbody></table></div>
{inc_html}

<h2>工具调用排行</h2>
<ul class="toolList">{tool_rows}</ul>
</main>
<footer class="foot-note">数据源：本机会话库与 cron 执行库（只读聚合）· 错误文本已脱敏<br>Hermes Agent · kami design</footer>
</div>
</body>
</html>"""

    OUT.write_text(html)
    worst = min(crons, key=lambda x: x["rate"], default=None)
    tip = f"（最低成功率：{worst['name']} {worst['rate']}%）" if worst else ""
    print(f"OK: stats.html -> {len(models)} 模型 / {len(daily)} 天 / {len(crons)} cron 任务 / "
          f"{len(tools)} 工具 {tip}")


if __name__ == "__main__":
    main()
