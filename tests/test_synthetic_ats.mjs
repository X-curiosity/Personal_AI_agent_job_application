import test from 'node:test';
import assert from 'node:assert/strict';
import {Readable} from 'node:stream';
import handler from './synthetic-ats/api/submit.js';

function response() {
  return {statusCode: 200, payload: null, status(code) {this.statusCode = code; return this;}, json(body) {this.payload = body; return this;}, setHeader() {}};
}
test('synthetic ATS returns a receipt without echoing candidate data', async () => {
  const req = Readable.from(['{"name":"Synthetic"}']); req.method = 'POST';
  const res = response(); await handler(req, res);
  assert.equal(res.statusCode, 200); assert.equal(res.payload.synthetic, true);
  assert.ok(res.payload.submissionId); assert.ok(res.payload.bodySha256);
  assert.equal(JSON.stringify(res.payload).includes('Synthetic'), false);
});
test('synthetic ATS rejects GET', async () => {
  const req = Readable.from([]); req.method = 'GET';
  const res = response(); await handler(req, res);
  assert.equal(res.statusCode, 405);
});
