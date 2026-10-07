#!/usr/bin/env python3
"""生成 docs/slash-commands.html —— Hermes 斜杠命令参考页。

数据源：~/.hermes/hermes-agent 的 hermes_cli/commands.py::COMMAND_REGISTRY（唯一权威源）。
  导入成功 → 写入 tools/slash_commands.json 缓存并渲染；
  导入失败 → 回退读缓存（站点构建不因上游源码变动而挂掉）。

中文说明：注册表里的 description 是英文，逐条配中文一句话便于阅读；
  未配置的一律回退显示英文原文，不臆造。

隐私：本页不含金额、路径、姓名；meta robots noindex。
"""
import datetime
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERMES_AGENT = Path.home() / ".hermes" / "hermes-agent"
CACHE = ROOT / "tools" / "slash_commands.json"
OUT = ROOT / "docs" / "slash-commands.html"

CAT_ZH = {
    "Session": "会话与会话控制",
    "Configuration": "配置与开关",
    "Tools & Skills": "能力与扩展",
    "Info": "信息与运维",
    "Exit": "退出",
}
CAT_ORDER = ["Session", "Configuration", "Tools & Skills", "Info", "Exit"]

# 逐条中文说明。以命令名（不含 /）为键。
ZH = {
    # —— 会话 ——
    "start": "确认平台启动 ping（不回话）",
    "new": "开一个新会话（全新会话 ID 与历史）",
    "topic": "启用或查看 Telegram 私聊话题会话",
    "clear": "清屏并开一个新会话",
    "redraw": "强制重绘界面（终端显示漂移时恢复）",
    "history": "显示对话历史",
    "save": "导出当前对话",
    "retry": "重发上一条消息",
    "prompt": "在编辑器里写 markdown 形式的下一条提问",
    "undo": "回退 N 轮用户发言并重新提问（默认 1）",
    "title": "给当前会话命名",
    "handoff": "把本会话移交给某个消息平台",
    "branch": "从当前会话分叉出新线程",
    "worktree": "查看、创建或清理隔离的 git worktree",
    "compress": "压缩对话上下文（可控成本）",
    "rollback": "列出或恢复文件系统检查点",
    "snapshot": "创建或恢复 Hermes 配置/状态快照",
    "stop": "杀掉所有正在跑的后台进程",
    "pause": "全局暂停新工作（紧急刹车），/pause off 恢复",
    "approve": "批准一条待审的危险命令",
    "deny": "拒绝一条待审的危险命令（可附理由）",
    "bg": "在独立的后台会话里跑一个 prompt",
    "btw": "对当前对话提个侧问，不打断主线",
    "agents": "查看活跃 agent 与运行中的任务",
    "journey": "打开学习轨迹时间线",
    "queue": "把提问排到下一轮，或列出/编辑/删除队列",
    "steer": "在下次工具调用之后注入消息，不打断当前回合",
    "goal": "设定一个跨回合持续推进、直到达成的长期目标",
    "heartbeat": "设一个空闲时自动重入本会话的循环 prompt",
    "refine": "立即复盘本对话，把教训存进记忆与技能",
    "review": "起一个独立 subagent 评审刚讨论的工作",
    "loop": "在本会话里按固定间隔重复跑一个 prompt",
    "plan": "写一份 markdown 实施计划到 .hermes/plans/，不执行",
    "moa": "用默认 Mixture of Agents 预设跑一次，然后恢复原模型",
    "subgoal": "给进行中的目标追加判据",
    "status": "查看会话、模型、token 与上下文信息",
    "egress": "查看 Docker 出口代理状态",
    "context": "查看上下文窗口明细（占用、分类、压缩、吞吐）",
    "sethome": "把当前聊天设为 home 频道",
    "resume": "恢复一个此前命名过的会话",
    "sessions": "浏览并恢复历史会话",
    # —— 信息 ——
    "whoami": "查看你的斜杠命令权限（管理员 / 普通）",
    "profile": "查看当前 profile 名称与主目录",
    "commands": "分页浏览全部命令与技能",
    "palette": "打开模糊命令面板（也可按 Ctrl+P）",
    "help": "显示可用命令（/help skills 列技能、/help <词> 过滤）",
    "restart": "优雅重启网关（先排空在跑的回合）",
    "usage": "查看 token 用量与限额",
    "subscription": "查看 Nous 套餐并在浏览器里变更",
    "login": "用 Nous 账号登录（保留已连接的 connector）",
    "topup": "查看 Nous 余额并在门户管理账单",
    "insights": "查看使用洞察与分析",
    "platforms": "查看网关/消息平台状态",
    "platform": "暂停、恢复或列出故障中的平台",
    "copy": "把上一条助手回复复制到剪贴板",
    "paste": "附上剪贴板里的图片",
    "image": "附上一个本地图片文件（给下一条提问）",
    "update": "把 Hermes Agent 升级到最新版",
    "version": "查看 Hermes Agent 版本",
    "debug": "上传诊断报告（系统信息 + 日志）并取分享链接",
    "diff": "显示工作目录里的 git 变更",
    # —— 配置 ——
    "export": "把 profile（配置、技能、主题）导出成可分享压缩包",
    "import": "把分享的 profile 压缩包导入为新 profile",
    "config": "显示当前配置",
    "model": "切换模型（会话级；--global 才持久化）",
    "codex-runtime": "切换 OpenAI/Codex 模型的 codex app-server 运行时",
    "personality": "设置一个预设人设",
    "statusbar": "开关上下文/模型状态栏",
    "battery": "开关状态栏上的电量指示",
    "timestamps": "开关消息时间戳",
    "verbose": "循环切换工具进度显示档位（off→new→all→verbose）",
    "focus": "切换聚焦视图，只看你的提问与最终答复",
    "footer": "开关最终回复下方的运行元数据页脚",
    "yolo": "开关 YOLO 模式（跳过所有危险命令审批）",
    "approvals": "查看或设置危险命令的持久审批模式",
    "reasoning": "管理推理强度与展示",
    "fast": "快速模式：OpenAI 优先处理 / Anthropic Fast（normal/fast/auto/cold）",
    "skin": "查看或更换界面皮肤主题",
    "indicator": "挑选 TUI 的忙碌指示器样式",
    "voice": "开关语音模式",
    "wake": "开关「Hey Hermes」唤醒词监听",
    "busy": "控制 Hermes 工作时新消息的行为",
    # —— 能力 ——
    "tools": "管理工具：/tools [list|disable|enable] [名称…]",
    "toolsets": "列出可用的工具集",
    "skills": "搜索、安装、查看或管理技能",
    "memory": "审阅待写入的记忆 / 切换记忆审批闸",
    "bundles": "列出技能包（用一个别名带起多个技能）",
    "pet": "开关或领养 petdex 吉祥物",
    "hatch": "用一段描述生成一个新的 petdex 宠物",
    "learn": "从任何东西（目录、URL、本对话、笔记）学成一个可复用技能",
    "init": "扫描仓库，生成或更新 AGENTS.md 项目说明",
    "cron": "管理定时任务",
    "suggestions": "审阅建议的自动化（接受 / 忽略）",
    "blueprint": "用蓝图模板搭起一个自动化",
    "curator": "后台技能维护（状态、运行、固定、归档）",
    "kanban": "多 profile 协作看板（任务、关联、评论）",
    "reload": "把 .env 变量重新载入正在跑的会话",
    "reload-mcp": "按配置重新加载 MCP server",
    "reload-skills": "重新扫描技能目录，识别新装或已删的技能",
    "browser": "通过 CDP 连上你本机的 Chromium 系浏览器",
    "plugins": "列出已安装插件及其状态",
    # —— 退出 ——
    "quit": "退出 CLI（--delete 会一并删除会话历史）",
}

