#!/usr/bin/env python3
"""生成 docs/skills.html —— Skill 清单 + 使用频率页。

数据源:
  ~/.hermes/skills/**/SKILL.md   -> 清单 (name/description/分类)
  ~/.hermes/state.db (messages)  -> skill_view / skill_manage 权威调用统计
                                     (次数/天数/会话数/最近使用)

隐私: 仅输出 name + 脱敏后的 description + 统计数字, 不含 SKILL.md 正文。
      金额/绝对路径/真实姓名/邮箱在渲染前替换。
样式: 复用 build_site.py 的 KAMI_CSS token (kami 设计语言), 卡片网格而非
      逐行 hairline 长列表; 触控区 >= 44px; 单强调色。
"""
import datetime
import importlib.util
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = Path.home() / ".hermes" / "skills"
STATE_DB = Path.home() / ".hermes" / "state.db"
OUT = ROOT / "docs" / "skills.html"

MAX_DESC = 140


def load_kami_css():
    """复用 build_site.py 的字体与 token, 保证与站点逐字节同源。"""
    spec = importlib.util.spec_from_file_location("bs", ROOT / "build_site.py")
    assert spec and spec.loader
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)
    return bs.KAMI_CSS.replace("__FONTS__", "fonts/")


# ── 数据: 清单 ──
def sanitize_desc(d: str) -> str:
    d = re.sub(r"[¥￥$]\s*\d[\d,.\s]*(万|亿|w|k|K|/hr)?", "【金额已脱敏】", d)
    d = re.sub(r"/Users/[^\s，。;；'\")]+", "[本地路径]", d)
    d = d.replace("文辉", "用户").replace("David-qiuwenhui", "用户")
    d = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[邮箱]", d)
    d = d.replace("\u2014", "-").replace("\u2013", "-")  # em/en-dash 禁用
    d = re.sub(r"\s+", " ", d).strip().strip("'\"")
    return d[:MAX_DESC] + ("…" if len(d) > MAX_DESC else "")


def load_skills():
    out = []
    for p in sorted(SKILLS_DIR.rglob("SKILL.md")):
        rel = p.relative_to(SKILLS_DIR)
        parts = rel.parts
        category = parts[0] if len(parts) > 1 else "general"
        head = p.read_text(errors="ignore")[:4000]
        m = re.search(r"^name:\s*(.+)$", head, re.M)
        name = m.group(1).strip().strip("'\"") if m else (
            parts[-2] if len(parts) > 1 else "unnamed")
        dm = re.search(r"^description:\s*[>\-]?\s*(.+)$", head, re.M)
        desc = sanitize_desc(dm.group(1)) if dm else ""
        out.append({"name": name, "desc": desc, "category": category})
    return out


# ── 数据: 使用统计 (state.db 只读) ──
def load_usage():
    usage = {}
    if not STATE_DB.exists():
        return usage, None
    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT session_id, tool_calls, timestamp FROM messages "
            "WHERE tool_calls IS NOT NULL AND tool_calls != '[]'")
        for sid, tc, ts in rows:
            try:
                calls = json.loads(tc)
            except Exception:
                continue
            day = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            for c in calls:
                fn = c.get("function") or {}
                tool = fn.get("name", "")
                if tool not in ("skill_view", "skill_manage"):
                    continue
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                target = args.get("name")
                if not target and tool == "skill_manage":
                    for op in args.get("operations") or []:
                        if isinstance(op, dict) and op.get("name"):
                            target = op["name"]
                            break
                if not target:
                    continue
                d = usage.setdefault(
                    target, {"view": 0, "manage": 0, "days": set(),
                             "sessions": set(), "last": 0.0})
                d["view" if tool == "skill_view" else "manage"] += 1
                d["days"].add(day)
                d["sessions"].add(sid)
                d["last"] = max(d["last"], ts)
        win = con.execute("SELECT MIN(timestamp), MAX(timestamp) FROM messages").fetchone()
    finally:
        con.close()
    span = None
    if win and win[0]:
        f = lambda t: datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        span = (f(win[0]), f(win[1]))
    return usage, span


