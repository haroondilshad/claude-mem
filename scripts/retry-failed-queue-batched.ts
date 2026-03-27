#!/usr/bin/env bun
/**
 * Reset a batch of failed pending_messages back to pending, truncating huge tool payloads
 * so OpenRouter is less likely to hit context / upstream limits.
 *
 * Usage:
 *   bun scripts/retry-failed-queue-batched.ts
 *   bun scripts/retry-failed-queue-batched.ts --batch 25 --max-chars 20000
 *
 * Then nudge the worker:
 *   curl -sS -X POST http://127.0.0.1:37777/api/pending-queue/process -H 'Content-Type: application/json' -d '{"sessionLimit":10}'
 */
import { Database } from 'bun:sqlite';
import { homedir } from 'os';
import { join } from 'path';

const DB_PATH = join(homedir(), '.claude-mem', 'claude-mem.db');

function arg(name: string, def: number): number {
  const i = process.argv.indexOf(name);
  if (i === -1 || !process.argv[i + 1]) return def;
  return parseInt(process.argv[i + 1], 10) || def;
}

const BATCH = arg('--batch', 25);
const MAX_CHARS = arg('--max-chars', 20_000);

const SUFFIX = '\n...[truncated by retry-failed-queue-batched for smaller OpenRouter payload]';

function truncate(s: string | null): string | null {
  if (s == null || s.length <= MAX_CHARS) return s;
  return s.slice(0, MAX_CHARS) + SUFFIX;
}

const db = new Database(DB_PATH);

const rows = db
  .query(
    `SELECT id, tool_input, tool_response FROM pending_messages WHERE status = 'failed' ORDER BY id ASC LIMIT ?`
  )
  .all(BATCH) as { id: number; tool_input: string | null; tool_response: string | null }[];

let truncated = 0;
const tx = db.transaction(() => {
  const upd = db.prepare(`
    UPDATE pending_messages
    SET tool_input = ?,
        tool_response = ?,
        status = 'pending',
        retry_count = 0,
        started_processing_at_epoch = NULL,
        completed_at_epoch = NULL,
        failed_at_epoch = NULL
    WHERE id = ?
  `);
  for (const r of rows) {
    const ti = truncate(r.tool_input);
    const tr = truncate(r.tool_response);
    if (ti !== r.tool_input || tr !== r.tool_response) truncated++;
    upd.run(ti, tr, r.id);
  }
});

tx();

console.log(
  JSON.stringify(
    {
      db: DB_PATH,
      batch: BATCH,
      maxChars: MAX_CHARS,
      resetCount: rows.length,
      truncatedPayloads: truncated,
    },
    null,
    2
  )
);
