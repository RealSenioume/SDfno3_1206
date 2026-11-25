/**
 * lolping-intents — a DSH bundle that exposes LoLPing's ping intents to the agent.
 *
 * LoLPing (the desktop ping wheel) writes `intents.jsonl` whenever a slice with
 * an injected action is committed. This plugin:
 *   - registers the `lolping_intents` tool so the agent can read the latest
 *     intents (and the screenshot path for region captures);
 *   - optionally watches the file and logs new intents as they arrive.
 *
 * It never talks to the game and never injects input: it is a read-only bridge
 * on the desktop side of the cursor.
 */

import { defineTool } from "@deepseek-ai/dsh-tools";

import { intentsPath, pollNew, readIntents, summary } from "./lib/intents.js";

export const name = "lolping-intents";

/** The `tools` service must be ready before `apply` registers the tool. */
export const inject = ["tools"];

const INTENT_SCHEMA = {
  type: "object",
  additionalProperties: true,
  properties: {
    ts: { type: "string", required: true },
    sector: { type: "integer", required: true },
    name: { type: "string", required: true },
    action: { type: "string", required: true },
    x: { type: "integer", required: true },
    y: { type: "integer", required: true },
    region: { type: "array", items: { type: "integer" } },
    screenshot: { type: "string" },
    text: { type: "string" },
    score: { type: "integer" },
    mode: { type: "string" },
  },
};

const READ_OUTPUT = {
  type: "object",
  additionalProperties: false,
  properties: {
    path: { type: "string", required: true },
    count: { type: "integer", required: true },
    intents: { type: "array", required: true, items: INTENT_SCHEMA },
  },
};

function jsonOutput(schema) {
  return {
    schema,
    render: (_args, value) => [{ type: "text", text: JSON.stringify(value) }],
  };
}

export function apply(ctx, config = {}) {
  const path = intentsPath(config.intentsPath);

  ctx.tools.register(
    defineTool({
      name: "lolping_intents",
      description:
        "Read the latest LoLPing ping intents. Use this after the user pings a " +
        "slice with an injected action (for example Enemy Missing or On My Way) " +
        "or asks what the wheel just sent. Region captures carry a PNG path.",
      parameters: {
        limit: {
          type: "integer",
          description: "How many recent intents to return (1-100, default 5).",
        },
      },
      output: jsonOutput(READ_OUTPUT),
      async execute(args) {
        const intents = readIntents(path, Number(args.limit ?? 5));
        return { path, count: intents.length, intents };
      },
    }),
  );

  if (config.watch !== false) {
    ctx.effect(() => {
      let offset = 0;
      const timer = setInterval(() => {
        try {
          const result = pollNew(path, offset);
          offset = result.offset;
          for (const intent of result.intents) {
            console.log(`[lolping-intents] ${summary(intent)}`);
          }
        } catch (error) {
          console.warn("[lolping-intents] watch failed:", error);
        }
      }, 500);
      timer.unref?.();
      return () => clearInterval(timer);
    });
  }
}
