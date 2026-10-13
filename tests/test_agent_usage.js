"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  normalize,
  createTracker,
} = require("../agent_console/static/usage.js");

function event(id, kind, usage, run_id = "run-a", extra = {}) {
  return { id, run_id, kind, data: { usage, round: 1 }, ...extra };
}

test("provider totals count cache and reasoning only as subsets", () => {
  const tracker = createTracker();
  tracker.add(event("q", "model.request"));
  tracker.add(
    event("a", "model.response", {
      prompt_tokens: 1000,
      completion_tokens: 120,
      total_tokens: 1120,
      prompt_cache_hit_tokens: 800,
      prompt_cache_miss_tokens: 200,
      completion_tokens_details: { reasoning_tokens: 90 },
    }),
  );
  const s = tracker.summary();
  assert.equal(s.total, 1120);
  assert.equal(s.input, 1000);
  assert.equal(s.output, 120);
  assert.equal(s.cacheHit, 800);
  assert.equal(s.cacheMiss, 200);
  assert.equal(s.reasoning, 90);
  assert.equal(s.partial, false);
});

test("main loop, role generation and background runs share session accounting", () => {
  const tracker = createTracker();
  for (const [id, prefix, run, input, output] of [
    ["main", "", "run-a", 100, 20],
    ["role", "roleplay.", "run-a", 200, 40],
    ["background", "", "run-b", 300, 60],
  ]) {
    tracker.add(event(id + "-q", prefix + "model.request", undefined, run));
    tracker.add(
      event(
        id + "-a",
        prefix + "model.response",
        {
          prompt_tokens: input,
          completion_tokens: output,
        },
        run,
      ),
    );
  }
  assert.equal(tracker.summary().total, 720);
  assert.equal(tracker.summary().requests, 3);
  assert.equal(tracker.summary("run-a").total, 360);
  assert.equal(tracker.summary("run-a").breakdown[1].source, "角色生成");
  assert.equal(tracker.summary("run-b").total, 360);
});

test("SSE replay cannot double count persisted request or response IDs", () => {
  const tracker = createTracker();
  const events = [
    event("q", "model.request"),
    event("a", "model.response", {
      prompt_tokens: 100,
      completion_tokens: 10,
      total_tokens: 110,
    }),
  ];
  events.forEach((e) => assert.equal(tracker.add(e), true));
  events
    .map((e) => JSON.parse(JSON.stringify(e)))
    .forEach((e) => assert.equal(tracker.add(e), false));
  assert.equal(tracker.summary().requests, 1);
  assert.equal(tracker.summary().responses, 1);
  assert.equal(tracker.summary().total, 110);
});

test("stream chunks and tool usage are excluded even when they repeat usage", () => {
  const tracker = createTracker();
  const usage = {
    prompt_tokens: 100,
    completion_tokens: 10,
    total_tokens: 110,
  };
  for (const kind of ["model.delta", "tool.result", "web_search", "run.end"]) {
    assert.equal(tracker.add(event(kind, kind, usage)), false);
  }
  assert.equal(
    tracker.add(
      event("transient", "model.response", usage, "run-a", { transient: true }),
    ),
    false,
  );
  assert.equal(tracker.summary().total, 0);
  tracker.add(event("response", "model.response", usage));
  assert.equal(tracker.summary().requests, 1);
  assert.equal(tracker.summary().total, 110);
});

test("zero, pending, missing usage and partial results remain distinguishable", () => {
  const tracker = createTracker();
  assert.equal(tracker.summary().total, 0);
  tracker.add(event("q1", "model.request"));
  assert.equal(tracker.summary().total, null);
  assert.equal(tracker.summary().pending, 1);
  tracker.add(event("a1", "model.response", {}));
  assert.equal(tracker.summary().missing, 1);
  assert.equal(tracker.summary().pending, 0);
  assert.equal(tracker.summary().total, null);
  tracker.add(event("q2", "model.request"));
  tracker.add(
    event("a2", "model.response", {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
    }),
  );
  const partial = tracker.summary();
  assert.equal(partial.total, 0);
  assert.equal(partial.known.total, 1);
  assert.equal(partial.partial, true);
  tracker.add(event("failed-request", "model.request"));
  tracker.add(event("failed-end", "run.end"));
  assert.equal(tracker.summary().pending, 1);
});

test("alternate usage fields retain provider totals and detailed token subsets", () => {
  assert.deepEqual(
    normalize({
      input_tokens: "100",
      output_tokens: 20,
      input_tokens_details: { cached_tokens: 60 },
      output_tokens_details: { reasoning_tokens: 10 },
    }),
    {
      input: 100,
      output: 20,
      total: 120,
      cacheHit: 60,
      cacheMiss: 40,
      reasoning: 10,
    },
  );
  assert.equal(normalize({ input_tokens: 100, total_tokens: 120 }).total, 120);
  assert.equal(normalize({ input_tokens: 100 }).total, null);
  assert.equal(
    normalize({ input_tokens: 100, prompt_cache_hit_tokens: 200 }).cacheMiss,
    null,
  );
});

test("cache rate is weighted by input tokens with known cache usage", () => {
  const tracker = createTracker();
  tracker.add(
    event("a", "model.response", {
      prompt_tokens: 100,
      completion_tokens: 1,
      prompt_cache_hit_tokens: 90,
    }),
  );
  tracker.add(
    event("b", "model.response", {
      prompt_tokens: 900,
      completion_tokens: 1,
      prompt_cache_hit_tokens: 90,
    }),
  );
  tracker.add(
    event("c", "model.response", { prompt_tokens: 1000, completion_tokens: 1 }),
  );
  assert.equal(tracker.summary().cacheRate, 0.18);
  assert.equal(tracker.summary().known.cacheHit, 2);
  assert.equal(tracker.summary().requests, 3);
});

test("malformed usage cannot produce NaN or fictitious zero counts", () => {
  for (const invalid of [null, true, -1, 1.5, "invalid", Infinity]) {
    assert.equal(normalize({ prompt_tokens: invalid }).input, null);
  }
  assert.equal(normalize(null).total, null);
  assert.equal(normalize({ prompt_tokens: false, input_tokens: 10 }).input, 10);
});
