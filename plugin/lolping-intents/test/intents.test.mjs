import assert from "node:assert/strict";
import { appendFileSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  intentsPath,
  parseIntents,
  pollNew,
  readIntents,
  summary,
} from "../lib/intents.js";

function fixture() {
  const dir = mkdtempSync(join(tmpdir(), "lolping-intents-"));
  const file = join(dir, "intents.jsonl");
  return {
    file,
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  };
}

const SAMPLE = {
  ts: "2026-11-25T16:20:29.956+08:00",
  sector: 4,
  name: "Enemy Missing",
  action: "capture_region",
  x: 826,
  y: 237,
  region: [506, 57, 640, 360],
  screenshot: "C:/tmp/region.png",
  text: "",
  score: 0,
  mode: "image",
};

test("intentsPath honours the override and APPDATA", () => {
  assert.equal(intentsPath("C:/custom.jsonl"), "C:/custom.jsonl");
  const saved = process.env.APPDATA;
  process.env.APPDATA = "C:/Users/x/AppData/Roaming";
  try {
    assert.match(intentsPath(), /lolping-desktop[\\/]intents\.jsonl$/);
  } finally {
    if (saved === undefined) delete process.env.APPDATA;
    else process.env.APPDATA = saved;
  }
});

test("parseIntents skips malformed and empty lines", () => {
  const text = `${JSON.stringify(SAMPLE)}\n\n{broken\n`;
  const records = parseIntents(text);
  assert.equal(records.length, 1);
  assert.equal(records[0].name, "Enemy Missing");
});

test("readIntents returns the last N in order", () => {
  const { file, cleanup } = fixture();
  try {
    writeFileSync(
      file,
      [1, 2, 3].map((i) => JSON.stringify({ ...SAMPLE, sector: i })).join("\n") + "\n",
    );
    const last = readIntents(file, 2);
    assert.deepEqual(last.map((item) => item.sector), [2, 3]);
    assert.equal(readIntents(join(file, "..", "missing.jsonl"), 5).length, 0);
  } finally {
    cleanup();
  }
});

test("pollNew only returns complete appended lines", () => {
  const { file, cleanup } = fixture();
  try {
    writeFileSync(file, `${JSON.stringify(SAMPLE)}\n`);
    const first = pollNew(file, 0);
    assert.equal(first.intents.length, 1);
    assert.equal(first.reset, false);
    appendFileSync(file, `${JSON.stringify({ ...SAMPLE, sector: 7 })}\n{partial`);
    const second = pollNew(file, first.offset);
    assert.equal(second.intents.length, 1);
    assert.equal(second.intents[0].sector, 7);
    const third = pollNew(file, second.offset);
    assert.equal(third.intents.length, 0);
  } finally {
    cleanup();
  }
});

test("pollNew resets after truncation", () => {
  const { file, cleanup } = fixture();
  try {
    writeFileSync(file, `${JSON.stringify(SAMPLE)}\n`);
    const first = pollNew(file, 0);
    writeFileSync(file, "");
    const reset = pollNew(file, first.offset);
    assert.equal(reset.reset, true);
    assert.equal(reset.offset, 0);
  } finally {
    cleanup();
  }
});

test("summary renders a compact line", () => {
  assert.equal(summary(SAMPLE), "Enemy Missing · capture_region · score 0");
});