SCOPE_ZH = {"both": "通用", "cli": "仅命令行", "gw": "仅消息平台"}


def load_kami_css() -> str:
    spec = importlib.util.spec_from_file_location("bs", ROOT / "build_site.py")
    assert spec and spec.loader
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)
    return bs.KAMI_CSS.replace("__FONTS__", "fonts/")


def _venv_python():
    """hermes-agent 自己的 venv 解释器——只有它装了 ruamel 等依赖，能 import 注册表。"""
    for p in (HERMES_AGENT / "venv" / "bin" / "python3",
              HERMES_AGENT / ".venv" / "bin" / "python3"):
        if p.exists():
            return p
    return None


# 在 venv 解释器里读注册表；用子进程是为了让本脚本在任何解释器下都能被调用
# （部署脚本用的是系统 python3，没有 ruamel）。
_SNIPPET = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from hermes_cli.commands import COMMAND_REGISTRY
out = []
for c in COMMAND_REGISTRY:
    out.append({
        "category": str(c.category),
        "name": str(c.name),
        "desc": str(c.description),
        "aliases": [str(a) for a in (getattr(c, "aliases", ()) or ())],
        "cli_only": bool(getattr(c, "cli_only", False)),
        "gw_only": bool(getattr(c, "gateway_only", False)),
        "gate": getattr(c, "gateway_config_gate", None),
    })
