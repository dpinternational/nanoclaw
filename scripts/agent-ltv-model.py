#!/usr/bin/env python3
"""
Agent Lifetime Value (LTV) Model

Pulls data from:
  - Recruiting Report (Google Sheet) — hire dates, sources, managers, production
  - Production Report (xlsx) — monthly agent production
  - Money Report (Google Sheet) — revenue, costs, lead data
  
Builds per-agent, per-source, per-manager LTV calculations.
"""

import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta
from collections import defaultdict

NANOCLAW = "/home/david/nanoclaw"
INTEL_DB = os.path.join(NANOCLAW, "store", "tpg-intel.db")
RECRUITING_SHEET = "1cn5a5eWiBbH1IcQe6jpzwyTc4yrquBpCFeuDjSIEabI"
MONEY_SHEET = "1K7kGLmJJ6a7ilKfPqjyIEhoB6nBkL4Cu94uR6JUtMdw"


def sheets_api():
    """Get authenticated Google Sheets API."""
    node_script = """
const {google} = require('googleapis');
const fs = require('fs'), path = require('path');
const credDir = '/home/david/.gmail-mcp';
const keys = JSON.parse(fs.readFileSync(path.join(credDir, 'gcp-oauth.keys.json'), 'utf-8'));
const tokens = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8'));
const config = keys.installed || keys.web || keys;
const auth = new google.auth.OAuth2(config.client_id, config.client_secret, config.redirect_uris?.[0]);
auth.setCredentials(tokens);
auth.on('tokens', t => {
  const c = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8'));
  Object.assign(c, t);
  fs.writeFileSync(path.join(credDir, 'credentials.json'), JSON.stringify(c, null, 2));
});
const sheets = google.sheets({version:'v4',auth});

async function main() {
  const args = JSON.parse(process.argv[2]);
  const results = {};
  for (const [key, {id, range}] of Object.entries(args)) {
    try {
      const res = await sheets.spreadsheets.values.get({spreadsheetId:id, range});
      results[key] = res.data.values || [];
    } catch(e) {
      results[key] = {error: e.message};
    }
  }
  console.log(JSON.stringify(results));
}
main();
"""
    return node_script


def fetch_sheets(queries):
    """Fetch multiple sheet ranges in one call."""
    script_path = f"/tmp/_sheets_{os.getpid()}.js"
    node_script = sheets_api()
    with open(script_path, "w") as f:
        f.write(node_script)

    result = subprocess.run(
        ["node", script_path, json.dumps(queries)],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "HOME": "/home/david",
             "NODE_PATH": f"{NANOCLAW}/node_modules"},
        cwd=NANOCLAW,
    )
    os.unlink(script_path)

    for i, ch in enumerate(result.stdout):
        if ch == '{':
            return json.loads(result.stdout[i:])
    return {}


def ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS agent_ltv (
        agent_name TEXT PRIMARY KEY,
        hire_date TEXT,
        lead_source TEXT,
        manager TEXT,
        team_name TEXT,
        months_active INTEGER DEFAULT 0,
        total_personal_ap REAL DEFAULT 0,
        total_team_ap REAL DEFAULT 0,
        estimated_override_revenue REAL DEFAULT 0,
        estimated_lead_revenue REAL DEFAULT 0,
        estimated_total_revenue REAL DEFAULT 0,
        cost_to_acquire REAL DEFAULT 0,
        ltv REAL DEFAULT 0,
        ltv_to_cac REAL DEFAULT 0,
        status TEXT DEFAULT 'unknown',
        first_sale_month TEXT,
        months_to_first_sale INTEGER,
        avg_monthly_ap REAL DEFAULT 0,
        peak_monthly_ap REAL DEFAULT 0,
        last_production_month TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS ltv_by_source (
        lead_source TEXT PRIMARY KEY,
        total_agents INTEGER,
        producing_agents INTEGER,
        production_rate REAL,
        avg_ltv REAL,
        median_ltv REAL,
        total_cost REAL,
        cost_per_hire REAL,
        avg_ltv_to_cac REAL,
        total_revenue REAL,
        total_profit REAL
    );

    CREATE TABLE IF NOT EXISTS ltv_by_manager (
        manager TEXT PRIMARY KEY,
        total_agents INTEGER,
        producing_agents INTEGER,
        production_rate REAL,
        avg_agent_ltv REAL,
        best_agent TEXT,
        best_agent_ltv REAL,
        total_team_revenue REAL
    );

    CREATE TABLE IF NOT EXISTS ltv_cohorts (
        cohort_month TEXT PRIMARY KEY,
        agents_hired INTEGER,
        agents_producing INTEGER,
        production_rate REAL,
        total_ap REAL,
        avg_ap REAL,
        avg_months_to_first_sale REAL,
        lead_source_breakdown TEXT
    );

    CREATE TABLE IF NOT EXISTS sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        last_synced TEXT,
        rows_synced INTEGER,
        status TEXT,
        created_at TEXT
    );
    """)


def parse_date(d):
    """Parse various date formats."""
    if not d:
        return None
    d = str(d).strip()
    for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m/%d"]:
        try:
            parsed = datetime.strptime(d, fmt)
            if parsed.year < 2000:
                parsed = parsed.replace(year=parsed.year + 2000)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_money(val):
    """Parse money strings like '$5,374.50' to float."""
    if not val:
        return 0
    s = str(val).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0


def main():
    print("=" * 60)
    print("AGENT LIFETIME VALUE MODEL")
    print("=" * 60)

    # Fetch all data from Google Sheets
    print("\n1. Fetching data from Google Sheets...")
    data = fetch_sheets({
        "comp_roi": {"id": RECRUITING_SHEET, "range": "Comp ROI!A1:J200"},
        "master": {"id": RECRUITING_SHEET, "range": "Master List!A1:G500"},
        "summary_2025": {"id": RECRUITING_SHEET, "range": "Summary-2025!A1:I30"},
        "summary_2026": {"id": RECRUITING_SHEET, "range": "Summary-2026!A1:I30"},
        "revenue": {"id": MONEY_SHEET, "range": "Revenue!A1:M15"},
        "expenses": {"id": MONEY_SHEET, "range": " Expenses!A1:M25"},
    })

    for key, val in data.items():
        if isinstance(val, dict) and "error" in val:
            print(f"   WARNING: {key}: {val['error']}")
        else:
            print(f"   {key}: {len(val)} rows")

    # Setup DB
    print("\n2. Setting up database...")
    conn = sqlite3.connect(INTEL_DB)
    ensure_tables(conn)
    now = datetime.utcnow().isoformat()

    # Parse Comp ROI — agents with hire date, source, manager, production
    print("\n3. Parsing Comp ROI (agent production data)...")
    comp_roi = data.get("comp_roi", [])
    agents = {}

    for row in comp_roi:
        if not row or len(row) < 6:
            continue
        # Skip header-like rows
        if str(row[0]).strip() in ("", "None") and not row[1]:
            continue

        name = str(row[1]).strip() if len(row) > 1 and row[1] else None
        if not name or name in ("None", ""):
            continue

        hire_date = parse_date(row[4]) if len(row) > 4 else None
        source = str(row[5]).strip() if len(row) > 5 and row[5] else "Unknown"
        manager = str(row[6]).strip() if len(row) > 6 and row[6] else "Unknown"
        production = parse_money(row[8]) if len(row) > 8 else 0
        policies = int(float(row[9])) if len(row) > 9 and row[9] and str(row[9]) != "0" else 0

        if name not in agents:
            agents[name] = {
                "name": name,
                "hire_date": hire_date,
                "source": source,
                "manager": manager,
                "production": production,
                "policies": policies,
            }
        else:
            # Update if this row has more data
            if production > agents[name]["production"]:
                agents[name]["production"] = production
            if not agents[name]["hire_date"] and hire_date:
                agents[name]["hire_date"] = hire_date

    print(f"   {len(agents)} agents found")

    # Parse Master List for hire dates we might be missing
    print("\n4. Enriching from Master List...")
    master = data.get("master", [])
    enriched = 0
    for row in master:
        if not row or len(row) < 5:
            continue
        name = str(row[0]).strip() if row[0] else None
        hire_date = parse_date(row[4]) if len(row) > 4 else None

        if name and hire_date:
            if name not in agents:
                agents[name] = {
                    "name": name,
                    "hire_date": hire_date,
                    "source": "Unknown",
                    "manager": "Unknown",
                    "production": 0,
                    "policies": 0,
                }
                enriched += 1
            elif not agents[name].get("hire_date"):
                agents[name]["hire_date"] = hire_date
                enriched += 1
    print(f"   {enriched} agents enriched")

    # Get personal production from intel DB (already synced from Gina's report)
    print("\n5. Matching with production data...")
    existing_production = {}
    try:
        rows = conn.execute("""
            SELECT agent_name, team_name, 
                   COUNT(DISTINCT month) as months,
                   SUM(production) as total,
                   AVG(production) as avg_monthly,
                   MAX(production) as peak,
                   MIN(month) as first_month,
                   MAX(month) as last_month
            FROM agent_production
            GROUP BY agent_name
        """).fetchall()
        for r in rows:
            existing_production[r[0]] = {
                "team": r[1], "months": r[2], "total": r[3],
                "avg": r[4], "peak": r[5], "first": r[6], "last": r[7],
            }
        print(f"   {len(existing_production)} agents with production history")
    except Exception:
        print("   No production data in DB yet")

    # Parse cost data from Money Report
    print("\n6. Parsing cost data...")
    revenue_rows = data.get("revenue", [])
    monthly_commissions = []
    monthly_agents = []
    monthly_leads = []
    monthly_lead_revenue = []
    monthly_hires = []

    for row in revenue_rows:
        if not row:
            continue
        label = str(row[0]).strip() if row[0] else ""
        if label == "Commisions":
            monthly_commissions = [parse_money(c) for c in row[1:13]]
        elif label == "Writing Agents":
            monthly_agents = [int(float(c)) if c and c != "" else 0 for c in row[1:13]]
        elif label == "Lead Distributed":
            monthly_leads = [parse_money(c) for c in row[1:13]]
        elif label == "Lead Revenue":
            monthly_lead_revenue = [parse_money(c) for c in row[1:13]]
        elif label == "Agents Hired":
            monthly_hires = [int(float(c)) if c and c != "" else 0 for c in row[1:13]]

    # Calculate average override per agent per month
    total_commission = sum(c for c in monthly_commissions if c > 0)
    total_agent_months = sum(a for a in monthly_agents if a > 0)
    avg_override_per_agent_month = total_commission / total_agent_months if total_agent_months > 0 else 0

    # Average lead revenue per agent per month
    total_lead_rev = sum(r for r in monthly_lead_revenue if r > 0)
    avg_lead_rev_per_agent_month = total_lead_rev / total_agent_months if total_agent_months > 0 else 0

    total_rev_per_agent_month = avg_override_per_agent_month + avg_lead_rev_per_agent_month

    print(f"   Override per agent/month: ${avg_override_per_agent_month:,.2f}")
    print(f"   Lead rev per agent/month: ${avg_lead_rev_per_agent_month:,.2f}")
    print(f"   Total rev per agent/month: ${total_rev_per_agent_month:,.2f}")

    # Parse recruiting costs by source
    summary_2025 = data.get("summary_2025", [])
    summary_2026 = data.get("summary_2026", [])
    source_costs = {"Wizehire": 500, "ZipRecruiter": 4936}  # monthly
    source_hires = defaultdict(int)
    source_total_cost = defaultdict(float)

    for rows in [summary_2025, summary_2026]:
        for row in rows:
            if not row or len(row) < 7:
                continue
            source = str(row[1]).strip() if len(row) > 1 and row[1] else ""
            hires = int(float(row[5])) if len(row) > 5 and row[5] and str(row[5]).replace("$", "").replace(",", "").strip().replace(".", "").isdigit() else 0
            cost = parse_money(row[3]) if len(row) > 3 else 0
            if source in ("Wizehire", "ZipRecruiter") and hires > 0:
                source_hires[source] += hires
                source_total_cost[source] += cost

    cost_per_hire = {}
    for source in source_costs:
        if source_hires[source] > 0:
            cost_per_hire[source] = source_total_cost[source] / source_hires[source]
        else:
            cost_per_hire[source] = source_costs[source]  # estimate

    print(f"   Wizehire: {source_hires.get('Wizehire', 0)} hires, ${cost_per_hire.get('Wizehire', 0):,.2f}/hire")
    print(f"   ZipRecruiter: {source_hires.get('ZipRecruiter', 0)} hires, ${cost_per_hire.get('ZipRecruiter', 0):,.2f}/hire")

    # Build LTV for each agent
    print("\n7. Calculating Agent LTV...")
    ltv_count = 0

    for name, agent in agents.items():
        # Get production data if available
        prod = existing_production.get(name, {})
        months_active = prod.get("months", 0)
        total_ap = prod.get("total", agent["production"])
        avg_monthly = prod.get("avg", 0)
        peak = prod.get("peak", 0)
        first_month = prod.get("first", "")
        last_month = prod.get("last", "")
        team = prod.get("team", "")

        # If no production from Gina's report, use Comp ROI data
        if total_ap == 0 and agent["production"] > 0:
            total_ap = agent["production"]

        # Calculate months to first sale
        months_to_first = None
        if agent["hire_date"] and first_month:
            try:
                hire_dt = datetime.strptime(agent["hire_date"], "%Y-%m-%d")
                first_dt = datetime.strptime(first_month + "-01", "%Y-%m-%d")
                months_to_first = max(0, (first_dt.year - hire_dt.year) * 12 + first_dt.month - hire_dt.month)
            except ValueError:
                pass

        # Estimate total months active (hire to last production or now)
        if months_active == 0 and agent["hire_date"]:
            try:
                hire_dt = datetime.strptime(agent["hire_date"], "%Y-%m-%d")
                end = datetime.strptime(last_month + "-01", "%Y-%m-%d") if last_month else datetime.now()
                months_active = max(1, (end.year - hire_dt.year) * 12 + end.month - hire_dt.month)
            except ValueError:
                months_active = 1

        # Revenue estimate
        override_rev = months_active * avg_override_per_agent_month if months_active > 0 and total_ap > 0 else 0
        # More precise: use their actual AP with an estimated override %
        # Typical IMO override is 10-25% of agent's AP
        override_pct = 0.15  # estimate 15% average override
        override_rev_from_ap = total_ap * override_pct
        lead_rev = months_active * avg_lead_rev_per_agent_month if months_active > 0 else 0
        total_rev = override_rev_from_ap + lead_rev

        # Cost to acquire
        source = agent["source"]
        cac = cost_per_hire.get(source, 300)  # default $300

        # LTV
        ltv = total_rev
        ltv_cac = ltv / cac if cac > 0 else 0

        # Status
        status = "producing" if total_ap > 0 else "zero"

        conn.execute("""
            INSERT OR REPLACE INTO agent_ltv
            (agent_name, hire_date, lead_source, manager, team_name,
             months_active, total_personal_ap, estimated_override_revenue,
             estimated_lead_revenue, estimated_total_revenue,
             cost_to_acquire, ltv, ltv_to_cac, status,
             first_sale_month, months_to_first_sale,
             avg_monthly_ap, peak_monthly_ap, last_production_month, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, agent["hire_date"], source, agent["manager"], team,
              months_active, round(total_ap, 2),
              round(override_rev_from_ap, 2), round(lead_rev, 2), round(total_rev, 2),
              round(cac, 2), round(ltv, 2), round(ltv_cac, 1), status,
              first_month, months_to_first,
              round(avg_monthly, 2), round(peak, 2), last_month, now))
        ltv_count += 1

    conn.commit()
    print(f"   {ltv_count} agents processed")

    # Build source-level LTV
    print("\n8. Building LTV by source...")
    for source in ["Wizehire", "ZipRecruiter", "Unknown", "Direct"]:
        rows = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN total_personal_ap > 0 THEN 1 ELSE 0 END) as producing,
                   AVG(ltv) as avg_ltv,
                   SUM(estimated_total_revenue) as total_rev,
                   SUM(cost_to_acquire) as total_cost
            FROM agent_ltv WHERE lead_source = ?
        """, (source,)).fetchone()

        if rows and rows[0] > 0:
            prod_rate = rows[1] / rows[0] if rows[0] > 0 else 0
            profit = (rows[3] or 0) - (rows[4] or 0)
            conn.execute("""
                INSERT OR REPLACE INTO ltv_by_source
                (lead_source, total_agents, producing_agents, production_rate,
                 avg_ltv, total_cost, cost_per_hire, total_revenue, total_profit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (source, rows[0], rows[1], round(prod_rate, 3),
                  round(rows[2] or 0, 2), round(rows[4] or 0, 2),
                  round((rows[4] or 0) / rows[0], 2) if rows[0] > 0 else 0,
                  round(rows[3] or 0, 2), round(profit, 2)))

    conn.commit()

    # Build manager-level LTV
    print("9. Building LTV by manager...")
    managers = conn.execute("""
        SELECT manager, COUNT(*) as total,
               SUM(CASE WHEN total_personal_ap > 0 THEN 1 ELSE 0 END) as producing,
               AVG(ltv) as avg_ltv,
               SUM(estimated_total_revenue) as total_rev
        FROM agent_ltv WHERE manager != 'Unknown'
        GROUP BY manager ORDER BY total_rev DESC
    """).fetchall()

    for m in managers:
        best = conn.execute("""
            SELECT agent_name, ltv FROM agent_ltv
            WHERE manager = ? ORDER BY ltv DESC LIMIT 1
        """, (m[0],)).fetchone()
        conn.execute("""
            INSERT OR REPLACE INTO ltv_by_manager
            (manager, total_agents, producing_agents, production_rate,
             avg_agent_ltv, best_agent, best_agent_ltv, total_team_revenue)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (m[0], m[1], m[2], round(m[2] / m[1], 3) if m[1] > 0 else 0,
              round(m[3] or 0, 2), best[0] if best else None,
              round(best[1], 2) if best else 0, round(m[4] or 0, 2)))

    conn.commit()

    # Print results
    print("\n" + "=" * 60)
    print("AGENT LTV RESULTS")
    print("=" * 60)

    print("\n📊 LTV BY LEAD SOURCE:")
    for r in conn.execute("SELECT * FROM ltv_by_source ORDER BY total_revenue DESC"):
        print(f"\n  {r[0]}:")
        print(f"    Agents: {r[1]} ({r[2]} producing, {r[3]*100:.1f}% rate)")
        print(f"    Avg LTV: ${r[4]:,.2f}")
        print(f"    Cost/hire: ${r[6]:,.2f}")
        print(f"    Total revenue: ${r[7] or 0:,.2f}")
        print(f"    Total profit: ${r[8] or 0:,.2f}")

    print("\n\n👥 LTV BY MANAGER (top 10):")
    for r in conn.execute("SELECT * FROM ltv_by_manager ORDER BY total_team_revenue DESC LIMIT 10"):
        print(f"  {r[0]:25s} {r[1]:3d} agents ({r[2]} producing, {r[3]*100:.0f}%) avg LTV ${r[4]:>10,.2f}  best: {r[5]} (${r[6]:,.2f})")

    print("\n\n🏆 TOP 15 AGENTS BY LTV:")
    for r in conn.execute("""
        SELECT agent_name, ltv, total_personal_ap, months_active, lead_source, manager,
               months_to_first_sale, avg_monthly_ap, cost_to_acquire, ltv_to_cac
        FROM agent_ltv WHERE ltv > 0
        ORDER BY ltv DESC LIMIT 15
    """):
        print(f"  {r[0]:25s} LTV ${r[1]:>10,.2f}  AP ${r[2]:>10,.2f}  {r[4]:12s}  mgr:{r[5]:15s}  LTV:CAC {r[9]:.1f}x")

    print("\n\n⚠️  ZERO PRODUCERS (hired but never sold):")
    zeros = conn.execute("SELECT COUNT(*) FROM agent_ltv WHERE status = 'zero'").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM agent_ltv").fetchone()[0]
    print(f"  {zeros} of {total} agents ({zeros/total*100:.0f}%) never produced")

    avg_months_to_first = conn.execute("""
        SELECT AVG(months_to_first_sale) FROM agent_ltv 
        WHERE months_to_first_sale IS NOT NULL AND months_to_first_sale > 0
    """).fetchone()[0]
    print(f"  Avg months to first sale (producers): {avg_months_to_first:.1f}" if avg_months_to_first else "")

    print("\n" + "=" * 60)
    conn.close()


if __name__ == "__main__":
    main()