def main():
    skills = load_skills()
    usage, span = load_usage()
    by_name = {s["name"]: s for s in skills}

    matched = 0
    for target, u in usage.items():
        key = target if target in by_name else target.split("/")[0]
        if key in by_name:
            matched += 1
            s = by_name[key]
            s.update(view=u["view"], manage=u["manage"],
                     days=len(u["days"]), sessions=len(u["sessions"]),
                     last=datetime.datetime.fromtimestamp(u["last"]).strftime("%m-%d"))
    for s in skills:
        s.setdefault("view", 0)
        s.setdefault("manage", 0)
        s.setdefault("days", 0)
        s.setdefault("sessions", 0)
        s.setdefault("last", None)
        s["total"] = s["view"] + s["manage"]

    def tier(s):
        return "hot" if s["total"] >= 3 else ("warm" if s["total"] else "cold")

    used = [s for s in skills if s["total"]]
    unused = [s for s in skills if not s["total"]]
    used.sort(key=lambda s: (-s["total"], s["name"]))
    unused.sort(key=lambda s: (s["category"], s["name"]))
    ordered = used + unused

    cats = sorted({s["category"] for s in skills})
    n_hot = sum(1 for s in skills if tier(s) == "hot")
    n_warm = sum(1 for s in skills if tier(s) == "warm")
    span_txt = f"{span[0]} 起" if span else "无数据"

    TIER_LABEL = {"hot": "常用", "warm": "用过", "cold": "未使用"}

    cards = []
    for s in ordered:
        t = tier(s)
        if s["total"]:
            stats = (f'<span class="sk-usage"><b>{s["total"]}</b> 次 · {s["days"]} 天</span>'
                     f'<span class="sk-last">最近 {s["last"]}</span>')
        else:
            stats = '<span class="sk-usage sk-zero">尚无调用记录</span>'
        desc = f'<p class="sk-desc">{s["desc"] or "（无描述）"}</p>'
        cards.append(
            f'<div class="skcard" data-tier="{t}" data-cat="{s["category"]}">'
            f'<div class="sk-head"><h3 class="sk-name">{s["name"]}</h3>'
            f'<span class="sk-tag t-{t}">{TIER_LABEL[t]}</span></div>'
            f'{desc}'
            f'<div class="sk-meta"><span class="sk-cat">{s["category"]}</span>{stats}</div>'
            f"</div>")
    n = len(ordered)

    kami_css = load_kami_css()
    page_css = """
.wrap{max-width:1080px;margin:0 auto;padding:56px 24px 72px}
header{margin-bottom:30px}
.eyebrow{font-size:12.5px;letter-spacing:.18em;color:var(--stone);text-transform:uppercase;margin-bottom:14px}
h1{font-family:"TsangerJinKai02",serif;font-size:34px;font-weight:500;color:var(--near-black);margin:0 0 12px}
.sub{font-size:14.5px;color:var(--olive);line-height:1.75;max-width:62ch;margin:0 0 16px}
.statusline{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--stone);font-variant-numeric:tabular-nums;margin-bottom:22px}
.statusline b{color:var(--brand);font-weight:500}
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:26px}
.chipf{border:1px solid var(--border);background:var(--ivory);color:var(--olive);font-family:inherit;font-size:13px;padding:7px 14px;border-radius:3px;cursor:pointer;transition:background .18s,color .18s,border-color .18s;display:inline-flex;align-items:center;min-height:44px}
.chipf[aria-pressed="true"]{background:var(--brand);border-color:var(--brand);color:#fbfaf6}
.chipf:focus-visible{outline:2px solid var(--brand-ink-light);outline-offset:2px}
.self{border:1px solid var(--border);background:var(--ivory);color:var(--olive);font-family:inherit;font-size:13.5px;min-height:44px;padding:6px 10px;border-radius:3px;cursor:pointer}
.self:focus-visible{outline:2px solid var(--brand-ink-light);outline-offset:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.skcard{display:flex;flex-direction:column;gap:9px;background:var(--ivory);border:1px solid var(--border);border-radius:6px;padding:17px 19px;box-shadow:var(--shadow)}
.sk-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.sk-name{font-family:"TsangerJinKai02",serif;font-size:15.5px;font-weight:500;color:var(--near-black);margin:0;line-height:1.4;overflow-wrap:anywhere}
.sk-tag{flex:none;font-size:11.5px;letter-spacing:.06em;padding:3px 8px;border-radius:3px;margin-top:2px}
.t-hot{background:var(--tag-bg);color:var(--brand);font-weight:500}
.t-warm{border:1px solid var(--border);color:var(--olive)}
.t-cold{color:var(--stone)}
.sk-desc{font-size:13.5px;color:var(--olive);line-height:1.65;margin:0;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow-wrap:anywhere;text-wrap:pretty}
.sk-meta{margin-top:auto;display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;color:var(--stone);font-variant-numeric:tabular-nums}
.sk-cat{background:var(--parchment);border:1px solid var(--border-soft);padding:1px 7px;border-radius:3px}
.sk-usage b{color:var(--brand);font-weight:500}
.sk-zero{font-style:normal}
.more{margin:38px auto 0;display:flex;align-items:center;justify-content:center;min-height:44px;border:1px solid var(--border);background:var(--ivory);color:var(--brand);font-family:inherit;font-size:13.5px;padding:11px 22px;border-radius:3px;cursor:pointer;transition:border-color .18s,background .18s}
.more:hover{border-color:var(--brand);background:var(--tag-bg)}
.foot-note{margin-top:46px;font-size:12px;color:var(--stone);line-height:1.8;text-align:center}
.empty{display:none;font-size:14px;color:var(--stone);padding:40px 0;text-align:center}
.totop{position:fixed;right:18px;bottom:calc(18px + env(safe-area-inset-bottom));width:44px;height:44px;border-radius:50%;background:var(--ivory);border:1px solid var(--border);color:var(--brand);font-size:17px;line-height:1;display:flex;align-items:center;justify-content:center;box-shadow:var(--shadow);opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;z-index:20}
.totop.on{opacity:1;pointer-events:auto}
[data-hidden="1"]{display:none!important}
@media(max-width:640px){
.wrap{padding:calc(40px + env(safe-area-inset-top)) 20px calc(56px + env(safe-area-inset-bottom))}
h1{font-size:30px}
.grid{grid-template-columns:1fr;gap:12px}
}
"""

    cat_opts = "\n".join(f'<option value="{c}">{c}</option>' for c in cats)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Skills 一览 · Hermes Agent</title>
