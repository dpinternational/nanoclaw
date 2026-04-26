#!/usr/bin/env python3
"""Full Agent LTV deep analysis - runs on server."""
import json, sqlite3
from collections import defaultdict
from datetime import datetime

d = json.load(open('/home/david/nanoclaw/data/recruiting-full-dump.json'))
intel = sqlite3.connect('/home/david/nanoclaw/store/tpg-intel.db')

production = {}
try:
    for r in intel.execute('SELECT agent_name, team_name, COUNT(DISTINCT month), SUM(production), AVG(production), MAX(production), MIN(month), MAX(month) FROM agent_production GROUP BY agent_name'):
        production[r[0]] = dict(team=r[1], months=r[2], total=r[3], avg=r[4], peak=r[5], first=r[6], last=r[7])
except: pass
print(f'Production records: {len(production)} agents')

master = d['master']
agents = {}
for row in master[1:]:
    if len(row) < 5: continue
    name = str(row[1]).strip() if len(row) > 1 and row[1] else None
    if not name or name in ('', 'None'): continue
    hire_date = str(row[4]).strip() if len(row) > 4 and row[4] else None
    source = str(row[5]).strip() if len(row) > 5 and row[5] else 'Unknown'
    upline = str(row[6]).strip() if len(row) > 6 and row[6] else 'Unknown'
    parsed = None
    if hire_date and '/' in hire_date:
        try:
            parts = hire_date.split('/')
            if len(parts)==3:
                m,dy,yr=parts
                if len(yr)==2: yr='20'+yr
                parsed=f'{yr}-{m.zfill(2)}-{dy.zfill(2)}'
        except: pass
    if name not in agents:
        agents[name] = dict(hire_date=parsed, source=source, upline=upline, production=production.get(name, {}))

print(f'Total agents: {len(agents)}')

source_map = {'Direct':'Direct','Direct Recruit':'Direct','Website':'Website','Organic':'Organic','ZipRecruiter':'ZipRecruiter','Wizehire':'Wizehire','Funnels':'Funnels','ClickFunnels':'Funnels','clickFunnels':'Funnels','Email':'Email','Facebook':'Facebook','Trinity':'Trinity','4x4 Training':'4x4','4x4 training':'4x4','4x4':'4x4'}
now = datetime(2026,4,13)
override_pct = 0.15
avg_lead_rev = 1094

results = []
for name, a in agents.items():
    p = a['production']
    total_ap = p.get('total',0) or 0
    months = p.get('months',0) or 0
    source = source_map.get(a['source'], a['source'])
    override = total_ap * override_pct
    lead_rev = months * avg_lead_rev if months > 0 else 0
    total_rev = override + lead_rev
    results.append(dict(name=name, hire_date=a['hire_date'], source=source, upline=a['upline'], months_producing=months, total_ap=total_ap, avg_monthly=p.get('avg',0) or 0, peak=p.get('peak',0) or 0, total_rev=total_rev, is_producer=total_ap>0, first=p.get('first',''), last=p.get('last','')))

total = len(results)
producers = [r for r in results if r['is_producer']]
print(f'\n{"="*60}\nFULL AGENT LTV ANALYSIS\n{"="*60}')
print(f'\nTotal agents: {total}')
print(f'Producers: {len(producers)} ({len(producers)/total*100:.1f}%)')
if producers:
    avg_ltv = sum(r['total_rev'] for r in producers)/len(producers)
    avg_ap = sum(r['total_ap'] for r in producers)/len(producers)
    avg_m = sum(r['months_producing'] for r in producers)/len(producers)
    print(f'Avg LTV (producers): ${avg_ltv:,.2f}')
    print(f'Avg AP (producers): ${avg_ap:,.2f}')
    print(f'Avg months producing: {avg_m:.1f}')

print('\n\n--- LTV BY LEAD SOURCE ---')
by_source = defaultdict(list)
for r in results: by_source[r['source']].append(r)
source_costs = {'ZipRecruiter':740,'Wizehire':150,'Direct':0,'Website':50,'Funnels':100,'Organic':0,'Email':20,'Facebook':200,'Trinity':0,'4x4':0,'Unknown':200}
for src in sorted(by_source.keys(), key=lambda s: -len(by_source[s])):
    al = by_source[src]
    pr = [a for a in al if a['is_producer']]
    rate = len(pr)/len(al)*100 if al else 0
    avg = sum(a['total_rev'] for a in pr)/len(pr) if pr else 0
    cac = source_costs.get(src, 200)
    cpp = cac*len(al)/len(pr) if pr else 0
    print(f'\n  {src} ({len(al)} agents, {len(pr)} producing, {rate:.1f}%)')
    if pr:
        print(f'    Avg LTV: ${avg:,.2f} | Cost/producer: ${cpp:,.0f} | ROI: {avg/cpp:.1f}x' if cpp>0 else f'    Avg LTV: ${avg:,.2f} | FREE source')
        best = max(pr, key=lambda a:a['total_ap'])
        print(f'    Best: {best["name"]} (${best["total_ap"]:,.2f} AP)')

print('\n\n--- COHORT ANALYSIS (hire month) ---')
by_month = defaultdict(list)
for r in results:
    if r['hire_date']: by_month[r['hire_date'][:7]].append(r)
for month in sorted(by_month.keys()):
    c = by_month[month]
    pr = [a for a in c if a['is_producer']]
    tap = sum(a['total_ap'] for a in pr)
    print(f'  {month}: {len(c):3d} hired, {len(pr):2d} producing ({len(pr)/len(c)*100:4.1f}%), ${tap:>12,.2f} AP')

print('\n\n--- TOP MANAGERS ---')
by_up = defaultdict(list)
for r in results:
    if r['upline'] and r['upline']!='Unknown': by_up[r['upline']].append(r)
stats = []
for mgr, al in by_up.items():
    pr = [a for a in al if a['is_producer']]
    if len(al)>=3: stats.append((mgr, len(al), len(pr), len(pr)/len(al)*100, sum(a['total_ap'] for a in pr)))
for m in sorted(stats, key=lambda x:-x[4])[:15]:
    print(f'  {m[0]:25s} {m[1]:3d} recruits, {m[2]:2d} producing ({m[3]:4.1f}%), ${m[4]:>12,.2f} AP')

print('\n\n--- TOP 20 AGENTS BY AP ---')
for r in sorted(producers, key=lambda a:-a['total_ap'])[:20]:
    print(f'  {r["name"]:25s} ${r["total_ap"]:>12,.2f} AP  {r["months_producing"]:2d}mo  ${r["avg_monthly"]:>8,.2f}/mo  {r["source"]:12s} {r["upline"]}')

intel.close()
