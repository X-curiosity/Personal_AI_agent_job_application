import {createHash, randomUUID} from 'node:crypto';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({error: 'Method not allowed'});
  }
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 1024 * 1024) return res.status(413).json({error: 'Synthetic payload too large'});
    chunks.push(Buffer.from(chunk));
  }
  const body = Buffer.concat(chunks);
  // Test receipt only: never log, persist, or forward candidate data.
  return res.status(200).json({
    ok: true,
    synthetic: true,
    submissionId: randomUUID(),
    receivedBytes: body.length,
    bodySha256: createHash('sha256').update(body).digest('hex'),
  });
}
