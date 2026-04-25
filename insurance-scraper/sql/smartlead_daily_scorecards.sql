-- Smartlead daily scorecards (pilot-safe)
-- Project: TPG cold outreach
-- Campaigns:
--   3232436 = Seq A - New Licensees PILOT (25)
--   3232437 = Seq B - Single Carrier PILOT (25)

-- 0) Preconditions check
SELECT
  to_regclass('public.smartlead_campaign_metrics')    AS has_campaign_metrics,
  to_regclass('public.smartlead_mailbox_health')      AS has_mailbox_health,
  to_regclass('public.smartlead_sync_runs')           AS has_sync_runs,
  to_regclass('public.smartlead_webhook_events')      AS has_webhook_events;

-- 1) Latest campaign scorecard (from smartlead_sync polling snapshots)
WITH latest AS (
  SELECT DISTINCT ON (campaign_id)
    campaign_id,
    campaign_name,
    status,
    sent_count,
    open_count,
    click_count,
    reply_count,
    bounce_count,
    unsubscribe_count,
    captured_at
  FROM smartlead_campaign_metrics
  WHERE campaign_id IN (3232436, 3232437)
  ORDER BY campaign_id, captured_at DESC
)
SELECT
  campaign_id,
  campaign_name,
  status,
  sent_count,
  COALESCE(bounce_count,0) AS bounce_count,
  COALESCE(reply_count,0) AS reply_count,
  COALESCE(unsubscribe_count,0) AS unsubscribe_count,
  GREATEST(COALESCE(sent_count,0) - COALESCE(bounce_count,0), 0) AS delivered_est,
  ROUND((COALESCE(bounce_count,0)::numeric / NULLIF(sent_count,0)) * 100, 2) AS bounce_rate_pct,
  ROUND((COALESCE(reply_count,0)::numeric / NULLIF(GREATEST(COALESCE(sent_count,0)-COALESCE(bounce_count,0),0),0)) * 100, 2) AS reply_rate_pct,
  ROUND((COALESCE(unsubscribe_count,0)::numeric / NULLIF(GREATEST(COALESCE(sent_count,0)-COALESCE(bounce_count,0),0),0)) * 100, 2) AS unsub_rate_pct,
  captured_at
FROM latest
ORDER BY campaign_id;

-- 2) Webhook events by campaign + event type (last 24h)
SELECT
  COALESCE(campaign_id, -1) AS campaign_id,
  event_type,
  COUNT(*) AS events_24h
FROM smartlead_webhook_events
WHERE received_at >= NOW() - INTERVAL '24 hours'
GROUP BY 1,2
ORDER BY 1,2;

-- 3) Campaign-level event rates from webhook events (last 24h)
-- Uses event counts directly from webhook stream. "Delivered" is approximated as SENT-BOUNCED.
WITH events AS (
  SELECT
    campaign_id,
    COUNT(*) FILTER (WHERE event_type IN ('EMAIL_SENT')) AS sent_events,
    COUNT(*) FILTER (WHERE event_type IN ('EMAIL_BOUNCED')) AS bounced_events,
    COUNT(*) FILTER (WHERE event_type IN ('EMAIL_REPLY')) AS reply_events,
    COUNT(*) FILTER (WHERE event_type IN ('LEAD_UNSUBSCRIBED')) AS unsub_events,
    COUNT(*) FILTER (WHERE event_type IN ('EMAIL_COMPLAINED','SPAM_COMPLAINT')) AS complaint_events
  FROM smartlead_webhook_events
  WHERE received_at >= NOW() - INTERVAL '24 hours'
    AND campaign_id IN (3232436, 3232437)
  GROUP BY campaign_id
), scored AS (
  SELECT
    campaign_id,
    sent_events,
    bounced_events,
    reply_events,
    unsub_events,
    complaint_events,
    GREATEST(sent_events - bounced_events, 0) AS delivered_est
  FROM events
)
SELECT
  campaign_id,
  sent_events,
  bounced_events,
  delivered_est,
  reply_events,
  unsub_events,
  complaint_events,
  ROUND((bounced_events::numeric / NULLIF(sent_events,0)) * 100, 2) AS bounce_rate_pct,
  ROUND((reply_events::numeric / NULLIF(delivered_est,0)) * 100, 2) AS reply_rate_pct,
  ROUND((unsub_events::numeric / NULLIF(delivered_est,0)) * 100, 2) AS unsub_rate_pct
FROM scored
ORDER BY campaign_id;

