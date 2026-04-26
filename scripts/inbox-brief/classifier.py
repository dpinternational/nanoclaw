"""
Inbox classifier — pattern library extracted from the 2026-04-17 manual triage
session where David archived 282 emails down to 0.

Three buckets:
  AUTO_CANDIDATE  — high-confidence noise (newsletters, receipts, auto-notices)
  CARRIER         — insurance carrier statements, debt notices, commissions
  NEEDS_REVIEW    — humans, $$$-mentioning, ambiguous (default if no match)

Every classification returns (bucket, confidence 0-1, reason).
"""
import re
from typing import Dict, Tuple

# === AUTO_CANDIDATE patterns (David confirmed archivable) ===
AUTO_FROM = [
    # Shipping / receipts
    r'^Blueprint Bryan Johnson', r'^Blueprint <hello@bryanjohnson',
    r'support@bryanjohnson', r'@shopkanso', r'cozyearth',
    r'orders@orders\.apple', r'OnlineResearch@insideapple',
    r'shipping_notification@orders\.apple',
    r'DesignWithinReach', r'design-within-reach',
    # Newsletters
    r'haro@helpareporter', r'forbes@email', r'dailydozen@email',
    r'grailzee', r'brutestrength', r'clickfunnels',
    r'no-reply@email\.claude', r'noreply@lovable',
    r'hello@mail\.wispr', r'atlassian', r'bigscoots',
    r'@mail\.airtable', r'@mail\.notion', r'@mail\.instabrain',
    r'hello@gamma\.app', r'updates@info\.iproyal',
    r'marketing@', r'MedicareBrokerNews@',
    r'aetna.*medicare', r'AetnaSeniorSupp', r'heartland',
    r'sales@bigscoots', r'^Wispr Flow',
    r'Adzviser', r'XCEL@research',
    r'hello@samedayawards', r'Royal Neighbors',
    r'American National.*Annuity', r'noreply@ema.*anico',
    # Corporate marketing
    r'americanexpress@member', r'Card Services.*info6\.citi',
    r'marriottbonvoy', r'AA.*Advantage', r'american.*airlines',
    r'att@message\.att', r't-mobile.*mktg',
    r'Agent Pipeline.*info@agentpipeline', r'info@agentpipeline',
    r'Wellcare.*Sales',
    # Best Buy / retail marketing
    r'My Best Buy', r'citicards', r'comenityservicing',
    # Agent tool promos
    r'Agent CRM', r'GoHighLevel', r'gohighlevel',
    # Recurring SaaS invoices (you review monthly not daily)
    r'PriceLabs Support', r'PriceLabs.*invoice',
    # (note: pipedream workflow ERRORS are actionable - do NOT auto-archive)
    # Mail infra
    r'^Mail Delivery Subsystem', r'mailer-daemon',
    # Social
    r'noreply@business\.facebook', r'unread-messages@mail\.instagram',
    r'^Facebook\b', r'@mail\.instagram',
    # Skool / community (digest format)
    r'noreply@skool', r'We Are Insurance Agents.*Skool',
    r'Imperium Academy.*Skool', r'The Lean Content Engine.*Skool',
    # Calendar / Google infra (own actions)
    r'no-reply@accounts\.google', r'calendar-notification',
    r'Google Workspace Team', r'workspace-nor',
    # Venmo/payment receipts (informational, you already know)
    r'@venmo\.com', r'NoReply@payoneer',
    # Vendor receipts (subscriptions auto-charged)
    r'support@buzzsprout', r'Nextiva Billing',
    r'donotreply@vertafore', r'^Vertafore\b',
    r'support@trulyinbox', r'@tm\.openai\.com',
    r'^Ascend Learning', r'info@notificatio.*ascend',
    r'^Gu from Adzviser', r'saleshandy\.com',
    # Condo / bills (not immediately actionable; you pay on schedule)
    r'utilities@leegov', r'UtilityBilling@capecoral',
    r'donotreply@icon\.management', r'Consejo de Titulares',
    r'vsanchez@icon', r'buildinglink',
    # Zoom reauth / tool maintenance
    r'notification@zoom\.us',
    # ClickFunnels / marketing gurus
    r'^Todd Dickerson', r'noreply@clickfunnels',
    r'^Dan Henry.*getclients',  # promos
    # Hospitable / email tool ops
    r'chris@yourhospitable',
    # Google sheet share (FYI only, file linked not needed in inbox)
    r'drive-shares-dm-noreply', r'via Google Sheets',
    r'via Otter\.ai', r'Katie Canning.*otter',
    # Forbes council
    r'Forbes Business Council', r'Experiences Team, Forbes',
    # Cold pitches / low-relevance
    r'tlkfusion', r'themarketerstoolkit',
    r'interchangeauditgroup', r'iag marketing',
    # VA / Healthcare infra (FYI, no action)
    r'veteranshealth', r'Department of Veterans',
    # Vacation / resort marketing
    r'vailresort', r'HeavenlyMountain',
]

