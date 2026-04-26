import os
import subprocess
from pathlib import Path

import requests

base='https://server.smartlead.ai/api/v1'
key=os.environ['SMARTLEAD_API_KEY']
ROOT = Path(__file__).resolve().parents[1]
READY_GUARD = ROOT / 'scripts' / 'enforce_ready_senders.py'


def require_ready_senders():
    cmd = ['python3', str(READY_GUARD), '--strict-auth']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise RuntimeError('BLOCKED: ready-sender preflight failed; refusing campaign sequence changes')


def upsert_sequences(campaign_id, sequences):
    url=f'{base}/campaigns/{campaign_id}/sequences?api_key={key}'
    payload={'sequences': sequences}
    r=requests.post(url,json=payload,timeout=60)
    if r.status_code!=200:
        raise RuntimeError(f'FAILED campaign {campaign_id}: {r.status_code} {r.text[:400]}')
    g=requests.get(f'{base}/campaigns/{campaign_id}/sequences?api_key={key}',timeout=30)
    g.raise_for_status()
    got=sorted(g.json(),key=lambda x:x.get('seq_number',0))
    print('campaign',campaign_id,'sequence_count',len(got))
    for s in got:
        print(' -',s.get('seq_number'),s.get('subject'))

A=[
{
 'seq_number':1,
 'subject':'agent to agent',
 'email_body':"""{{first_name}},

You either know who I am or you don't. Either way, I'm reaching out to licensed agents one-on-one and wanted to ask you a real question before anything else.

What's the biggest thing breaking your business right now? Bad leads, weak training, captive contract, dial reluctance, something else?

Tell me and I'll send back the best thing I can on it. No pitch, no booking link.

David Price""",
 'seq_delay_details': {'delay_in_days':0}
},
{
 'seq_number':2,
 'subject':'the $4,200/month opener',
 'email_body':"""{{first_name}},

Quick story while I wait to hear back.

We had an agent in our shop writing about $3k/month in AP. Solid effort, terrible numbers. On a ride-along I heard the problem in 30 seconds.

Every call he opened with: "Hi, this is Mike with [carrier], I'm following up on the form you filled out about final expense coverage."

Dead. Before he even started.

We changed it to: "Hey, is this Carol? Hey Carol, you sent in some info about getting some affordable life insurance to cover final expenses. Did I catch you at an okay time?"

Three things changed. He confirmed the prospect, framed it as affordable instead of a sales call, and gave them an out, which actually made them stay on.

Next month he wrote $7,200 AP. Same leads, same hours, same agent. One opener.

This is the kind of thing we break down every week inside the community I'm building. More on that in a couple days.

David Price""",
 'seq_delay_details': {'delay_in_days':3}
},
{
 'seq_number':3,
 'subject':"before insurance, i was repo'ing cars",
 'email_body':"""{{first_name}},

Short story, then I'll get to why I'm telling you any of this.

Before I started The Price Group in 2018, I worked oil rigs and repossessed cars. Grew up in government housing. Didn't know one person in the insurance business. No license, no mentor, no clue.

First year as an agent I made $20k. I was broke and embarrassed.

What changed wasn't talent. It was access. I finally got into a room of agents who were actually winning, started copying what they did, started getting answers same day instead of figuring it out alone for months.

Today we've done over $100 million in production. I write a column for Forbes on what's actually working in the industry, and I've shared stages with people like Jeremy Miner.

I'm not telling you this to flex. I'm telling you because the thing that moved the needle wasn't a script or a lead source or a carrier contract. It was the room.

That's why I'm building what I'm building. Tomorrow you'll get the link.

David Price""",
 'seq_delay_details': {'delay_in_days':7}
},
{
 'seq_number':4,
 'subject':'the link i promised {{first_name}}',
 'email_body':"""{{first_name}},

Here it is: https://www.skool.com/insurance/about

It's called We Are Insurance Agents. The free tier takes 30 seconds to join, and that's the only thing I'm asking you to do.

What you get on the free side:

Unbreakable: The Mindset Blueprint
Weekly live calls with me every Monday at 3pm Eastern
Access to our Leads Ready AI platform
The community feed where producers writing FE, life, and Medicare swap what's actually working
The wins thread, ask-me-anything threads, and the room itself

If the room earns its keep, there are two paid tiers:
Premium at $39/month adds the full Never Settle Academy (40+ video modules I used to sell as a $2,000 course, filmed at Cody Askins' studio) and the NEPQ-based scripts we run in the shop (Jeremy Miner / 7th Level).
VIP at $197/month or $1,000/year adds direct DM access to me plus quarterly 1-on-1 strategy calls where we look at your business together and adjust course.

But none of that matters yet. The free tier is more than most paid communities give you. Start there.

David Price""",
 'seq_delay_details': {'delay_in_days':11}
},
{
 'seq_number':5,
 'subject':"i'll stop emailing you {{first_name}}",
 'email_body':"""{{first_name}},

Last one from me. Promise.

I'm not going to keep showing up in your inbox if it's not your moment. They're loud enough already.

If you ever want in, the free tier is here: https://www.skool.com/insurance/about

If not, I hope you write a record year. Genuinely.

David Price

PS. One thing before I go. The agents I've watched break through usually did it after they stopped trying to figure it out alone. Whenever that moment hits for you, I'll be around.""",
 'seq_delay_details': {'delay_in_days':16}
}
]

