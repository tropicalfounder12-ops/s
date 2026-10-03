// "Ask the coach": sends the last 8 weeks of sessions to Claude and returns a short review.
// Loaded by server.js only when ANTHROPIC_API_KEY is set. Needs `npm install` and Node.js 20+.
const { Anthropic } = require('@anthropic-ai/sdk');

const MODEL = 'claude-opus-5-5';
const WINDOW_DAYS = 56;

const SYSTEM = `You are a friendly, knowledgeable strength coach reviewing someone's gym log. Each line is one session: date, session type (usually a muscle group), duration, and optional notes in their own words.

Give a short review: what is going well, what is missing or overdone (muscle-group balance, how often they train, rest), and a concrete suggestion for their next session or two. Base everything on the log; when notes are thin, don't invent exercises or weights.

The answer is shown in a narrow side panel, often on a phone, as plain text: no Markdown, under 150 words.`;

const client = new Anthropic(); // reads ANTHROPIC_API_KEY

function weekday(date) {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString('en-US', { weekday: 'short', timeZone: 'UTC' });
}

// today is the browser's local date as YYYY-MM-DD.
async function review(sessions, today) {
  const since = new Date(Date.parse(today) - WINDOW_DAYS * 86400 * 1000).toISOString().slice(0, 10);
  const recent = sessions
    .filter((s) => s.date >= since && s.date <= today)
    .sort((a, b) => a.date.localeCompare(b.date));
  if (!recent.length) return `Nothing logged since ${since}. Log a few sessions and ask again.`;

  const log = recent
    .map((s) => {
      const parts = [`${s.date} ${weekday(s.date)}`, s.type, `${s.minutes} min`];
      if (s.notes) parts.push(s.notes.replace(/\s+/g, ' '));
      return parts.join(' | ');
    })
    .join('\n');

  let response;
  try {
    response = await client.beta.messages.create({
      model: MODEL,
      max_tokens: 16000,
      output_config: { effort: 'medium' },
      // If Claude's safety classifiers decline, rerun on Anthropic's recommended fallback model.
      betas: ['server-side-fallback-2026-07-01'],
      fallbacks: 'default',
      system: SYSTEM,
      messages: [{ role: 'user', content: `Today is ${today}. My log since ${since}:\n${log}` }],
    });
  } catch (err) {
    if (err instanceof Anthropic.AuthenticationError) {
      throw new Error('Claude rejected the API key. Check ANTHROPIC_API_KEY on the server.');
    }
    if (err instanceof Anthropic.RateLimitError) throw new Error('Claude is busy right now. Try again in a minute.');
    if (err instanceof Anthropic.APIError) throw new Error(`Claude API error: ${err.message}`);
    throw err;
  }

  if (response.stop_reason === 'refusal') return "The coach couldn't answer this time. Try again later.";
  return response.content
    .filter((block) => block.type === 'text')
    .map((block) => block.text)
    .join('')
    .trim();
}

module.exports = { review };
