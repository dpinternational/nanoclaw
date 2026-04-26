/**
 * Content Machine — Email Generation Engine
 *
 * Generates daily themed emails in David Price's voice using:
 * - Voice Protocol v2.0 (from 280 YouTube transcripts)
 * - 201 archived Chris emails (style/format reference)
 * - 7-day rotation from the Content Machine Blueprint
 * - TPG wins data for proof/social proof emails
 *
 * Output: ready-to-send email text + subject line options
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');

// --- 7-Day Rotation ---

export const DAILY_THEMES = {
  Monday: {
    theme: 'Mindset & Motivation',
    pillar: 'Mindset & Identity (20%)',
    description:
      'Origin story, "Never Settle" philosophy, overcoming adversity, choosing the right hard',
    instructions: `Write a motivational email anchored in a REAL personal story from David's life.
Use one of these story wells:
- Addiction recovery and rebuilding from zero
- Growing up in government housing / homeless shelters
- Going from $2K first month to $15M company
- Watching his grandfather's mechanic shop as a kid and deciding to build something
- Getting cut off by a carrier and rebuilding

Structure: Open with a bold statement or memory. Build the story with specific details. Extract one clear lesson. Close with "Never settle."
Do NOT use generic motivation. Every sentence must feel like David talking to one person.`,
  },
  Tuesday: {
    theme: 'Agent Proof & Results',
    pillar: 'Proof & Results (30%)',
    description: 'Agent wins, income screenshots, real numbers from TPG agents',
    instructions: `Write a proof email showcasing REAL agent results from TPG.
Use available wins data. If no fresh data, use established proof points:
- Shenna Michelle: $15,343 weekly
- Delaney: $12,000 single sale
- Teghan: $1,515 Trans business in one morning
- Team: $78,082 weekly volume, $6,652 single day
- Lauren: $45K, $30K, $8K months

Structure: Lead with the specific number. Tell the agent's mini-story (where they were before, what changed). Extract the lesson for the reader. Close with a soft pull — "If they can do it, why not you?"
Do NOT make it sound like a testimonial ad. Make it sound like David bragging about his people.`,
  },
  Wednesday: {
    theme: 'Education & Value',
    pillar: 'Education & Value (25%)',
    description: 'Sales training, system breakdowns, tactical insurance advice',
    instructions: `Write an educational email teaching ONE specific tactical insight.
Topics to draw from:
- Why 6-10pm is prime calling time (leads are employees, they're home after 5)
- The math: $100K / $700 avg premium = 143 policies = 2.8/week
- Lead investment strategy (don't be stingy, leads are inventory)
- Why new agents outperform experienced ones (beginner's mindset)
- The one-product focus principle (how David made millions on Final Expense)
- NEPQ selling system
- Working leads: 5 calls/day, 5 days/week, no exceptions

Structure: Open with a counterintuitive claim or question. Break down the insight with David's analogy style. Use real math or numbers. Give them one actionable takeaway. Close with "Never settle."
Use David's teaching style: progressive layering, analogies (Costco, race car, bowling bumpers), "real simple" collapse.`,
  },
  Thursday: {
    theme: 'Origin Story & Identity',
    pillar: 'Mindset & Identity (20%)',
    description: 'David\'s journey, TPG culture, "why we do this" stories',
    instructions: `Write a story-driven email from a specific moment in David's journey.
Use the 4-beat storytelling pattern:
1. Set the scene (specific details — dates, places, numbers)
2. Introduce the conflict (emotional honesty, no sugarcoating)
3. The pivot (what he did differently, framed as a choice)
4. Result + lesson extraction

Story bank:
- Getting insurance license May 2018 with zero sales experience
- First month: $2,000. First million: 36 months later (should have been 18)
- The $36K business pivot that led to $10M
- $1.6M → $3.6M → $4M stall → uncomfortable decisions → $7.5M → $15M
- Carrier cutting him off: "going from 8 figures back to zero"
- The GoFundMe for his father's funeral
- Father canceling insurance meeting, passing a week later

Make it raw and specific. Use David's oscillation pattern: "Government assistance, business owner, government assistance, business owner."`,
  },
  Friday: {
    theme: 'Recruiting Push',
    pillar: 'Direct Recruiting CTA (10%)',
    description:
      'Application pushes, opportunity framing, "what if this was you" emails',
    instructions: `Write a recruiting email that frames the TPG opportunity.
This is the ONE day per week with a direct CTA. Use David's recruiting language:
- "The salary is the bribe they pay you to not live your dreams"
- "180% of zero is definitely zero" (mentorship over comp)
- No barrier to entry — $40K in leads over 12 months = your MBA
- "You can find insurance anywhere. You can't find The Price Group."
- Average agent focus: "Will the average agent here survive?"

Structure: Open with a question or challenge that creates a knowledge gap. Paint the contrast (where they are now vs where they could be). Use social proof (team numbers, agent results). One clear CTA — book a call, DM READY, or apply.
Keep it confident, not desperate. David disqualifies, he doesn't beg.`,
  },
  Saturday: {
    theme: 'Weekly Recap',
    pillar: 'Behind The System (15%)',
    description:
      "Week in review, behind the scenes at TPG, what's happening in the business",
    instructions: `Write a behind-the-scenes email about what's happening at TPG this week.
Topics:
- Team production numbers for the week
- New agents onboarded
- Training highlights
- Business growth milestones
- Industry observations (market conditions, tariffs, etc.)

Structure: Conversational, like David giving a weekly update to a friend. "Here's what happened this week." List 2-3 highlights with real numbers. Extract one insight about what it means. Close with forward momentum — "Next week we're going to..."
Keep it shorter than other days. Saturday readers want quick hits.`,
  },
  Sunday: {
    theme: 'Inspiration & Vision',
    pillar: 'Mindset & Identity (20%)',
    description:
      'Big picture thinking, life philosophy, the "why" behind the grind',
    instructions: `Write an inspirational email about the bigger picture — why this matters beyond money.
Themes:
- Building something that outlasts you
- Freedom > salary
- "The money wasn't the fun part. It was building something."
- Generational wealth vs paycheck-to-paycheck
- Choosing the right hard
- The compound effect of small daily habits

Structure: Reflective and slightly longer than weekday emails. Open with a philosophical observation. Connect it to David's personal experience. Bring it back to the reader's situation. Close with a challenge: "What are you going to do about it?"
Sunday emails should feel like a conversation after church — thoughtful, warm, but with a push.`,
  },
} as const;

// --- Voice Protocol (email-adapted) ---

const EMAIL_VOICE_RULES = `
# David Price — Email Voice Rules
(Adapted from Voice Protocol v2.0 for email format)

## TONE
- Conversational authority — a successful friend giving you real talk, not a guru on a stage
- First person, always. "I" for stories, "you" for teaching, "we" for TPG identity.
- Raw and unpolished — should read like a voice memo, not a blog post
- Peer-to-peer, never talking down

## FORMAT
- Short paragraphs (1-3 sentences max)
- Line breaks between every thought
- No bullet points in the main body (Chris's emails never use them)
- Use ellipsis (…) for dramatic pauses
- ALL lowercase subject lines, curiosity-driven
- No images, no fancy formatting — plain text feel
- 300-500 words ideal length (Chris averages ~350)

## STRUCTURE
- Open with a bold statement, personal memory, or provocative question
- ONE core idea per email — never try to teach multiple things
- Build with short momentum sentences, then PUNCH with a one-liner
- Close with "Never settle." + "David Price" (no title, no email address in the body)
- Include unsubscribe note: "If you no longer want to hear from us, click here to unsubscribe."
- Include address: "136 4th St. N, Suite 2232, Saint Petersburg, FL, United States, 33701"

## SIGNATURE PHRASES TO USE NATURALLY
- "Think about that" — after a key insight
- "Real simple" — to collapse complexity
- "Never settle" — ALWAYS the closing line
- "I promise you" — sparingly, for conviction
- Doubled intensifiers: "really really", "super super"

## WHAT TO AVOID IN EMAIL
- "Right?" (verbal tic — works on video, weird in email)
- "Guys" (too casual for broadcast email)
- "So" as sentence starter (use sparingly in email vs video)
- Generic motivational platitudes ("rise and grind", "manifest")
- Complex jargon ("synergy", "leverage", "optimize your funnel")
- Aggressive CTAs ("Click NOW", "Limited time")
- Rounding numbers up — always exact or round DOWN
- Emojis (Chris's emails use zero emojis)
- HTML formatting — these read as plain text

## SUBJECT LINE RULES
- All lowercase
- 2-7 words
- Create a knowledge gap or curiosity
- Questions work well
- Use numbers or dollar amounts when relevant
- Personal/conversational tone
- Examples from Chris's best performers:
  "Private invitation" (44.5% open)
  "the million dollar question" (40.7% open)
  "when is the 'perfect time'" (41.9% open)
  "What if this was you?" (41.7% open)
  "if I woke up tomorrow with nothing…" (41.6% open)
`;

// --- Email generation ---

export interface GeneratedEmail {
  dayOfWeek: string;
  theme: string;
  subject: string;
  subjectAlternatives: string[];
  body: string;
  generatedAt: string;
}

export function getDayTheme(
  dayOfWeek?: string,
): (typeof DAILY_THEMES)[keyof typeof DAILY_THEMES] & { day: string } {
  const days = [
    'Sunday',
    'Monday',
    'Tuesday',
    'Wednesday',
    'Thursday',
    'Friday',
    'Saturday',
  ];
  const day = dayOfWeek || days[new Date().getDay()];
  const theme = DAILY_THEMES[day as keyof typeof DAILY_THEMES];
  return { ...theme, day };
}

export function buildPrompt(
  dayOfWeek?: string,
  tpgWins?: string,
  additionalContext?: string,
): string {
  const { day, theme, pillar, description, instructions } =
    getDayTheme(dayOfWeek);

  // Load a few sample Chris emails for style reference
  let sampleEmails = '';
  try {
    const archivePath = path.join(
      PROJECT_ROOT,
      'store',
      'cr-email-archive.json',
    );
    if (fs.existsSync(archivePath)) {
      const archive = JSON.parse(fs.readFileSync(archivePath, 'utf-8'));
      // Pick 3 of Chris's best emails (skip webinar promos, pick story/value emails)
      const goodEmails = archive
        .filter(
          (e: any) =>
            e.body.length > 500 &&
            !e.subject.toLowerCase().includes('live') &&
            !e.subject.toLowerCase().includes('hour') &&
            !e.subject.toLowerCase().includes('seat') &&
            !e.subject.toLowerCase().includes('meeting'),
        )
        .slice(0, 3);

      if (goodEmails.length > 0) {
        sampleEmails = `\n## REFERENCE: Chris's emails (match this style and length)\n\n`;
        for (const e of goodEmails) {
          sampleEmails += `Subject: ${e.subject}\n${e.body.slice(0, 800)}\n\n---\n\n`;
        }
      }
    }
  } catch {}

  const prompt = `You are David Price. Write today's email for the daily broadcast.

## TODAY'S ASSIGNMENT
- Day: ${day}
- Theme: ${theme}
- Content Pillar: ${pillar}
- Description: ${description}

## SPECIFIC INSTRUCTIONS FOR TODAY
${instructions}

## VOICE & FORMAT RULES
${EMAIL_VOICE_RULES}
${sampleEmails}
${tpgWins ? `## FRESH TPG WINS DATA (use if today is Tuesday/Saturday)\n${tpgWins}\n` : ''}
${additionalContext ? `## ADDITIONAL CONTEXT\n${additionalContext}\n` : ''}

## OUTPUT FORMAT
Return EXACTLY this format:

SUBJECT: [your subject line, all lowercase]
ALT_SUBJECT_1: [alternative subject line]
ALT_SUBJECT_2: [alternative subject line]

BODY:
[full email text — no HTML, no markdown formatting, plain text only]

Never settle.

David Price

If you no longer want to hear from us, click here to unsubscribe.
136 4th St. N, Suite 2232, Saint Petersburg, FL, United States, 33701
`;

  return prompt;
}

export function parseGeneratedEmail(
  output: string,
  dayOfWeek?: string,
): GeneratedEmail {
  const { day, theme } = getDayTheme(dayOfWeek);

  const subjectMatch = output.match(/SUBJECT:\s*(.+)/i);
  const alt1Match = output.match(/ALT_SUBJECT_1:\s*(.+)/i);
  const alt2Match = output.match(/ALT_SUBJECT_2:\s*(.+)/i);
  const bodyMatch = output.match(/BODY:\s*\n([\s\S]+)/i);

  return {
    dayOfWeek: day,
    theme,
    subject: subjectMatch?.[1]?.trim() || 'untitled',
    subjectAlternatives: [
      alt1Match?.[1]?.trim(),
      alt2Match?.[1]?.trim(),
    ].filter(Boolean) as string[],
    body: bodyMatch?.[1]?.trim() || output,
    generatedAt: new Date().toISOString(),
  };
}

// --- CLI runner ---

async function main() {
  const dayArg = process.argv[2]; // Optional: Monday, Tuesday, etc.
  const day =
    dayArg ||
    [
      'Sunday',
      'Monday',
      'Tuesday',
      'Wednesday',
      'Thursday',
      'Friday',
      'Saturday',
    ][new Date().getDay()];

  console.log(`\n=== Email Generator — ${day} ===\n`);

  const { theme, instructions } = getDayTheme(day);
  console.log(`Theme: ${theme}\n`);

  const prompt = buildPrompt(day);

  // Save the prompt for use with Claude
  const promptPath = path.join(PROJECT_ROOT, 'store', 'email-prompt-today.txt');
  fs.writeFileSync(promptPath, prompt);
  console.log(`Prompt saved to ${promptPath}`);
  console.log(`Length: ${prompt.length} chars\n`);

  // Also save as a container-ready task
  const taskPrompt = `Generate today's daily email for the Content Machine.

${prompt}

After generating, save the output to /workspace/group/email-drafts/${new Date().toISOString().slice(0, 10)}-${day.toLowerCase()}.txt`;

  const taskPath = path.join(PROJECT_ROOT, 'store', 'email-task-today.txt');
  fs.writeFileSync(taskPath, taskPrompt);
  console.log(`Container task prompt saved to ${taskPath}`);

  // Print the prompt for manual use
  console.log(`\n--- PROMPT PREVIEW (first 1000 chars) ---\n`);
  console.log(prompt.slice(0, 1000));
  console.log(`\n... (${prompt.length} total chars)\n`);
}

const isMain =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(__filename);
if (isMain) {
  main().catch((err) => {
    console.error('Error:', err);
    process.exit(1);
  });
}