-- 4) Mailbox health snapshot (latest poll)
WITH latest AS (
  SELECT MAX(captured_at) AS max_captured_at
  FROM smartlead_mailbox_health
)
SELECT
  from_email,
  smtp_ok,
  imap_ok,
  warmup_enabled,
  message_per_day,
  daily_sent_count,
  campaign_count,
  is_connected_to_campaign,
  captured_at
FROM smartlead_mailbox_health mh
JOIN latest l ON mh.captured_at = l.max_captured_at
ORDER BY from_email;

-- 5) Scale / Hold / Pause recommendation by campaign (24h webhook windows)
-- Thresholds encoded from operating plan:
--   Red if bounce > 3.0% OR complaints >= 1 OR unsub > 1.5%
--   Hold if bounce 2.0-3.0% OR unsub 1.0-1.5% OR reply < 2.0%
--   Scale if bounce <= 2.0% AND complaints = 0 AND unsub < 1.0% AND reply >= 2.0%
WITH events AS (
  SELECT
    campaign_id,
    COUNT(*) FILTER (WHERE event_type IN ('EMAIL_SENT')) AS sent_events,
    COUNT(*) FILTER (WHERE event_type IN ('EMAIL_BOUNCED')) AS bounced_events,
    COUNT(*) FILTER (WHERE event_type IN ('EMAIL_REPLY')) AS reply_events,
    COUNT(*) FILTER (WHERE event_type IN ('LEAD_UNSUBSCRIBED')) AS unsub_events,
    COUNT(*) FILTER (WHERE event_type IN ('EMAIL_COMPLAINED','SPAM_COMPLAINT')) AS complaint_events
  FROM smartlead_webhook_events
  WHERE received_at >= NOW() - INTERVAL '24 hours'
    AND campaign_id IN (3232436, 3232437)
  GROUP BY campaign_id
), rates AS (
  SELECT
    campaign_id,
    sent_events,
    bounced_events,
    reply_events,
    unsub_events,
    complaint_events,
    GREATEST(sent_events - bounced_events, 0) AS delivered_est,
    (bounced_events::numeric / NULLIF(sent_events,0)) * 100 AS bounce_rate_pct,
    (reply_events::numeric / NULLIF(GREATEST(sent_events - bounced_events, 0),0)) * 100 AS reply_rate_pct,
    (unsub_events::numeric / NULLIF(GREATEST(sent_events - bounced_events, 0),0)) * 100 AS unsub_rate_pct
  FROM events
)
SELECT
  campaign_id,
  sent_events,
  bounced_events,
  delivered_est,
  reply_events,
  unsub_events,
  complaint_events,
  ROUND(bounce_rate_pct,2) AS bounce_rate_pct,
  ROUND(reply_rate_pct,2) AS reply_rate_pct,
  ROUND(unsub_rate_pct,2) AS unsub_rate_pct,
  CASE
    WHEN complaint_events >= 1 OR COALESCE(bounce_rate_pct,0) > 3.0 OR COALESCE(unsub_rate_pct,0) > 1.5 THEN 'PAUSE'
    WHEN (COALESCE(bounce_rate_pct,0) BETWEEN 2.0 AND 3.0)
      OR (COALESCE(unsub_rate_pct,0) BETWEEN 1.0 AND 1.5)
      OR (COALESCE(reply_rate_pct,0) < 2.0) THEN 'HOLD'
    WHEN COALESCE(bounce_rate_pct,0) <= 2.0
      AND complaint_events = 0
      AND COALESCE(unsub_rate_pct,0) < 1.0
      AND COALESCE(reply_rate_pct,0) >= 2.0 THEN 'SCALE_+25%'
    ELSE 'HOLD'
  END AS recommendation
FROM rates
ORDER BY campaign_id;

-- 6) Ingestion heartbeat checks
SELECT
  MAX(received_at) AS last_webhook_event_at,
  EXTRACT(EPOCH FROM (NOW() - MAX(received_at)))::INT AS seconds_since_last_webhook_event
FROM smartlead_webhook_events;

SELECT
  MAX(created_at) AS last_sync_run_at,
  EXTRACT(EPOCH FROM (NOW() - MAX(created_at)))::INT AS seconds_since_last_sync_run,
  (ARRAY_AGG(ok ORDER BY created_at DESC))[1] AS last_sync_ok,
  (ARRAY_AGG(details ORDER BY created_at DESC))[1] AS last_sync_details
FROM smartlead_sync_runs;
