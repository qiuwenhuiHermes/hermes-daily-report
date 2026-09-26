#!/usr/bin/env python3
"""源文 ↔ 渲染结果 逐表比对 + 静态缺陷扫描（独立第二意见）

用法:  python3 tools/verify_report.py [--repo-dir .]

为什么需要它: check_tables.py 只检查渲染结果"自身自洽"（列数与表头一致、
行数不为 0）。但曾经出现过**表头被降级成段落、首行数据被当成表头**的情况——
每张表列数都自洽、行数都对，数字全绿，实际列名整表错位。只有把源文里
"本该是表头的那一行"和渲染出的 <th> 逐字比，才能发现。

本工具用**独立实现**（不复用 build_site 的解析函数）从源文重建表格清单，
再和渲染结果比；另扫五类静态缺陷。有问题退出码 1。
"""
import argparse
import glob
import html as _html
import importlib.util
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# ─────────── 独立实现：源文侧表格识别 ───────────
BAD_PREFIX = ("- ", "* ", "> ", "#", "1. ", "2. ", "3. ")
PROSE_LABEL = re.compile(r'^\*{0,2}[^|*：:]{1,12}[：:]')
PIPE_IN_PAREN = re.compile(r'（[^（）]{0,24}\|[^（）]{0,24}）')
SEP_CELL = re.compile(r'^:?-{2,}:?$')


def cells_of(line):
    """把一个源文候选行切成单元格；不含竖线返回 None"""
    s = line.strip()
    if "|" not in s:
        return None
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells = [c.strip() for c in s.split("|")]
    return cells if len(cells) >= 2 else None


def vetoed(line):
    s = line.strip()
    return (s.startswith(BAD_PREFIX) or PROSE_LABEL.match(s)
            or s.endswith(("。", "！", "？")) or bool(PIPE_IN_PAREN.search(s)))


def src_tables(body):
    """独立重建源文表格: 连续 ≥2 行、列数相同、未被散文否决 → 一块表"""
    lines = body.splitlines()
    cand = []
    for ln in lines:
        c = cells_of(ln)
        cand.append(None if (c is None or vetoed(ln)) else c)
    out, i, n = [], 0, len(lines)
    while i < n:
        if not cand[i]:
            i += 1
            continue
        ncol, j = len(cand[i]), i
        while j < n and cand[j] and (len(cand[j]) == ncol
                                     or all(SEP_CELL.match(x or "") for x in cand[j])):
            j += 1
        if j - i >= 2:
            block = [(lines[k], cand[k]) for k in range(i, j)]
            real = [(ln, c) for ln, c in block
                    if not all(SEP_CELL.match(x or "") for x in c)]
            if len(real) >= 2:
                out.append([[_norm(c) for c in cs] for _, cs in real])
            i = j
        else:
            i += 1
    return out


BTAG = re.compile(r"<[^>]+>")


def _norm(s):
    """归一化: 去标签 / 去 markdown 标记 / 去所有空白"""
    s = BTAG.sub("", s)
    s = _html.unescape(s)
    s = re.sub(r"[*`_~]", "", s)
    return re.sub(r"\s+", "", s).strip()


def ren_tables(page_html):
    """渲染侧: [(表头列表, [数据行列表]), ...]"""
    out = []
    for tb in re.findall(r'<table class="kami-tb.*?</table>', page_html, re.S):
        ths = re.findall(r'<th[ >][^>]*>(.*?)</th>', tb, re.S)
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S):
            if "<td" not in tr:
                continue
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            rows.append([_norm(c) for c in tds])
        out.append(([_norm(c) for c in ths], rows))
    return out


