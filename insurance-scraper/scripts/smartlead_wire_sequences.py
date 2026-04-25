import os, requests

base='https://server.smartlead.ai/api/v1'
key=os.environ['SMARTLEAD_API_KEY']


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
 'subject':'Congrats on your {{state}} insurance license!',
 'email_body':"""Hi {{first_name}},

I noticed you recently got your insurance license in {{state}} — congrats! That's a big step.

I've been in this industry for years and I remember how overwhelming those first few weeks can be. Everyone's telling you to join their agency, buy leads, and start dialing.

Here's what I wish someone told me on day one:

The carrier you choose matters more than your work ethic. I've seen equally talented agents make $40K and $200K — the only difference was their commission structure and support system.

I put together a quick guide on 'The 5 Things Every New Agent Needs to Know' — happy to send it your way if you're interested.

Either way, welcome to the business. It's a great career if you set it up right.

David Price""",
 'seq_delay_details': {'delay_in_days':0}
},
{
 'seq_number':2,
 'subject':'The carrier decision most new agents get wrong',
 'email_body':"""Hi {{first_name}},

Following up on my last note. One thing I see new agents do all the time — they sign with the first carrier that recruits them without understanding what they're giving up.

Here's what to compare before you commit:

• Commission level — anything below 80% on first-year premiums is leaving money on the table
• Lead support — do THEY provide leads, or do YOU pay for them?
• Training — not product training (every carrier does that) — sales training and mentorship
• Contract terms — are you locked in? Can you move carriers freely?
• Vesting — do you own your book of business on day one?

Most captive agencies fail on 3 or more of these. Independent agencies built for agents typically nail all 5.

Worth knowing before you sign anything.

David Price""",
 'seq_delay_details': {'delay_in_days':2}
},
{
 'seq_number':3,
 'subject':'How a new agent wrote $50K AP in their first year',
 'email_body':"""Hi {{first_name}},

Quick story about an agent who started where you are right now.

She got her license, had zero experience, and wasn't sure which direction to go. She almost signed with a well-known captive carrier because they were the first to call.

Instead, she did her homework. She found an independent agency that:
— Paid 100%+ first-year commissions
— Provided 15+ warm leads per week at no cost
— Assigned her a mentor who'd been in the business 20 years
— Let her own her book from day one

Her first year: $52,000 in annual premium. Her income: over $80,000.

The agent at the captive carrier who got licensed the same week? She quit after 6 months. Not because she wasn't good — the math just didn't work at 40% commissions with $500/month in lead costs.

Same talent. Different environment. Completely different outcome.

If you want to know what to look for in your first agency, I'm happy to share what I've learned.

David Price""",
 'seq_delay_details': {'delay_in_days':5}
},
{
 'seq_number':4,
 'subject':'Free training this week for new life agents',
 'email_body':"""Hi {{first_name}},

I run a community of life insurance agents across the country. We do weekly trainings, share what's working, and help each other grow.

This week's topic: 'Your First 90 Days — The Exact Playbook Top Producers Follow'

It's free, no strings attached. We just believe that agents who are trained well sell more, and that's good for the whole industry.

If you're interested, I can send you the details.

David Price""",
 'seq_delay_details': {'delay_in_days':7}
},
{
 'seq_number':5,
 'subject':'Still looking for the right fit?',
 'email_body':"""Hi {{first_name}},

I've sent you a few emails about getting started in insurance — hopefully some of it was helpful.

I know you're probably getting pulled in a lot of directions right now. If you've already found a carrier you're happy with, that's great — ignore me and go crush it.

But if you're still figuring things out, I'd be happy to jump on a quick 10-minute call. No pitch — just honest answers about the industry from someone who's been doing this a while.

Either way, I wish you the best. This industry changes lives when you set it up right.

David Price""",
 'seq_delay_details': {'delay_in_days':10}
}
]

B=[
{
 'seq_number':1,
 'subject':'Quick question about your {{state}} book of business',
 'email_body':"""Hi {{first_name}},

I came across your information in the {{state}} insurance directory and had a quick question.

How happy are you with your current commission structure?

I ask because I talk to a lot of agents who are doing well but wonder if they could be doing better. Most don't realize how much the compensation landscape has changed in the last few years.

No agenda here — I'm genuinely curious what agents in {{state}} are experiencing right now.

David Price""",
 'seq_delay_details': {'delay_in_days':0}
},
{
 'seq_number':2,
 'subject':'The commission gap most {{state}} agents do not know about',
 'email_body':"""Hi {{first_name}},

Did you know that commission rates for life insurance agents range from 30% to 140% — for the exact same products?

That's not a typo. An agent selling a $100/month policy could earn $360/year or $1,680/year depending on their carrier and contract level.

Multiply that by 100 policies and the difference is $132,000 per year. Same effort. Same clients. Same products.

Most agents never see the other side because they don't know it exists.

I've put together a simple commission comparison tool. Want me to send it over? It takes 2 minutes and shows you exactly where you stand.

David Price""",
 'seq_delay_details': {'delay_in_days':3}
},
{
 'seq_number':3,
 'subject':'How agents in {{state}} are 3x-ing their income',
 'email_body':"""Hi {{first_name}},

I wasn't going to send another email, but I just got off the phone with an agent in {{state}} who made a change 8 months ago and I thought you might find his story interesting.

He was with a well-known carrier for 3 years. Good at sales. Working hard. Making about $65,000/year.

He switched to an independent model and kept doing the exact same thing he was already doing.

His income this year is on pace for $185,000.

What changed:
• Commission went from 55% to 110%
• Stopped paying $400/month for leads — now gets them for free
• Kept all his existing clients (portable book of business)
• Got paired with a mentor who helped him close bigger cases

He told me his only regret was not doing it sooner.

If you're curious about what's out there, I'm happy to chat. No pressure, just information.

David Price""",
 'seq_delay_details': {'delay_in_days':7}
},
{
 'seq_number':4,
 'subject':'Free training for {{state}} life agents',
 'email_body':"""Hi {{first_name}},

I run a community of life insurance agents — we do trainings, share wins, and help each other grow.

This month's training: 'Advanced Closing Techniques That Actually Work in 2026'

It's free. You don't have to change carriers, join anything, or buy anything. Good training makes good agents, regardless of where you work.

Want the details?

David Price""",
 'seq_delay_details': {'delay_in_days':10}
},
{
 'seq_number':5,
 'subject':'Last note from me, {{first_name}}',
 'email_body':"""Hi {{first_name}},

I've reached out a few times and I don't want to be that person who won't take a hint.

If you're happy where you are, I respect that 100%. Keep grinding and building your book.

But if any of what I shared made you curious — even a little — I'm here whenever you're ready. No expiration date on the offer to chat.

Either way, I wish you nothing but success.

David Price

P.S. If you ever want to compare your current comp to what's available, my door is always open. Sometimes a 15-minute conversation can change the trajectory of your career.""",
 'seq_delay_details': {'delay_in_days':14}
}
]

upsert_sequences(3232436,A)
upsert_sequences(3232437,B)
