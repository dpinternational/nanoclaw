#!/usr/bin/env python3
import json

prod = json.load(open('/home/david/nanoclaw/data/daily-production-by-agent.json'))
recruit = json.load(open('/home/david/nanoclaw/data/recruiting-full-dump.json'))

master = recruit['master']
manager_agents = {}
for row in master[1:]:
    if len(row) < 7: continue
    name = str(row[1]).strip() if row[1] else ''
    upline = str(row[6]).strip() if len(row) > 6 and row[6] else ''
    if not name or not upline or upline == 'Unknown': continue
    if upline not in manager_agents:
        manager_agents[upline] = []
    total_ap = sum(prod.get(name, {}).values()) if name in prod else 0
    months = len(prod.get(name, {})) if name in prod else 0
    manager_agents[upline].append(dict(name=name, ap=total_ap, months=months, producing=total_ap > 0))

stats = []
for mgr, agents in manager_agents.items():
    total = len(agents)
    if total < 3: continue
    prods = [a for a in agents if a['producing']]
    rate = len(prods) / total
    total_ap = sum(a['ap'] for a in agents)
    avg_ap = total_ap / len(prods) if prods else 0
    best = max(agents, key=lambda a: a['ap']) if agents else None
    if rate >= 0.45: grade = 'A - Elite'
    elif rate >= 0.30: grade = 'B - Good'
    elif rate >= 0.20: grade = 'C - Average'
    else: grade = 'D - Needs Work'
    stats.append((mgr, total, len(prods), rate, total_ap, avg_ap, best, grade))

print("MANAGER SCORECARD — WHO DEVELOPS PRODUCERS?")
print("=" * 80)
print()
for s in sorted(stats, key=lambda x: -x[4]):
    best_name = s[6]['name'][:22] if s[6] else ''
    best_ap = s[6]['ap'] if s[6] else 0
    print(f"  {s[7]:15s}  {s[0]}")
    print(f"    Recruits: {s[1]} | Producing: {s[2]} | Rate: {s[3]*100:.1f}%")
    print(f"    Total AP: ${s[4]:,.2f} | Avg per producer: ${s[5]:,.2f}")
    print(f"    Best agent: {best_name} (${best_ap:,.2f})")
    print()

print("Grade: A = 45%+ | B = 30-44% | C = 20-29% | D = under 20%")
