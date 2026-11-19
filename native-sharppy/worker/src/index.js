const OWNER = "nwsmatthewclay";
const REPO = "BTV-Mesoscale-Detective";
const BRANCH = "main";
const CATALOG_URL = `https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}/mesoscale/data/bufkit/catalog.json`;
const DATA_ROOT = `https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}/mesoscale/data/bufkit/`;

function response(body, status = 200, extra = {}) {
  return new Response(body, {
    status,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Cache-Control": status === 200 ? "public, max-age=300, s-maxage=900" : "no-store",
      "Content-Type": "text/plain; charset=utf-8",
      ...extra,
    },
  });
}

function parseRequest(pathname) {
  const match = pathname.match(/^\/bufkit\/(RRFS|GFS|RAP|HRRR)\/(\d{6})(\d{2})Z_([a-z0-9]+)\.buf$/i);
  if (!match) return null;
  const [, model, yymmdd, hh, station] = match;
  const yy = Number(yymmdd.slice(0, 2));
  const year = yy >= 70 ? 1900 + yy : 2000 + yy;
  const month = yymmdd.slice(2, 4);
  const day = yymmdd.slice(4, 6);
  if (+month < 1 || +month > 12 || +day < 1 || +day > 31 || +hh > 23) return null;
  return {
    model: model.toUpperCase(),
    cycleKey: `${year}${month}${day}_${hh}0000`,
    station: station.toLowerCase(),
  };
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return response(null, 204);
    if (request.method !== "GET" && request.method !== "HEAD") return response("Method not allowed", 405);
    if (url.pathname === "/health") {
      return new Response(JSON.stringify({ ok: true, service: "BTV native SHARPpy BUFKIT adapter", models: ["RRFS", "GFS", "RAP", "HRRR"] }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
      });
    }
    const requested = parseRequest(url.pathname);
    if (!requested) return response("Expected /bufkit/{MODEL}/{YYMMDD}{HH}Z_{srcid}.buf", 400);

    const catalogResponse = await fetch(CATALOG_URL, { cf: { cacheTtl: 300, cacheEverything: true } });
    if (!catalogResponse.ok) return response("BUFKIT catalog unavailable", 502);
    const catalog = await catalogResponse.json();
    const cycles = catalog.models?.[requested.model] || [];
    const cycle = cycles.find(item => item.cycle_key === requested.cycleKey);
    if (!cycle) return response(`No archived ${requested.model} cycle ${requested.cycleKey}`, 404);

    const station = cycle.stations?.find(item => item.station.toLowerCase() === requested.station);
    if (!station) return response(`Station ${requested.station.toUpperCase()} is not archived for ${requested.model} ${requested.cycleKey}`, 404);

    const upstream = await fetch(DATA_ROOT + station.file, { cf: { cacheTtl: 900, cacheEverything: true } });
    if (!upstream.ok || !upstream.body) return response("Archived BUFKIT file unavailable", 502);
    let body;
    try {
      body = upstream.body.pipeThrough(new DecompressionStream("gzip"));
    } catch {
      return response("Unable to decompress archived BUFKIT file", 502);
    }
    if (request.method === "HEAD") return new Response(null, { status: 200, headers: {
      "Access-Control-Allow-Origin": "*",
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=300, s-maxage=900",
    }});
    return new Response(body, {
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "public, max-age=300, s-maxage=900",
        "X-BTV-Model": requested.model,
        "X-BTV-Cycle": requested.cycleKey,
        "X-BTV-Station": requested.station.toUpperCase(),
      },
    });
  },
};