B=[
{
 'seq_number':1,
 'subject':'weird question',
 'email_body':"""{{first_name}},

If you had to bet money on which one fixes your business faster, more leads or better closing, which one are you putting the chips on?

David Price""",
 'seq_delay_details': {'delay_in_days':0}
},
{
 'seq_number':2,
 'subject':'i was wrong about this for years',
 'email_body':"""{{first_name}},

Spent the first three years of my career thinking the answer to every problem was more leads.

Wasn't.

Watched an agent in our shop close 38% on the same leads another agent was closing 11% on. Same script, same offer, same carrier. The difference was something I'm still trying to put into words.

I'll send you the closest thing I've got to an explanation in a few days.

David Price""",
 'seq_delay_details': {'delay_in_days':3}
},
{
 'seq_number':3,
 'subject':'the 38% guy',
 'email_body':"""{{first_name}},

Following up on the 38% closer I mentioned.

Took me a while to figure out what he was doing differently. It wasn't the script. It wasn't tone. It wasn't pace.

It was that he genuinely didn't care if the prospect bought.

Not in a "fake confidence" way. He actually didn't care. He'd made enough money that any one sale didn't matter, so he treated every call like he was helping a stranger figure out a problem. Prospects could feel it. They bought from him because he wasn't trying to sell them.

The hard part is, you can't fake that. You either have enough volume and enough belief in your product that you don't need any one prospect, or you don't. And if you don't, every call is going to leak the desperation no matter what script you use.

The fix isn't a better opener. The fix is enough lead flow and enough peer support that you stop needing the next sale to survive.

That's what I've been building toward for the last six years.

David Price""",
 'seq_delay_details': {'delay_in_days':7}
},
{
 'seq_number':4,
 'subject':'ok, here',
 'email_body':"""{{first_name}},

You've gotten three emails from me without an ask. Time to make one.

I'm building a community for insurance agents. It's called We Are Insurance Agents. Free tier, 30 seconds to join, link below.

What's in the free tier:

Unbreakable: The Mindset Blueprint
Weekly live calls with me every Monday at 3pm Eastern
Access to our Leads Ready AI platform
The community itself

Premium ($39/month) adds the full Never Settle Academy and the NEPQ scripts we use. VIP ($197/month or $1,000/year) adds direct DM access to me plus quarterly 1-on-1 strategy calls. But the free tier is more than most agents need to start with.

https://www.skool.com/insurance/about

David Price""",
 'seq_delay_details': {'delay_in_days':11}
},
{
 'seq_number':5,
 'subject':'closing the loop',
 'email_body':"""{{first_name}},

This is the last one. If the timing's not right, no problem. Free tier is here whenever: https://www.skool.com/insurance/about

David Price""",
 'seq_delay_details': {'delay_in_days':16}
}
]

require_ready_senders()
upsert_sequences(3232436,A)
upsert_sequences(3232437,B)
