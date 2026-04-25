import os, requests, datetime

sb=os.environ['SUPABASE_URL'].rstrip('/')
key=os.environ['SUPABASE_KEY']
h={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json'}

# 1) verify table exists
u=f"{sb}/rest/v1/smartlead_webhook_events?select=id,received_at,event_type,campaign_id,lead_id,lead_email&order=received_at.desc&limit=1"
r=requests.get(u,headers=h,timeout=30)
print('table_check',r.status_code)
print('table_check_body',r.text[:300])

# 2) trigger webhook test event
payload={
  'event_type':'MANUAL_HEALTHCHECK',
  'campaign_id':3232436,
  'lead_id':1001,
  'lead_email':'manual+postschema@tpglife.com',
  'description':'post-schema verification'
}
r2=requests.post('https://89.167.109.12.sslip.io/smartlead/webhook',json=payload,timeout=30)
print('webhook_post',r2.status_code,r2.text)

# 3) verify inserted
u2=f"{sb}/rest/v1/smartlead_webhook_events?select=id,received_at,event_type,campaign_id,lead_id,lead_email&lead_email=eq.manual%2Bpostschema%40tpglife.com&order=received_at.desc&limit=1"
r3=requests.get(u2,headers=h,timeout=30)
print('verify_insert',r3.status_code,r3.text)

# 4) 24h event counts
since=(datetime.datetime.utcnow()-datetime.timedelta(hours=24)).isoformat() + 'Z'
u3=f"{sb}/rest/v1/smartlead_webhook_events?select=campaign_id,event_type,received_at&received_at=gte.{since}&order=received_at.desc&limit=5000"
r4=requests.get(u3,headers=h,timeout=60)
print('events_fetch',r4.status_code)
if r4.ok:
    rows=r4.json()
    agg={}
    for x in rows:
        k=(x.get('campaign_id'),x.get('event_type'))
        agg[k]=agg.get(k,0)+1
    print('events_rows',len(rows))
    for (cid,etype),cnt in sorted(agg.items(), key=lambda kv: ((kv[0][0] if kv[0][0] is not None else -1), (kv[0][1] or ''))):
        print('event_count',cid,etype,cnt)
else:
    print('events_fetch_body',r4.text[:400])
