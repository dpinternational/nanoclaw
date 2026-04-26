#!/usr/bin/env python3
"""Complete LTV model using DAILY production data + Master List."""
import json, sqlite3
from collections import defaultdict
from datetime import datetime

prod_data = json.load(open('/home/david/nanoclaw/data/daily-production-by-agent.json'))
recruit_data = json.load(open('/home/david/nanoclaw/data/recruiting-full-dump.json'))
intel = sqlite3.connect('/home/david/nanoclaw/store/tpg-intel.db')

# Build master agent list
master = recruit_data['master']
hire_info = {}
for row in master[1:]:
    if len(row) < 2 or not row[1]: continue
    name = str(row[1]).strip()
    hire_date = str(row[4]).strip() if len(row)>4 and row[4] else None
    source = str(row[5]).strip() if len(row)>5 and row[5] else ''
    upline = str(row[6]).strip() if len(row)>6 and row[6] else ''
    parsed = None
    if hire_date and '/' in hire_date:
        try:
            parts = hire_date.split('/')
            if len(parts)==3:
                m,d,y = parts
                if len(y)==2: y='20'+y
                parsed = f'{y}-{m.zfill(2)}-{d.zfill(2)}'
        except: pass
    if name not in hire_info:
        hire_info[name] = dict(hire_date=parsed, source=source, upline=upline)

src_map = {'Direct':'Direct','Direct Recruit':'Direct','Website':'Website','Organic':'Organic','ZipRecruiter':'ZipRecruiter','Wizehire':'Wizehire','Funnels':'Funnels','ClickFunnels':'Funnels','clickFunnels':'Funnels','Email':'Email','Facebook':'Facebook','Trinity':'Trinity','4x4 Training':'4x4','4x4 training':'4x4','4x4':'4x4'}

override_pct = 0.15
avg_lead_rev_month = 1094
src_costs = {'ZipRecruiter':740,'Wizehire':150,'Direct':0,'Website':50,'Funnels':100,'Organic':0,'Email':20,'Facebook':200,'Trinity':0,'4x4':0,'Unknown':200}

print('='*60)
print('COMPLETE AGENT LTV MODEL')
print(f'Production data: {len(prod_data)} agents')
print(f'Master list: {len(hire_info)} agents')
print('='*60)

# Match production to hire info
agents = []
matched = 0
for name, monthly in prod_data.items():
    # Skip "Grand Total" row
    if 'grand' in name.lower() or 'total' in name.lower(): continue
    
    total_ap = sum(v for k,v in monthly.items() if k != 'Grand T')
    months_producing = len([k for k in monthly if k != 'Grand T'])
    avg_monthly = total_ap / months_producing if months_producing > 0 else 0
    peak = max(v for k,v in monthly.items() if k != 'Grand T') if monthly else 0
    first_month = min(k for k in monthly if k != 'Grand T') if monthly else ''
    last_month = max(k for k in monthly if k != 'Grand T') if monthly else ''
    
    hi = hire_info.get(name, {})
    source = src_map.get(hi.get('source',''), hi.get('source','Unknown'))
    hire_date = hi.get('hire_date')
    upline = hi.get('upline', 'Unknown')
    if hi: matched += 1
    
    # Months to first sale
    m2f = None
    if hire_date and first_month:
        try:
            hd = datetime.strptime(hire_date, '%Y-%m-%d')
            fm = datetime.strptime(first_month + '-01', '%Y-%m-%d')
            m2f = max(0, (fm.year-hd.year)*12 + fm.month-hd.month)
        except: pass
    
    override = total_ap * override_pct
    lead_rev = months_producing * avg_lead_rev_month
    ltv = override + lead_rev
    cac = src_costs.get(source, 200)
    
    agents.append(dict(
        name=name, hire_date=hire_date, source=source, upline=upline,
        total_ap=total_ap, months=months_producing, avg=avg_monthly,
        peak=peak, first=first_month, last=last_month,
        months_to_first=m2f, override=override, lead_rev=lead_rev,
        ltv=ltv, cac=cac
    ))

print(f'\nProducing agents: {len(agents)}')
print(f'Matched to master list: {matched}')

# Also count non-producers from master list
non_producers = [n for n in hire_info if n not in prod_data and n.strip()]
print(f'Non-producers in master list: {len(non_producers)}')
total_hired = len(agents) + len(non_producers)
print(f'Total hired: {total_hired}')
print(f'Production rate: {len(agents)/total_hired*100:.1f}%')

