// vercel-site/api/submit.js — Vercel serverless function.
// Receives an employer role submission, validates it, and stores it in the
// Supabase `job_submissions` table (status 'pending') for manual review.
module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'Method not allowed' });
    return;
  }
  const { SUPABASE_URL, SUPABASE_SECRET_KEY } = process.env;
  if (!SUPABASE_URL || !SUPABASE_SECRET_KEY) {
    res.status(503).json({ error: 'Submission backend is not configured yet.' });
    return;
  }
  const body = req.body || {};
  const title = String(body.title || '').trim().slice(0, 300);
  const company = String(body.company || '').trim().slice(0, 200);
  const applyUrl = String(body.apply_url || '').trim();
  if (!title || !company || !applyUrl) {
    res.status(400).json({ error: 'Job title, company, and apply URL are required.' });
    return;
  }
  let parsed;
  try { parsed = new URL(applyUrl); } catch {
    res.status(400).json({ error: 'Apply URL is not a valid URL.' });
    return;
  }
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password) {
    res.status(400).json({ error: 'Apply URL must be a plain https:// link.' });
    return;
  }
  // Best-effort verification: fetch the apply URL and record whether the role
  // actually looks live (this becomes the reviewer's auto-check note).
  let review_note = '';
  try {
    const check = await fetch(applyUrl, { method: 'GET', redirect: 'follow', signal: AbortSignal.timeout(8000) });
    if (!check.ok) {
      review_note = `Auto-check: apply URL returned HTTP ${check.status} — likely not a live role.`;
    } else {
      const text = (await check.text()).slice(0, 150000);
      const probe = title.split(/\s+/).filter(w => w.length > 3).slice(0, 3).join(' ');
      review_note = (probe && text.toLowerCase().includes(probe.toLowerCase()))
        ? `Auto-check: apply URL live (HTTP ${check.status}) and references "${probe}".`
        : `Auto-check: apply URL live (HTTP ${check.status}) but "${probe}" was not found on the page — review manually.`;
    }
  } catch {
    review_note = 'Auto-check: could not reach the apply URL — verify it exists before approving.';
  }
  const row = {
    title,
    company,
    website: String(body.website || '').trim().slice(0, 300),
    location: String(body.location || '').trim().slice(0, 200),
    apply_url: applyUrl,
    description: String(body.description || '').trim().slice(0, 4000),
    employment_type: String(body.employment_type || '').trim().slice(0, 60),
    contact_email: String(body.contact_email || '').trim().slice(0, 200),
    status: 'pending',
    review_note,
    created_at: new Date().toISOString(),
  };
  const resp = await fetch(`${SUPABASE_URL}/rest/v1/job_submissions`, {
    method: 'POST',
    headers: {
      apikey: SUPABASE_SECRET_KEY,
      Authorization: `Bearer ${SUPABASE_SECRET_KEY}`,
      'Content-Type': 'application/json',
      Prefer: 'return=minimal',
    },
    body: JSON.stringify(row),
  });
  if (!resp.ok) {
    res.status(502).json({ error: 'Failed to store the submission.' });
    return;
  }
  res.status(200).json({ ok: true, message: 'Thanks — your role is pending review.' });
};
