#!/usr/bin/env python3
import json, openpyxl

d = json.load(open('/home/david/nanoclaw/data/recruiting-full-dump.json'))
master = d['master']

print("=== MASTER LIST ===")
for row in master:
    if len(row) > 1:
        name = str(row[1]).strip() if row[1] else ''
        if 'nussbaum' in name.lower() or 'deshotel' in name.lower():
            hire = row[4] if len(row) > 4 else '?'
            source = row[5] if len(row) > 5 else '?'
            upline = row[6] if len(row) > 6 else '?'
            print(f"  {name}: hired={hire}, source={source}, upline={upline}")

print("\n=== SCREEN NAME TAB ===")
wb = openpyxl.load_workbook('/home/david/nanoclaw/data/production-reporting.xlsx', data_only=True)
ws = wb['SCREEN NAME']
for row in ws.iter_rows(min_row=2, values_only=True):
    name = str(row[0]).strip() if row[0] else ''
    if 'nussbaum' in name.lower() or 'deshotel' in name.lower():
        screen = row[1] if len(row) > 1 else '?'
        mgr = row[3] if len(row) > 3 else '?'
        team = row[4] if len(row) > 4 else '?'
        print(f"  {name}: screen={screen}, manager={mgr}, team={team}")