<meta name="description" content="Hermes Agent 已安装 Skill 清单与使用频率（调用次数、活跃天数、最近使用），每交易日自动更新。">
<meta name="robots" content="noindex">
<link rel="preload" href="fonts/kami-400.woff2" as="font" type="font/woff2" crossorigin>
<style>{kami_css}
{page_css}</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="eyebrow">Hermes Skill Inventory</div>
  <h1>Skills 一览</h1>
  <p class="sub">已安装 Skill 的清单与真实调用频率。数据来自 Hermes 会话的权威工具调用记录，按次数降序；未出现的即为尚未启用。</p>
  <p class="statusline"><span><b>{n}</b> 个已安装</span><span><b>{n_hot}</b> 个常用（≥3 次）</span><span><b>{n_warm}</b> 个低频</span><span><b>{n - n_hot - n_warm}</b> 个未使用</span><span>统计窗口 {span_txt}</span></p>
  <a class="back" href="index.html" style="font-size:14px;color:var(--brand-ink-light);padding:11px 2px;display:inline-block">← 返回报告首页</a>
</header>
<main>
<div class="controls" role="group" aria-label="按使用频率筛选">
  <button class="chipf" type="button" data-tier="all" aria-pressed="true">全部 {n}</button>
  <button class="chipf" type="button" data-tier="hot" aria-pressed="false">常用 {n_hot}</button>
  <button class="chipf" type="button" data-tier="warm" aria-pressed="false">低频 {n_warm}</button>
  <button class="chipf" type="button" data-tier="cold" aria-pressed="false">未使用 {n - n_hot - n_warm}</button>
  <label class="self"><select class="catsel" aria-label="按分类筛选"><option value="all">全部分类</option>{cat_opts}</select></label>
</div>
<div class="grid">
{chr(10).join(cards)}
</div>
<p class="empty">该筛选组合下没有 Skill。</p>
<button class="more" type="button" hidden>显示全部</button>
</main>
<footer class="foot-note">仅展示名称、描述与统计数字，Skill 正文不入公开库 · 描述已脱敏<br>Hermes Agent · kami design</footer>
</div>
<a class="totop" href="#" aria-label="回到顶部">↑</a>
<script>
(function(){{
  var cards=[].slice.call(document.querySelectorAll('.skcard'));
  var chips=[].slice.call(document.querySelectorAll('.chipf'));
  var sel=document.querySelector('.catsel');
  var more=document.querySelector('.more');
  var empty=document.querySelector('.empty');
  var SHOWN=60, tier='all', cat='all';
  function apply(){{
    var vis=0;
    cards.forEach(function(c){{
      var ok=(tier==='all'||c.dataset.tier===tier)&&(cat==='all'||c.dataset.cat===cat);
      if(!ok){{c.setAttribute('data-hidden','1');return;}}
      vis++;
      c.setAttribute('data-hidden',vis>SHOWN?'1':'0');
    }});
    more.hidden=vis<=SHOWN;
    empty.style.display=vis?'none':'block';
  }}
  more.addEventListener('click',function(){{SHOWN=1e9;apply();}});
  chips.forEach(function(b){{
    b.addEventListener('click',function(){{
      chips.forEach(function(x){{x.setAttribute('aria-pressed','false');}});
      b.setAttribute('aria-pressed','true');
      tier=b.dataset.tier;SHOWN=60;apply();
    }});
  }});
  sel.addEventListener('change',function(){{cat=sel.value;SHOWN=60;apply();}});
  var tt=document.querySelector('.totop');
  addEventListener('scroll',function(){{tt.classList.toggle('on',scrollY>600);}},true);
  apply();
}})();
</script>
</body>
</html>"""

    OUT.write_text(html)
    print(f"OK: skills.html -> {n} skills ({n_hot} hot / {n_warm} warm / "
          f"{n - n_hot - n_warm} unused), usage matched {matched} targets")


if __name__ == "__main__":
    main()
