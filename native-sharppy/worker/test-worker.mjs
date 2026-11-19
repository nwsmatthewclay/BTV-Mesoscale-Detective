import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import worker from "./src/index.js";

const originalFetch = globalThis.fetch;
const catalog = {
  models: {
    RRFS: [{
      cycle_key: "20261119_120000",
      stations: [{
        station: "KBTV",
        file: "archive/RRFS/20261119_120000/kbtv.buf.gz"
      }]
    }]
  }
};
globalThis.fetch = async (input) => {
  const url = String(input);
  if (url.includes("catalog.json")) {
    return new Response(JSON.stringify(catalog), { status: 200 });
  }
  if (url.endsWith("/kbtv.buf.gz")) {
    return new Response(gzipSync("BUFKIT TEST PROFILE\n"), { status: 200 });
  }
  return new Response("not found", { status: 404 });
};

try {
  const good = await worker.fetch(new Request("https://worker.test/bufkit/RRFS/26111912Z_kbtv.buf"));
  assert.equal(good.status, 200);
  assert.equal(await good.text(), "BUFKIT TEST PROFILE\n");
  assert.equal(good.headers.get("X-BTV-Model"), "RRFS");
  assert.equal(good.headers.get("X-BTV-Cycle"), "20261119_120000");

  const missing = await worker.fetch(new Request("https://worker.test/bufkit/RRFS/26111906Z_kbtv.buf"));
  assert.equal(missing.status, 404);

  const malformed = await worker.fetch(new Request("https://worker.test/not-a-bufkit-route"));
  assert.equal(malformed.status, 400);

  const health = await worker.fetch(new Request("https://worker.test/health"));
  assert.equal(health.status, 200);
  assert.equal((await health.json()).ok, true);
  console.log("PASS: Worker returns exact archived cycle data, decompresses gzip, rejects missing cycles, and reports health.");
} finally {
  globalThis.fetch = originalFetch;
}