AUTO_SUBJECT = [
    r'HARO Queries for',
    r'Your.*[Oo]rder.*(delivered|out for delivery|shipped|processing|confirmed)',
    r'A shipment from order',
    r'Your.*Invoice', r'Your.*Receipt', r'Your .* Bill', r'receipt from',
    r'^Reminder: From.*Passive Cameras',  # zoom auto-reminders
    r'^Security alert for',  # google auto
    r'Your Google Account was recovered',
    r'new notifications? since',  # skool digests
    r'Posted ".*YouTube Video',
    r'Just for you: Earn',  # AA
    r'You.?ve Renewed.*Elite Status',  # marriott
    r'Ready for more flexibility',  # amex
    r'Daily Agenda for',  # google calendar
    r'new life for old work',  # forbes
    r'What Emma Lawson fixed',  # brute
    r'What.?s new for your org',  # claude team
    r'Your credits now go 2x',  # lovable
    r'Surprise! Bonus skiing',
    r'We noticed you checking',  # cozy earth
    r'Stay Compliant.*CMS',  # agent pipeline
    r'How was your purchase experience',  # apple survey
    r'Try Flow on your computer',  # wispr
    r'Transaction failed',  # failed subscription
    r'auto-renewal information',  # namecheap / update domain
    r'Update your domain contact',
    r'Medicarians Recap',  # training newsletter
    r'^Annual.*Insurance.*Campaign',  # marketing
    r'longevity active supports',  # blueprint
    r'Beyond the Server:',  # bigscoots
    r'Your Final Expense Coverage Just Got Better',  # instabrain platform
    r'Daily Automation Inspiration',  # self-sent noise
    r'Accepted:.*(past meeting)',  # calendar acceptances
    r'Canceled event',  # calendar cancels
    r'Spreadsheet shared with you',  # drive share — most are FYI
    r'A new passkey was added',  # openai security
]

# === CARRIER patterns (own bucket, separate review) ===
CARRIER_FROM = [
    r'AETSSIDebtManagement@aetna',
    r'NoReplyCompensation@mutualofomaha',
    r'debtrecovery@mutualofomaha',
    r'noreply@americo\.com',
    r'noreply@email\.transamerica',
    r'^Ethos Agents Team', r'agents@ethoslife',
    r'Agent from Ethos Technologies.*Routable',
    r'shafpcrnewbusiness', r'AFP CR New Business',
    r'Premium Accounting Dept', r'Premium and Disbursements',
    r'shlppremiumand', r'AMERICAN AMICABLE Policy Service',
    r'Americo Daily Update', r'integrityconnect\.com',
    r'Corebridge Financial.*American General',
    r'MassMutual.*electroniccommun',
    r'webmaster@aetna', r'commissions@ihlic',
    r'dmorgan@ihlic',  # auto weekly production reports
    r'@ins-portal\.com',  # auto service notifications
    r'CICA LIFE.*MarketingNotif',
    r'Agent\.Administration@equitrust',
    r'Transamerica Life Insurance Co',
    r'American Amicable Life.*Notification',
    r'AML Notification',
    r'Collections.*NoReply',
    r'debt.*collection',
    r'@aatx\.com',                       # American Amicable automated notifications
    r'American Amicable Life Ins',
]
CARRIER_SUBJECT = [
    r'^\d+ Day Debt Notice',
    r'Debt Alert',
    r'Debit Balance',
    r'Commission Statement',
    r'Express Pay Commission',
    r'Payment of \$[\d,]+\.\d+',  # ethos payment txn
    r'Daily Update',  # americo daily
    r'Policyholder Correspondence',
    r'Returned Payment',
    r'Premium Reversal',
    r'ZSecure:.*Transamerica',
    r'New resources for your clients',
    r'Tl .* weekly production report',
    r'Fb .* weekly production report',
    r'Debt Recovery Final Notification',
]