# Overall LTV
avg_ltv = sum(a['ltv'] for a in agents) / len(agents)
med_ap = sorted(a['total_ap'] for a in agents)[len(agents)//2]
print(f'\nAvg LTV (all producers): ${avg_ltv:,.2f}')
print(f'Median AP: ${med_ap:,.2f}')
print(f'Avg months producing: {sum(a["months"] for a in agents)/len(agents):.1f}')

# By source
print('\n\n--- LTV BY LEAD SOURCE ---')
by_src = defaultdict(lambda: {'producers':[], 'total_hired': 0})
for a in agents: by_src[a['source']]['producers'].append(a)
# Add non-producers
for name in non_producers:
    src = src_map.get(hire_info[name].get('source',''), 'Unknown')
    by_src[src]['total_hired'] += 1

for src in sorted(by_src.keys(), key=lambda s: -len(by_src[s]['producers'])):
    prods = by_src[src]['producers']
    total = len(prods) + by_src[src]['total_hired']
    if total == 0: continue
    rate = len(prods)/total*100
    avg = sum(a['ltv'] for a in prods)/len(prods) if prods else 0
    cac = src_costs.get(src, 200)
    cpp = cac * total / len(prods) if prods else 0
    roi = avg/cpp if cpp > 0 else float('inf')
    
    print(f'\n  {src}')
    print(f'    Total hired: {total} | Producing: {len(prods)} ({rate:.1f}%)')
    if prods:
        print(f'    Avg LTV per producer: ${avg:,.2f}')
        print(f'    Cost per hire: ${cac} | Cost per PRODUCER: ${cpp:,.0f}')
        print(f'    ROI: {roi:.1f}x')
        best = max(prods, key=lambda a:a['total_ap'])
        print(f'    Best: {best["name"]} (${best["total_ap"]:,.2f} AP, {best["months"]}mo)')

# Cohort analysis
print('\n\n--- COHORT ANALYSIS ---')
by_month = defaultdict(lambda: {'hired': 0, 'producers': []})
for a in agents:
    if a['hire_date']:
        m = a['hire_date'][:7]
        by_month[m]['producers'].append(a)
for name in non_producers:
    hd = hire_info[name].get('hire_date')
    if hd: by_month[hd[:7]]['hired'] += 1

for month in sorted(by_month.keys()):
    c = by_month[month]
    prods = c['producers']
    total = len(prods) + c['hired']
    if total == 0: continue
    rate = len(prods)/total*100
    tap = sum(a['total_ap'] for a in prods)
    avg_ltv = sum(a['ltv'] for a in prods)/len(prods) if prods else 0
    print(f'  {month}: {total:3d} hired, {len(prods):3d} producing ({rate:5.1f}%), ${tap:>12,.2f} AP, avg LTV ${avg_ltv:>10,.2f}')

# Manager analysis
print('\n\n--- MANAGER EFFECTIVENESS ---')
by_mgr = defaultdict(lambda: {'producers': [], 'total': 0})
for a in agents:
    if a['upline'] and a['upline'] != 'Unknown':
        by_mgr[a['upline']]['producers'].append(a)
for name in non_producers:
    up = hire_info[name].get('upline','')
    if up: by_mgr[up]['total'] += 1

mgr_stats = []
for mgr, data in by_mgr.items():
    total = len(data['producers']) + data['total']
    if total < 5: continue
    prods = data['producers']
    rate = len(prods)/total*100
    tap = sum(a['total_ap'] for a in prods)
    avg_ltv = sum(a['ltv'] for a in prods)/len(prods) if prods else 0
    mgr_stats.append((mgr, total, len(prods), rate, tap, avg_ltv))

for m in sorted(mgr_stats, key=lambda x:-x[4])[:15]:
    print(f'  {m[0]:25s} {m[1]:3d} recruits, {m[2]:3d} producing ({m[3]:5.1f}%), ${m[4]:>12,.2f} AP, avg LTV ${m[5]:>10,.2f}')

# Top 25 agents
print('\n\n--- TOP 25 AGENTS BY LTV ---')
for a in sorted(agents, key=lambda x:-x['ltv'])[:25]:
    m2f = f'{a["months_to_first"]}mo' if a['months_to_first'] is not None else '?'
    print(f'  {a["name"]:25s} LTV ${a["ltv"]:>10,.2f} | AP ${a["total_ap"]:>12,.2f} | {a["months"]:2d}mo | ${a["avg"]:>8,.2f}/mo | 1st sale: {m2f} | {a["source"]:12s} | {a["upline"]}')

# Key insights
print('\n\n' + '='*60)
print('KEY INSIGHTS FOR CEO')
print('='*60)
top_src = max(by_src.items(), key=lambda x: len(x[1]['producers']))
print(f'\n1. Best source: {top_src[0]} ({len(top_src[1]["producers"])} producers)')
avg_m2f = [a['months_to_first'] for a in agents if a['months_to_first'] is not None and a['months_to_first'] > 0]
if avg_m2f:
    print(f'2. Avg months to first sale: {sum(avg_m2f)/len(avg_m2f):.1f}')
print(f'3. Overall production rate: {len(agents)/total_hired*100:.1f}% of hires produce')
print(f'4. Average producer LTV: ${avg_ltv:,.2f}')
print(f'5. You can spend up to ${avg_ltv:,.0f} per PRODUCER to break even')

intel.close()