print(json.dumps(out, ensure_ascii=False))
'''


def _as_dicts(registry):
    return [{
        "category": str(c.category),
        "name": str(c.name),
        "desc": str(c.description),
        "aliases": [str(a) for a in (getattr(c, "aliases", ()) or ())],
        "cli_only": bool(getattr(c, "cli_only", False)),
        "gw_only": bool(getattr(c, "gateway_only", False)),
        "gate": getattr(c, "gateway_config_gate", None),
    } for c in registry]


def _write_cache(cmds):
    CACHE.write_text(json.dumps(
        {"exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
         "commands": cmds}, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_commands():
    """取命令注册表。三级回退：venv 子进程 → 进程内导入 → 上次缓存。

    注册表来自 hermes_cli/commands.py，是唯一权威源；导入需要 hermes-agent 的
    venv（ruamel 等依赖）。都不行时用缓存，保证站点构建不会因上游变动而挂掉。
    """
    vp = _venv_python()
    if vp:
        try:
            r = subprocess.run([str(vp), "-c", _SNIPPET, str(HERMES_AGENT)],
                               cwd=str(HERMES_AGENT), capture_output=True,
                               text=True, timeout=180)
            if r.returncode == 0 and r.stdout.strip():
                cmds = json.loads(r.stdout)
                _write_cache(cmds)
                return cmds, "注册表实时读取"
        except Exception:
            pass

    try:
        sys.path.insert(0, str(HERMES_AGENT))
        from hermes_cli.commands import COMMAND_REGISTRY  # type: ignore
        cmds = _as_dicts(COMMAND_REGISTRY)
        _write_cache(cmds)
        return cmds, "注册表实时读取"
    except Exception as exc:
        if CACHE.exists():
            data = json.loads(CACHE.read_text(encoding="utf-8"))
            return data["commands"], f"缓存于 {data.get('exported_at', '?')[:16]}（上游读取失败：{type(exc).__name__}）"
        raise RuntimeError(
            "取不到命令注册表，且无缓存。请在 hermes-agent 目录下确认 venv 存在，"
            f"或先跑：{HERMES_AGENT}/venv/bin/python3 -c 'import hermes_cli.commands'"
        ) from exc


def scope_of(c) -> str:
    if c["cli_only"]:
        return "cli"
    if c["gw_only"]:
        return "gw"
    return "both"


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def build():
    cmds, src = fetch_commands()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    n_all = len(cmds)
    n_both = sum(1 for c in cmds if scope_of(c) == "both")
    n_cli = sum(1 for c in cmds if scope_of(c) == "cli")
    n_gw = sum(1 for c in cmds if scope_of(c) == "gw")

    rows = []
    for cat in CAT_ORDER:
        group = [c for c in cmds if c["category"] == cat]
        if not group:
            continue
        # 按范围排序：通用在前，仅消息平台其次，仅命令行最后；同范围内按名称
        order = {"both": 0, "gw": 1, "cli": 2}
        group.sort(key=lambda c: (order[scope_of(c)], c["name"]))
        rows.append(
            f'<h2 class="cat" data-cat="{esc(cat)}">{CAT_ZH.get(cat, esc(cat))}'
            f'<span class="n">{len(group)} 条</span></h2>')
        rows.append('<div class="tbl-wrap"><table><thead><tr>'
                    '<th class="cn">命令</th><th class="cs">可用范围</th>'
                    '<th>说明</th></tr></thead><tbody>')
        for c in group:
            sp = scope_of(c)
            zh = ZH.get(c["name"]) or esc(c["desc"])
            extra = ""
            if c["aliases"]:
                extra += f'<span class="al">别名 ' + "、".join("/" + esc(a) for a in c["aliases"]) + "</span>"
            if c["gate"]:
                extra += f'<span class="al">需先开启 <code>{esc(str(c["gate"]))}</code></span>'
            hay = esc((c["name"] + " " + zh + " " + c["desc"] + " " + " ".join(c["aliases"])).lower())
            rows.append(
                f'<tr data-scope="{sp}" data-hay="{hay}">'
                f'<td class="cn"><code>/{esc(c["name"])}</code></td>'
                f'<td class="cs"><span class="sb {sp}">{SCOPE_ZH[sp]}</span></td>'
                f'<td>{zh}{(" " + extra) if extra else ""}</td></tr>')
        rows.append('</tbody></table></div>')

    css = """
.wrap{max-width:960px}
.top{position:sticky;top:0;z-index:10;background:var(--parchment);padding:12px 0 10px;border-bottom:.5px solid var(--border);margin-bottom:20px}
.top .row{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap}
.back{font-size:14px;color:var(--brand-ink-light);padding:11px 2px;display:inline-block;min-height:44px;white-space:nowrap}
.eyebrow{font-size:12.5px;letter-spacing:.18em;color:var(--stone);text-transform:uppercase;margin-bottom:10px}
h1{font-family:"TsangerJinKai02",serif;font-size:32px;font-weight:500;color:var(--near-black);margin:0 0 12px}
.sub{font-size:14.5px;color:var(--olive);line-height:1.8;max-width:64ch;margin:0 0 14px}
.statusline{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--stone);font-variant-numeric:tabular-nums;margin-bottom:16px}
.statusline b{color:var(--brand);font-weight:500}
.ctl{display:flex;flex-wrap:wrap;gap:8px 10px;align-items:center;margin:0 0 6px}
input[type=search]{flex:1;min-width:190px;min-height:44px;padding:10px 14px;font-size:14.5px;font-family:inherit;
  color:var(--near-black);background:var(--ivory);border:1px solid var(--border);border-radius:6px;-webkit-appearance:none}
input[type=search]:focus{outline:none;border-color:var(--brand-ink-light)}
.chipf{min-height:40px;padding:8px 15px;font-size:13.5px;font-family:inherit;color:var(--olive);cursor:pointer;
  background:transparent;border:1px solid var(--border);border-radius:99px}
.chipf[aria-pressed=true]{background:var(--tag-bg);border-color:#c9d8e8;color:var(--brand)}
.hidden{display:none !important}
h2.cat{font-family:"TsangerJinKai02",serif;font-size:20px;font-weight:500;color:var(--near-black);
  margin:36px 0 12px;padding-top:12px;border-top:1px solid var(--border)}
h2.cat .n{font-family:inherit;font-size:12.5px;color:var(--stone);font-weight:400;margin-left:10px}
.tbl-wrap{overflow-x:auto;border:1px solid var(--border-soft);border-radius:6px;background:var(--ivory)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{font-weight:500;text-align:left;color:var(--olive);border-bottom:1.5px solid var(--brand);
  padding:10px 14px;white-space:nowrap;font-size:12.5px}
td{padding:10px 14px;border-bottom:.5px solid var(--border-soft);color:var(--dark-warm);vertical-align:top;overflow-wrap:anywhere}
tr:last-child td{border-bottom:none}
td.cn{white-space:nowrap;width:1%}
td.cn code{font-size:13px;color:var(--brand);background:none;padding:0}
td.cs{white-space:nowrap;width:1%}
.sb{font-size:11.5px;padding:2px 9px;border-radius:99px;border:1px solid var(--border);color:var(--stone);white-space:nowrap}
.sb.both{color:var(--brand);border-color:#c9d8e8;background:var(--tag-bg)}
.al{display:block;font-size:12px;color:var(--stone);margin-top:3px}
.al code{font-size:11.5px;color:var(--olive)}
.empty{display:none;font-size:14px;color:var(--stone);text-align:center;padding:40px 0}
.note{font-size:13px;color:var(--stone);line-height:1.85;margin-top:30px;padding-top:16px;border-top:.5px solid var(--border)}
.foot-note{margin-top:40px;font-size:12px;color:var(--stone);line-height:1.8;text-align:center}
@media(max-width:640px){
h1{font-size:26px}
td,th{padding:9px 10px;font-size:12.5px}
td.cs .sb{font-size:11px;padding:2px 7px}
.al{font-size:11.5px}
}
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>斜杠命令 · Hermes</title>
<meta name="description" content="Hermes Agent 全部斜杠命令的中文参考：共 {n_all} 条，按会话、配置、能力、信息分组，标注每条在命令行与消息平台上的可用范围。">
<meta name="robots" content="noindex">
<link rel="preload" href="fonts/kami-400.woff2" as="font" type="font/woff2" crossorigin>
<style>{load_kami_css()}
{css}</style>
</head>
<body>
<div class="wrap">
<div class="top"><div class="row">
  <a class="back" href="index.html">← 返回报告首页</a>
  <span><a class="back" href="skills.html">Skills 一览</a>　<a class="back" href="stats.html">Agent 运营统计</a></span>
</div></div>
<header>
  <div class="eyebrow">Hermes Reference</div>
  <h1>斜杠命令</h1>
  <p class="sub">Hermes Agent 内置的全部斜杠命令。<strong>通用</strong>表示命令行与消息平台（Telegram 等）都能用；
  <strong>仅命令行</strong>只在 CLI/TUI 界面里存在，聊天里发出去不会有反应。</p>
  <p class="statusline"><span><b>{n_all}</b> 条命令</span><span>通用 <b>{n_both}</b></span>
  <span>仅消息平台 <b>{n_gw}</b></span><span>仅命令行 <b>{n_cli}</b></span></p>
  <div class="ctl">
    <input type="search" id="q" placeholder="搜索命令名、说明或别名…" aria-label="搜索命令">
    <button class="chipf" type="button" data-scope="all" aria-pressed="true">全部</button>
    <button class="chipf" type="button" data-scope="both" aria-pressed="false">通用</button>
    <button class="chipf" type="button" data-scope="gw" aria-pressed="false">仅消息平台</button>
    <button class="chipf" type="button" data-scope="cli" aria-pressed="false">仅命令行</button>
  </div>
</header>
<main>
{"".join(rows)}
<p class="empty" id="empty">没有匹配的命令。</p>
<p class="note">在 Telegram 里打 <code>/help</code> 看可用命令，<code>/commands</code> 分页浏览全部（含技能）。
命令名后带「需先开启」的，要先打开对应配置项才会出现。<br>
本页由 <code>tools/build_slash_commands.py</code> 从 <code>hermes_cli/commands.py</code> 的注册表自动生成，
数据取自 {stamp}（来源：{src}）。注册表是唯一权威源，命令增删会随每次部署自动反映到本页。</p>
</main>
<footer class="foot-note">Hermes Agent · qiuwenhuiHermes/hermes-daily-report · kami design</footer>
</div>
<script>
(function(){{
  var rows=[].slice.call(document.querySelectorAll('tr[data-scope]'));
  var cats=[].slice.call(document.querySelectorAll('h2.cat'));
  var wraps=[].slice.call(document.querySelectorAll('.tbl-wrap'));
  var q=document.getElementById('q');
  var empty=document.getElementById('empty');
  var scope='all';
  function apply(){{
    var t=(q.value||'').trim().toLowerCase();
    var shown=0;
    rows.forEach(function(r){{
      var okS=(scope==='all'||r.getAttribute('data-scope')===scope);
      var okQ=(!t||r.getAttribute('data-hay').indexOf(t)>=0);
      var ok=okS&&okQ;
      r.classList.toggle('hidden',!ok);
      if(ok) shown++;
    }});
    // 空的表/分类整块收起
    wraps.forEach(function(w){{
      var any=w.querySelector('tr[data-scope]:not(.hidden)');
      w.classList.toggle('hidden',!any);
    }});
    cats.forEach(function(h){{
      var n=h.nextElementSibling;
      h.classList.toggle('hidden', n && n.classList.contains('hidden'));
    }});
    empty.style.display=shown?'none':'block';
  }}
  [].slice.call(document.querySelectorAll('.chipf')).forEach(function(b){{
    b.addEventListener('click',function(){{
      scope=b.getAttribute('data-scope');
      [].slice.call(document.querySelectorAll('.chipf')).forEach(function(x){{
        x.setAttribute('aria-pressed',String(x===b));
      }});
      apply();
    }});
  }});
  q.addEventListener('input',apply);
  apply();
}})();
</script>
</body>
</html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"OK: slash-commands.html -> {n_all} 条（通用 {n_both} / 仅消息平台 {n_gw} / 仅命令行 {n_cli}）"
          f" | 数据源：{src} | {len(html)/1024:.0f}KB")


if __name__ == "__main__":
    build()
