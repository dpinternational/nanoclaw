import os, requests, datetime, json

sb=os.environ['SUPABASE_URL'].rstrip('/')
key=os.environ['SUPABASE_KEY']
h={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json'}

campaign_ids=[3232436,3232437]

# latest campaign metrics
latest={}
for cid in campaign_ids:
    u=f"{sb}/rest/v1/smartlead_campaign_metrics?select=campaign_id,campaign_name,status,sent_count,reply_count,bounce_count,unsubscribe_count,captured_at&campaign_id=eq.{cid}&order=captured_at.desc&limit=1"
    r=requests.get(u,headers=h,timeout=30)
    latest[cid]=(r.json()[0] if r.ok and r.json() else None)

# webhook 24h
since=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=24)).isoformat()
u=f"{sb}/rest/v1/smartlead_webhook_events?select=campaign_id,event_type,received_at&received_at=gte.{since}&limit=5000"
r=requests.get(u,headers=h,timeout=60)
rows=r.json() if r.ok else []

agg={cid:{'sent':0,'bounced':0,'reply':0,'unsub':0,'complaint':0} for cid in campaign_ids}
for x in rows:
    cid=x.get('campaign_id')
    et=(x.get('event_type') or '').upper()
    if cid not in agg:
        continue
    if et=='EMAIL_SENT': agg[cid]['sent']+=1
    elif et=='EMAIL_BOUNCED': agg[cid]['bounced']+=1
    elif et=='EMAIL_REPLY': agg[cid]['reply']+=1
    elif et=='LEAD_UNSUBSCRIBED': agg[cid]['unsub']+=1
    elif et in ('EMAIL_COMPLAINED','SPAM_COMPLAINT'): agg[cid]['complaint']+=1

# mailbox health latest snapshot
u2=f"{sb}/rest/v1/smartlead_mailbox_health?select=from_email,smtp_ok,imap_ok,warmup_enabled,message_per_day,daily_sent_count,campaign_count,is_connected_to_campaign,captured_at&order=captured_at.desc&limit=24"
r2=requests.get(u2,headers=h,timeout=30)
mb=r2.json() if r2.ok else []

# sync run
u3=f"{sb}/rest/v1/smartlead_sync_runs?select=id,ok,details,created_at&order=created_at.desc&limit=1"
r3=requests.get(u3,headers=h,timeout=30)
sync=(r3.json()[0] if r3.ok and r3.json() else None)

# recommendation
def rec(v):
    sent=v['sent']; bounced=v['bounced']; reply=v['reply']; unsub=v['unsub']; complaint=v['complaint']
    delivered=max(sent-bounced,0)
    bounce=(bounced/sent*100) if sent else 0.0
    replyr=(reply/delivered*100) if delivered else 0.0
    unsubr=(unsub/delivered*100) if delivered else 0.0
    if complaint>=1 or bounce>3.0 or unsubr>1.5:
        decision='PAUSE'
    elif (2.0<=bounce<=3.0) or (1.0<=unsubr<=1.5) or (replyr<2.0):
        decision='HOLD'
    elif bounce<=2.0 and complaint==0 and unsubr<1.0 and replyr>=2.0:
        decision='SCALE_+25%'
    else:
        decision='HOLD'
    return {'sent':sent,'bounced':bounced,'delivered_est':delivered,'reply':reply,'unsub':unsub,'complaint':complaint,
            'bounce_rate_pct':round(bounce,2),'reply_rate_pct':round(replyr,2),'unsub_rate_pct':round(unsubr,2),'recommendation':decision}

print('LATEST_CAMPAIGN_METRICS')
for cid in campaign_ids:
    print(cid, json.dumps(latest[cid], default=str))

print('\nWEBHOOK_24H_ROLLUP')
for cid in campaign_ids:
    print(cid, json.dumps(rec(agg[cid])))

print('\nMAILBOX_HEALTH_SUMMARY')
smtp_ok=sum(1 for x in mb if x.get('smtp_ok') is True)
imap_ok=sum(1 for x in mb if x.get('imap_ok') is True)
print({'rows':len(mb),'smtp_ok':smtp_ok,'imap_ok':imap_ok})

print('\nLAST_SYNC_RUN')
print(json.dumps(sync, default=str))
