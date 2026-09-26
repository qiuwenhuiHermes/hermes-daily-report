#!/usr/bin/env python3
"""站点成品结构体检（对 docs/reports/*.html 逐页扫描）

用法:  python3 tools/check_tables.py [目录]        # 默认 docs/reports

检查四类问题，任一非零即退出码 1（可接进 CI / 部署前闸门）:
  1. 列数不一致     某数据行 <td> 数 != 表头 <th> 数（表格解析破裂 / 行被粘合）
  2. 无数据行空表   只有表头没有数据行的表
  3. 分隔行/表头残留  Markdown 源码被原样当段落输出（"---|---" / "代码 | 状态 | 一句话"）
  4. 续行退化       紧跟表格、且竖线分列数等于该表列数的段落（合法的表格行掉出表格）

注意: 统计表头必须用 r'<th[ >]' 或 r'<th[^>]*>(.*?)</th>'——直接用 r'<th[^>]*>'
会把 <thead> 当成一个表头（多算一列），不巧时又因吞掉一个真表头而互相抵消，
得到"看起来正确"的列数，掩盖真实错位。
"""
import glob
import os
import re
import sys

DIR = sys.argv[1] if len(sys.argv) > 1 else 'docs/reports'
TH = re.compile(r'<th[ >]')          # <thead> 不算表头
TBL = re.compile(r'<table class="kami-tb.*?</table>', re.S)
TR = re.compile(r'<tr>(.*?)</tr>', re.S)

files = sorted(glob.glob(os.path.join(DIR, '*.html')))
total_tbl = total_rows = 0
bad, empty, unrendered, orphan = [], [], [], []

for f in files:
    h = open(f).read()
    name = os.path.basename(f)

    for bi, block in enumerate(TBL.findall(h)):
        total_tbl += 1
        ncol = len(TH.findall(block))
        rows = [r for r in TR.findall(block) if '<td' in r]
        if not rows:
            empty.append((name, bi, ncol))
            continue
        for ri, r in enumerate(rows):
            total_rows += 1
            n = len(re.findall(r'<td', r))
            if n != ncol:
                bad.append((name, bi, ri, ncol, n))

    # 表格 / 段落按文档顺序扫描：紧跟表格、竖线分列数与表格列数相同的段落 = 疑似表格续行
    last_ncol = None
    for m in re.finditer(r'<table class="kami-tb.*?</table>|<p[^>]*>.*?</p>', h, re.S):
        frag = m.group(0)
        if frag.startswith('<table'):
            last_ncol = len(TH.findall(frag))
            continue
        t = re.sub(r'<[^>]+>', '', frag).strip()
        # 要求 ≥2 个竖线（≥3 列）——2 列的散文如 "总弹药：5-10万RMB | 目标：2026年内建仓完成"
        # 列数恰好等于相邻表格列数，会被误报
        if last_ncol and t.count('|') >= 2 and len(re.split(r'\s*\|\s*', t)) == last_ncol:
            orphan.append((name, last_ncol, t[:70]))
        last_ncol = None

    # 段落里的 Markdown 表格源码残留
    ps = [re.sub(r'<[^>]+>', '', p).strip() for p in re.findall(r'<p[^>]*>(.*?)</p>', h, re.S)]
    for i, t in enumerate(ps):
        if re.search(r'-{2,}\|', t) and t.count('|') >= 2:
            unrendered.append((name, 'SEP-P: ' + t[:60]))
        elif t.count('|') >= 2 and i + 1 < len(ps) and re.search(r'-{2,}\|', ps[i + 1]):
            unrendered.append((name, 'HDR-P: ' + t[:60]))

print(f'报告 {len(files)} 份 | 表格 {total_tbl} 张 | 数据行 {total_rows} 行')
print('1 列数不一致        ', len(bad), bad[:4])
print('2 无数据行空表      ', len(empty), empty[:4])
print('3 分隔行/表头残留   ', len(unrendered), unrendered[:4])
print('4 疑似续行退化为段落', len(orphan))
for o in orphan[:10]:
    print('   ', o)

sys.exit(1 if (bad or empty or unrendered or orphan) else 0)
