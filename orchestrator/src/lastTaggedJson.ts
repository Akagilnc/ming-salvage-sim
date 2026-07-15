/**
 * lastTaggedJson.ts — shared last-`<tag>` body extraction for worker cargo.
 *
 * Production seats may bind Sandcastle `Output.object` for typed traffic signals;
 * ordinary role cargo still rides on stdout tags / sidecars. Every role parser
 * that reads "the last `<tag>{…}</tag>` wins" must share one body extractor so
 * CMR / merger / ship / single-slice cannot drift (indexOf + backward scan for a
 * closed span — never regex that can latch a conversational prefix).
 *
 * Callers keep their own malformed-input semantics (soft undefined vs sparse
 * cargo vs explicit error reason). This module only extracts / optionally soft-
 * parses JSON.
 */

import { stripJsonFence } from "./workerOutcomeSidecar.js";

/**
 * Body of the last well-closed `<tag>…</tag>` in `stdout`, or `undefined` when
 * no closed tag is present. Trailing unclosed opens are skipped so an earlier
 * complete block still wins.
 */
export function extractLastTagBody(
  stdout: string,
  tag: string,
): string | undefined {
  const open = `<${tag}>`;
  const close = `</${tag}>`;
  const starts: number[] = [];
  for (
    let idx = stdout.indexOf(open);
    idx !== -1;
    idx = stdout.indexOf(open, idx + open.length)
  ) {
    starts.push(idx);
  }
  if (starts.length === 0) return undefined;
  for (let i = starts.length - 1; i >= 0; i -= 1) {
    const bodyStart = starts[i]! + open.length;
    const end = stdout.indexOf(close, bodyStart);
    if (end === -1) continue;
    return stdout.slice(bodyStart, end);
  }
  return undefined;
}

/**
 * Soft-parse the last tagged JSON object/array. Missing tag or invalid JSON →
 * `undefined` (never throws). Fence-aware via {@link stripJsonFence}.
 */
export function parseLastTaggedJsonSoft(
  stdout: string,
  tag: string,
): unknown | undefined {
  const body = extractLastTagBody(stdout, tag);
  if (body === undefined) return undefined;
  try {
    return JSON.parse(stripJsonFence(body.trim()));
  } catch {
    return undefined;
  }
}
