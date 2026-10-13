"use strict";

// Only provider usage in explicit model responses is counted. Tool payloads
// and streaming chunks may contain the same data and must not be counted again.
const AgentUsage = (() => {
  const requestKinds = new Set(["model.request", "roleplay.model.request"]);
  const responseKinds = new Set(["model.response", "roleplay.model.response"]);
  const fields = [
    "input",
    "output",
    "total",
    "cacheHit",
    "cacheMiss",
    "reasoning",
  ];
  const number = (value) => {
    if (typeof value === "string" && /^\d+$/.test(value)) value = Number(value);
    return typeof value === "number" &&
      Number.isSafeInteger(value) &&
      value >= 0
      ? value
      : null;
  };
  const first = (...values) =>
    values.map(number).find((v) => v !== null) ?? null;

  function normalize(usage) {
    const u = usage && typeof usage === "object" ? usage : {};
    const input = first(u.prompt_tokens, u.input_tokens);
    const output = first(u.completion_tokens, u.output_tokens);
    const reportedTotal = number(u.total_tokens);
    const cacheHit = first(
      u.prompt_cache_hit_tokens,
      u.prompt_tokens_details?.cached_tokens,
      u.input_tokens_details?.cached_tokens,
    );
    return {
      input,
      output,
      total:
        reportedTotal ??
        (input !== null && output !== null ? input + output : null),
      cacheHit,
      cacheMiss:
        first(u.prompt_cache_miss_tokens) ??
        (input !== null && cacheHit !== null && cacheHit <= input
          ? input - cacheHit
          : null),
      reasoning: first(
        u.completion_tokens_details?.reasoning_tokens,
        u.output_tokens_details?.reasoning_tokens,
        u.reasoning_tokens,
      ),
    };
  }

  function createTracker() {
    const seen = new Set(),
      runs = new Map();
    function add(event) {
      if (event.transient) return false;
      if (!requestKinds.has(event.kind) && !responseKinds.has(event.kind))
        return false;
      if (event.id && seen.has(event.id)) return false;
      if (event.id) seen.add(event.id);
      let run = runs.get(event.run_id);
      if (!run) {
        run = { requests: 0, responses: [] };
        runs.set(event.run_id, run);
      }
      if (requestKinds.has(event.kind)) run.requests += 1;
      else
        run.responses.push({
          ...normalize(event.data?.usage),
          round: event.data?.round ?? null,
          source: event.kind.startsWith("roleplay.") ? "角色生成" : "对话",
        });
      return true;
    }
    function summary(runId) {
      const selected =
        runId === undefined
          ? [...runs.values()]
          : [runs.get(runId)].filter(Boolean);
      const requests = selected.reduce(
        (n, r) => n + Math.max(r.requests, r.responses.length),
        0,
      );
      const responses = selected.flatMap((r) => r.responses);
      const result = {
        requests,
        responses: responses.length,
        known: {},
        pending: Math.max(0, requests - responses.length),
      };
      for (const field of fields) {
        const values = responses.map((r) => r[field]).filter((v) => v !== null);
        result[field] = values.length
          ? values.reduce((a, b) => a + b, 0)
          : requests === 0
            ? 0
            : null;
        result.known[field] = values.length;
      }
      result.missing = responses.filter((r) => r.total === null).length;
      result.partial = result.known.total < requests;
      const cached = responses.filter(
        (r) => r.cacheHit !== null && r.input !== null && r.cacheHit <= r.input,
      );
      const cachedInput = cached.reduce((n, r) => n + r.input, 0);
      result.cacheRate = cachedInput
        ? cached.reduce((n, r) => n + r.cacheHit, 0) / cachedInput
        : null;
      result.breakdown = responses;
      return result;
    }
    return { add, summary };
  }
  return { normalize, createTracker };
})();
if (typeof module !== "undefined") module.exports = AgentUsage;