# ─────────── 配对与比对 ───────────
def load_builder(repo):
    spec = importlib.util.spec_from_file_location(
        "bs", os.path.join(repo, "build_site.py"))
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)
    return bs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=REPO)
    args = ap.parse_args()
    repo = os.path.abspath(args.repo_dir)
    bs = load_builder(repo)
    docs = os.path.join(repo, "docs", "reports")
    out = os.path.join(repo, "docs", "index.html")

    # 复现 main() 的源文件选择 → (日期, 栏目, body)
    reports = []
    for key, meta in bs.SOURCES.items():
        d = os.path.join(bs.CRON_OUT, meta["dir"])
        for f in sorted(glob.glob(os.path.join(d, "*.md")), reverse=True):
            r = bs.parse_report(f, meta)
            if r:
                r["type_key"] = key
                reports.append(r)
    seen, final = set(), []
    for r in reports:
        k = (r["date"], r["type_key"])
        if k not in seen:
            seen.add(k)
            final.append(r)

    problems = []
    for r in final:
        page = os.path.join(docs, f"{r['date']}-{r['type_key']}.html")
        if not os.path.exists(page):
            problems.append(("缺失页面", os.path.basename(page), ""))
            continue
        h = open(page, encoding="utf-8").read()

        # ① 源文 ↔ 渲染 逐表比对
        st, rt = src_tables(r["body"]), ren_tables(h)
        if len(st) != len(rt):
            problems.append(("表数不符", page, f"源文 {len(st)} / 渲染 {len(rt)}"))
        for i, (s_tb, r_tb) in enumerate(zip(st, rt)):
            r_head, r_rows = r_tb
            s_head = s_tb[0]
            if s_head != r_head:
                problems.append(("表头不符", page,
                                 f"第{i+1}表 源文={s_head} 渲染={r_head}"))
            if len(s_tb) - 1 != len(r_rows):
                problems.append(("行数不符", page,
                                 f"第{i+1}表 {s_head} 源文{len(s_tb)-1}行/渲染{len(r_rows)}行"))

        # ② 表头残留 markdown（错位表头信号）
        for th in re.findall(r'<th[ >][^>]*>(.*?)</th>', h, re.S):
            t = BTAG.sub("", th).strip()
            if t.startswith(("**", "|")) or "---" in t:
                problems.append(("表头残留标记", page, t[:40]))

        # ③ 段落里残留表格分隔行（表格被当文字渲染）
        for p in re.findall(r"<p[^>]*>(.*?)</p>", h, re.S):
            t = BTAG.sub("", p)
            if re.search(r"-{3,}\s*\|", t) or re.search(r"\|\s*-{3,}", t):
                problems.append(("段落含分隔行", page, t[:60]))

        # ④ 隐私: 未脱敏金额
        for m in re.finditer(r"[¥￥]\s*[\d,]+|\d[\d,]*\s*万(?=[元块，。;\s]|$)", BTAG.sub(" ", h)):
            problems.append(("金额未脱敏", page, m.group(0)[:20]))

        # ⑤ 必备 meta
        for need in ('name="viewport"', "og:title", "<title>"):
            if need not in h:
                problems.append(("缺 " + need, page, ""))

        # ⑥ 页内导航死链
        for href in re.findall(r'href="[^"]*?(reports/[\w.-]+\.html)"', h):
            if not os.path.exists(os.path.join(repo, "docs", href)):
                problems.append(("导航死链", page, href))

    if os.path.exists(out):
        idx = open(out, encoding="utf-8").read()
        for need in ('name="viewport"', "og:title"):
            if need not in idx:
                problems.append(("首页缺 " + need, "index.html", ""))
        for href in re.findall(r'href="[^"]*?(reports/[\w.-]+\.html)"', idx):
            if not os.path.exists(os.path.join(repo, "docs", href)):
                problems.append(("首页死链", "index.html", href))

    print(f"比对 {len(final)} 页（源文 ↔ 渲染 逐表）")
    if not problems:
        print("① 表头/行数/表数一致  ② 无表头残留标记  ③ 无段落分隔行\n"
              "④ 无金额泄漏  ⑤ meta 完整  ⑥ 无死链  → 全部通过")
        return 0
    from collections import Counter
    print(f"发现 {len(problems)} 处问题:")
    for (kind, page, detail) in problems[:40]:
        print(f"  [{kind}] {os.path.basename(page)} {detail}")
    if len(problems) > 40:
        print(f"  ... 另有 {len(problems)-40} 处")
    print(" 分类:", dict(Counter(k for k, _, _ in problems)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
