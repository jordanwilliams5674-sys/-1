const FORBIDDEN_PATH_WORDS = new Set([
  "account",
  "accounts",
  "order",
  "orders",
  "position",
  "positions",
  "trade",
  "trading",
  "transfer",
  "withdraw",
  "deposit",
]);

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function cleanSymbols(raw) {
  const symbols = String(raw || "")
    .split(",")
    .map((item) => item.trim().toUpperCase())
    .filter((item) => /^[A-Z][A-Z0-9.]{0,9}$/.test(item));
  return Array.from(new Set(symbols)).slice(0, 50);
}

function assertReadOnlyUrl(url) {
  const parsed = new URL(url);
  const parts = parsed.pathname.split("/").filter(Boolean).map((item) => item.toLowerCase());
  const blocked = parts.filter((item) => FORBIDDEN_PATH_WORDS.has(item));
  if (blocked.length) {
    throw new Error(`Blocked non-market-data endpoint: ${blocked.join(",")}`);
  }
}

function parseAlpacaQuote(symbol, row) {
  const quote = row && row.q ? row.q : row || {};
  const bid = Number.isFinite(Number(quote.bp)) ? Number(quote.bp) : null;
  const ask = Number.isFinite(Number(quote.ap)) ? Number(quote.ap) : null;
  let price = null;
  if (bid !== null && ask !== null && bid > 0 && ask > 0) price = (bid + ask) / 2;
  else if (ask !== null) price = ask;
  else if (bid !== null) price = bid;
  return {
    symbol,
    price,
    bid,
    ask,
    bidSize: Number.isFinite(Number(quote.bs)) ? Number(quote.bs) : null,
    askSize: Number.isFinite(Number(quote.as)) ? Number(quote.as) : null,
    timestamp: quote.t || null,
    provider: "alpaca",
    source: "Alpaca Market Data latest quotes",
    quoteStatus: price === null ? "未取得" : "ok",
  };
}

async function fetchAlpacaQuotes(symbols, env) {
  if (!env.ALPACA_KEY_ID || !env.ALPACA_SECRET_KEY || !symbols.length) {
    return { providerStatus: "disabled_missing_keys", quotes: {} };
  }
  const feed = env.ALPACA_DATA_FEED || "iex";
  const url = new URL("https://data.alpaca.markets/v2/stocks/quotes/latest");
  url.searchParams.set("symbols", symbols.join(","));
  url.searchParams.set("feed", feed);
  assertReadOnlyUrl(url.toString());
  const res = await fetch(url.toString(), {
    method: "GET",
    headers: {
      accept: "application/json",
      "APCA-API-KEY-ID": env.ALPACA_KEY_ID,
      "APCA-API-SECRET-KEY": env.ALPACA_SECRET_KEY,
    },
  });
  if (!res.ok) {
    return { providerStatus: `error_${res.status}`, quotes: {} };
  }
  const data = await res.json();
  const quotes = {};
  for (const [symbol, row] of Object.entries(data.quotes || {})) {
    quotes[symbol.toUpperCase()] = parseAlpacaQuote(symbol.toUpperCase(), row);
  }
  return { providerStatus: "ok", feed, quotes };
}

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  const symbols = cleanSymbols(url.searchParams.get("symbols"));
  if (!symbols.length) {
    return jsonResponse({ ok: false, error: "symbols_required", quotes: {} }, 400);
  }
  try {
    const alpaca = await fetchAlpacaQuotes(symbols, env);
    return jsonResponse({
      ok: alpaca.providerStatus === "ok",
      mode: "read_only_market_data",
      generatedAt: new Date().toISOString(),
      requestedSymbols: symbols,
      provider: "alpaca",
      providerStatus: alpaca.providerStatus,
      feed: alpaca.feed || null,
      quotes: alpaca.quotes,
      safety: {
        noTrading: true,
        noAccountAccess: true,
        noOrderEndpoints: true,
        noBrokerLogin: true,
      },
    });
  } catch (error) {
    return jsonResponse({ ok: false, error: String(error && error.message ? error.message : error), quotes: {} }, 502);
  }
}
