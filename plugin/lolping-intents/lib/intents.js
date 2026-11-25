/**
 * Pure helpers for the LoLPing intent log.
 *
 * LoLPing appends one JSON line per committed ping that has an injected action:
 *
 *   {"ts":"...","sector":4,"name":"Enemy Missing","action":"capture_region",
 *    "x":826,"y":237,"region":[506,57,640,360],"screenshot":"...png", "text":"...",
 *    "score":88,"mode":"text"}
 *
 * Keeping this file free of DSH imports lets the test runner (and any tooling)
 * load it with plain Node.
 */

import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/** Default location of the log, matching lolping's `intent.intents_path()`. */
export function intentsPath(override) {
  if (override) return override;
  const appData = process.env.APPDATA;
  if (appData) return join(appData, "lolping-desktop", "intents.jsonl");
  return join(homedir(), "lolping-desktop", "intents.jsonl");
}

/** Parse the whole log, skipping malformed lines (lolping may be mid-write). */
export function parseIntents(text) {
  const records = [];
  for (const raw of String(text).split(/\r?\n/)) {
    if (!raw.trim()) continue;
    try {
      const value = JSON.parse(raw);
      if (value && typeof value === "object") records.push(value);
    } catch {
      // A partially flushed last line is expected; ignore it.
    }
  }
  return records;
}

/** Read the last `limit` intents (oldest first). */
export function readIntents(path, limit = 5) {
  if (!existsSync(path)) return [];
  const count = Math.max(1, Math.min(100, Number(limit) || 5));
  return parseIntents(readFileSync(path, "utf8")).slice(-count);
}

/**
 * Read complete lines appended after `offset` bytes.
 * Returns `{ offset, intents, reset }`; `reset` means the file shrank and the
 * caller should treat the result as a fresh read.
 */
export function pollNew(path, offset = 0) {
  if (!existsSync(path)) return { offset: 0, intents: [], reset: true };
  const text = readFileSync(path, "utf8");
  const bytes = Buffer.byteLength(text, "utf8");
  if (bytes < offset) {
    return { offset: bytes, intents: parseIntents(text), reset: true };
  }
  const appended = Buffer.from(text, "utf8").subarray(offset).toString("utf8");
  const cut = appended.lastIndexOf("\n");
  if (cut < 0) return { offset, intents: [], reset: false };
  const complete = appended.slice(0, cut + 1);
  return {
    offset: offset + Buffer.byteLength(complete, "utf8"),
    intents: parseIntents(complete),
    reset: false,
  };
}

/** Compact one-line summary used by the watcher log and tool rendering. */
export function summary(intent) {
  const name = String(intent?.name ?? "?");
  const action = String(intent?.action ?? "?");
  const score = intent?.score ?? "";
  return `${name} · ${action}${score === "" ? "" : ` · score ${score}`}`;
}