# === NEEDS_REVIEW heuristics (boosts to user-attention) ===
IMPORTANT_PROPERTY_INDICATORS = [
    r'le\s*parc',
    r'@icon\.management',
    r'ismynest\.com',
]

HUMAN_INDICATORS = [
    r'^Gina Soriano',
    r'gina@tpglife', r'gina@thepricegroup',
    r'@cenegenics', r'joe@7thlevel',
    r'continuumlg', r'liniado',
    r'@grifinsurance', r'@youradvgroup', r'@getethos\.com',
    r'@thedeninsurance', r'@premiersmi\.com', r'medinillainsurance',
    r'@airshib', r'andrew\.deng@airship',  # Andy Deng personally
    r'@oldfltitle',
]
DOLLAR_RE = re.compile(r'\$[1-9][\d,]{3,}(?:\.\d{2})?')  # >$1000

# For preview extraction (any dollar amount, not just large)
DOLLAR_ANY_RE = re.compile(r'-?\$[\d,]+(?:\.\d{2})?')
# Negative / balance / debt indicators
NEG_BALANCE_RE = re.compile(r'(?:balance\s+due|debit\s+balance|negative\s+balance|debt\s+due|amount\s+past\s+due|returned\s+for)[^\n]{0,60}-?\$[\d,]+(?:\.\d{2})?', re.I)
# Commission / payment amount markers
PAYMENT_RE = re.compile(r'(?:total\s+commission|total\s+payment|payment\s+of|commission\s+amount|net\s+pay|amount|disbursement[^\n]{0,40}is)[^\n]{0,30}\$[\d,]+(?:\.\d{2})?', re.I)

# Agent-name extraction patterns
AGENT_NAME_PATTERNS = [
    # "NAME NAME DEBIT BALANCE" (Americo collections)
    re.compile(r'(?:Subject:\s*)?([A-Z][A-Z]+\s+[A-Z][A-Z]+(?:\s+[A-Z])?)\s+(?:DEBIT BALANCE|BALANCE|INDEBTEDNESS)', re.I),
    # "Dear NAME NAME,"  (Aetna debt notices)
    re.compile(r'Dear\s+([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*,', re.I),
    # "NAME NAME's indebtedness"
    re.compile(r"([A-Z][a-zA-Z']+\s+[A-Z][a-zA-Z']+)(?:\'s|\u2019s)\s+indebtedness", re.I),
    # Subject: "Returned Payment - NAME NAME 12345..." or "AML Notification- NAME NAME 1234567"
    re.compile(r'(?:Returned Payment|AML Notification|Debt Alert|Debt\s+Notice)\s*[-:]\s*([A-Z][A-Z\s]+?)\s+\d{4,}', re.I),
    # Subject: "Debt Alert NAME NAME #1234567" or similar
    re.compile(r'(?:Debt Alert|Debit Balance Administration)\s*[-:]?\s*([A-Z][A-Z\s]+?)\s*#', re.I),
]

def extract_agent_name(msg: Dict) -> str:
    """Pull agent name from carrier/debt emails. Empty string if none."""
    subj = msg.get("subject") or ""
    body = msg.get("snippet") or ""
    haystacks = [subj, body]
    for hay in haystacks:
        for pat in AGENT_NAME_PATTERNS:
            m = pat.search(hay)
            if m:
                name = m.group(1).strip()
                # Title-case if it's ALL CAPS
                if name.isupper():
                    name = name.title()
                # Skip if it's a company-ish noise
                if re.search(r'\b(insurance|agency|llc|inc|policy|service|company|corp)\b', name, re.I):
                    continue
                return name
    return ""

def extract_money_hint(msg: Dict) -> str:
    """Pull the most relevant dollar amount (for preview). Empty string if none."""
    hay = " ".join([
        (msg.get("subject") or ""),
        (msg.get("snippet") or ""),
    ])
    # Priority 1: explicit balance-due / returned / past-due phrase
    m = NEG_BALANCE_RE.search(hay)
    if m:
        return _clean_amount(m.group(0))
    # Priority 2: explicit payment/commission phrase — extract JUST the amount
    m = PAYMENT_RE.search(hay)
    if m:
        return _clean_amount(m.group(0))
    # Priority 3: subject already has $ amount
    subj = msg.get("subject") or ""
    m = DOLLAR_ANY_RE.search(subj)
    if m:
        return _clean_amount(m.group(0))
    # Priority 4: snippet has a large $ amount
    snip = msg.get("snippet") or ""
    m = DOLLAR_RE.search(snip)
    if m:
        return _clean_amount(m.group(0))
    # Priority 5: any $ amount in snippet
    m = DOLLAR_ANY_RE.search(snip)
    if m:
        return _clean_amount(m.group(0))
    return ""


def _clean_amount(s: str) -> str:
    """From a matched chunk, pull out just the $X,XXX.XX (with optional minus)."""
    m = re.search(r'-?\$[\d,]+(?:\.\d{2})?', s)
    return m.group(0) if m else s.strip()

def classify(msg: Dict) -> Tuple[str, float, str]:
    """
    msg: {"from": str, "subject": str, "snippet": str}
    returns (bucket, confidence, reason)
    """
    frm = (msg.get("from") or "").strip()
    subj = (msg.get("subject") or "").strip()
    snippet = (msg.get("snippet") or "").strip()
    hay = f"{frm}\n{subj}\n{snippet}"

    # Property/building override first — user flagged these as potentially important
    for pat in IMPORTANT_PROPERTY_INDICATORS:
        if re.search(pat, frm, re.I) or re.search(pat, subj, re.I) or re.search(pat, snippet, re.I):
            return ("NEEDS_REVIEW", 0.98, f"property-important:{pat}")

    # HUMAN override next — never auto-archive known humans
    for pat in HUMAN_INDICATORS:
        if re.search(pat, frm, re.I) or re.search(pat, subj, re.I):
            return ("NEEDS_REVIEW", 0.95, f"human:{pat}")

    # CARRIER match
    for pat in CARRIER_FROM:
        if re.search(pat, frm, re.I):
            return ("CARRIER", 0.9, f"carrier-from:{pat}")
    for pat in CARRIER_SUBJECT:
        if re.search(pat, subj, re.I):
            return ("CARRIER", 0.85, f"carrier-subj:{pat}")

    # AUTO candidate
    for pat in AUTO_FROM:
        if re.search(pat, frm, re.I):
            # still double-check for large $ mentions before auto-ing
            if DOLLAR_RE.search(hay):
                return ("NEEDS_REVIEW", 0.7, f"auto-from-but-big$:{pat}")
            return ("AUTO_CANDIDATE", 0.9, f"auto-from:{pat}")
    for pat in AUTO_SUBJECT:
        if re.search(pat, subj, re.I):
            if DOLLAR_RE.search(hay):
                return ("NEEDS_REVIEW", 0.7, f"auto-subj-but-big$:{pat}")
            return ("AUTO_CANDIDATE", 0.8, f"auto-subj:{pat}")

    # Fallback — needs review
    if DOLLAR_RE.search(hay):
        return ("NEEDS_REVIEW", 0.8, "has-large-$")
    return ("NEEDS_REVIEW", 0.5, "uncategorized")
