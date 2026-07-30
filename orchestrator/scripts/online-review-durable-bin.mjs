#!/usr/bin/env node
/**
 * #1145 worker-callable online-review durable CLI (DecisionGate A).
 *
 * Usage (inside sandbox):
 *   node "$ORCHESTRATOR_ONLINE_REVIEW_DURABLE_PATH/bin.mjs" <cmd> ...
 *
 * Host never parses state — workers own all transitions.
 */
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const STATE_FILE = "state.jsonl";
const LOCK_FILE = "state.jsonl.lock";
const BLOBS_DIR = "blobs";

function rootFromEnv() {
  const env = process.env.ORCHESTRATOR_ONLINE_REVIEW_DURABLE_PATH?.trim();
  if (env && env.length > 0) return env;
  // When invoked as .../durable/bin.mjs, root is dirname of this file.
  return dirname(fileURLToPath(import.meta.url));
}

function die(msg, code = 1) {
  process.stderr.write(`${msg}\n`);
  process.exit(code);
}

function out(obj) {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
}

function withLock(root, fn) {
  const lockPath = join(root, LOCK_FILE);
  const started = Date.now();
  let fd;
  while (fd === undefined) {
    try {
      fd = openSync(lockPath, "wx");
    } catch (err) {
      if (err?.code !== "EEXIST") throw err;
      if (Date.now() - started > 5000) {
        die(`lock timeout: ${lockPath}`);
      }
      const until = Date.now() + 20;
      while (Date.now() < until) {
        /* spin */
      }
    }
  }
  try {
    fn();
  } finally {
    closeSync(fd);
    try {
      unlinkSync(lockPath);
    } catch {
      /* ignore */
    }
  }
}

function readEvents(root) {
  const path = join(root, STATE_FILE);
  if (!existsSync(path)) return [];
  const text = readFileSync(path, "utf8");
  const events = [];
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      const p = JSON.parse(t);
      if (p && p.v === 1 && typeof p.kind === "string") events.push(p);
    } catch {
      /* skip */
    }
  }
  return events;
}

function appendEvent(root, event) {
  withLock(root, () => {
    writeFileSync(join(root, STATE_FILE), `${JSON.stringify(event)}\n`, {
      encoding: "utf8",
      flag: "a",
    });
  });
}

function nowIso() {
  return new Date().toISOString();
}

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith("--")) {
        args[key] = next;
        i++;
      } else {
        args[key] = true;
      }
    } else {
      args._.push(a);
    }
  }
  return args;
}

function requireRound(args) {
  const n = Number(args.round);
  if (!Number.isSafeInteger(n) || n < 1) die("--round N (>=1) required");
  return n;
}

function lastProgress(events, round) {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.kind === "collection_progress" && e.round === round) return e;
  }
  return undefined;
}

function receiptsForRound(events, round) {
  const map = new Map();
  for (const e of events) {
    if (e.kind === "side_effect_receipt" && e.round === round) {
      map.set(e.idempotencyKey, e);
    }
  }
  return [...map.values()];
}

function lastReceipt(events, round, key) {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (
      e.kind === "side_effect_receipt" &&
      e.round === round &&
      e.idempotencyKey === key
    ) {
      return e;
    }
  }
  return undefined;
}

function blobAbs(root, handle) {
  const normalized = String(handle).replace(/\\/g, "/");
  if (normalized.includes("..") || !normalized.startsWith(`${BLOBS_DIR}/`)) {
    die(`invalid evidence handle: ${handle}`);
  }
  return join(root, normalized);
}

function evidenceReadable(root, handle) {
  try {
    return existsSync(blobAbs(root, handle));
  } catch {
    return false;
  }
}

function classify(root, round) {
  const events = readEvents(root);
  const progress = lastProgress(events, round);
  const receipts = receiptsForRound(events, round);
  if (!Number.isSafeInteger(round) || round < 1) {
    return {
      kind: "corrupt",
      reason: "invalid_round",
      diagnosis: `round must be >= 1`,
    };
  }
  if (progress === undefined && receipts.length === 0) {
    return { kind: "pristine" };
  }
  if (progress === undefined && receipts.length > 0) {
    return {
      kind: "corrupt",
      reason: "unpaired_receipts",
      diagnosis: `round ${round} has receipts without progress`,
    };
  }
  if (
    progress.phase !== "initialized" &&
    progress.phase !== "waiting" &&
    progress.phase !== "evidence_ready"
  ) {
    return {
      kind: "corrupt",
      reason: "invalid_progress_phase",
      diagnosis: `bad phase`,
    };
  }
  if (progress.evidenceHandle) {
    if (!String(progress.evidenceHandle).trim()) {
      return {
        kind: "corrupt",
        reason: "empty_evidence_handle",
        diagnosis: "empty handle",
      };
    }
    if (!evidenceReadable(root, progress.evidenceHandle)) {
      return {
        kind: "corrupt",
        reason: "evidence_handle_unreadable",
        diagnosis: `handle ${progress.evidenceHandle} unreadable`,
      };
    }
  }
  return {
    kind: "resume",
    progress: {
      round: progress.round,
      phase: progress.phase,
      waitDeadlineAt: progress.waitDeadlineAt,
      completedWaitEpochs: progress.completedWaitEpochs,
      evidenceHandle: progress.evidenceHandle,
      ts: progress.ts,
    },
  };
}

function decide(receipt, fact) {
  if (receipt?.state === "succeeded") return { action: "skip_already_done" };
  if (receipt === undefined || receipt.state === "failed") {
    if (fact === "applied") return { action: "skip_already_done" };
    if (fact === "unknown") {
      return {
        action: "escalate",
        reason: "side_effect_fact_unknown",
        diagnosis: "cannot determine external fact — refuse blind replay",
      };
    }
    return { action: "execute_once" };
  }
  if (fact === "applied") return { action: "skip_already_done" };
  if (fact === "not_applied") return { action: "execute_once" };
  return {
    action: "escalate",
    reason: "side_effect_attempted_unresolvable",
    diagnosis: `key=${receipt.idempotencyKey} attempted; fact unknown`,
  };
}

function main() {
  const root = rootFromEnv();
  mkdirSync(join(root, BLOBS_DIR), { recursive: true });
  const argv = process.argv.slice(2);
  const cmd = argv[0];
  if (!cmd) die("usage: bin.mjs <cmd> ...");
  const args = parseArgs(argv.slice(1));

  switch (cmd) {
    case "progress-init": {
      const round = requireRound(args);
      appendEvent(root, {
        v: 1,
        kind: "collection_progress",
        round,
        ts: nowIso(),
        phase: "initialized",
      });
      out({ ok: true, round, phase: "initialized" });
      break;
    }
    case "progress-set-deadline": {
      const round = requireRound(args);
      const deadline = String(args.deadline ?? "").trim();
      if (!deadline) die("--deadline ISO required");
      appendEvent(root, {
        v: 1,
        kind: "collection_progress",
        round,
        ts: nowIso(),
        phase: "waiting",
        waitDeadlineAt: deadline,
        completedWaitEpochs: Number(args.epochs ?? 0) || 0,
      });
      out({ ok: true, round, waitDeadlineAt: deadline });
      break;
    }
    case "progress-set-epochs": {
      const round = requireRound(args);
      const epochs = Number(args.epochs);
      if (!Number.isSafeInteger(epochs) || epochs < 0) die("--epochs K required");
      const prev = lastProgress(readEvents(root), round);
      appendEvent(root, {
        v: 1,
        kind: "collection_progress",
        round,
        ts: nowIso(),
        phase: prev?.phase === "evidence_ready" ? "evidence_ready" : "waiting",
        waitDeadlineAt: prev?.waitDeadlineAt,
        completedWaitEpochs: epochs,
        evidenceHandle: prev?.evidenceHandle,
      });
      out({ ok: true, round, completedWaitEpochs: epochs });
      break;
    }
    case "progress-classify": {
      const round = requireRound(args);
      out(classify(root, round));
      break;
    }
    case "receipt-attempted":
    case "receipt-succeeded":
    case "receipt-failed": {
      const round = requireRound(args);
      const key = String(args.key ?? "").trim();
      if (!key) die("--key required");
      const seat = String(args.seat ?? "verify");
      const op = String(args.op ?? "resolve");
      const state =
        cmd === "receipt-attempted"
          ? "attempted"
          : cmd === "receipt-succeeded"
            ? "succeeded"
            : "failed";
      const handle =
        args.handle !== undefined ? String(args.handle).trim() : undefined;
      appendEvent(root, {
        v: 1,
        kind: "side_effect_receipt",
        round,
        ts: nowIso(),
        seat,
        op,
        idempotencyKey: key,
        state,
        ...(handle ? { externalHandle: handle } : {}),
      });
      out({ ok: true, round, key, state });
      break;
    }
    case "receipt-decide": {
      const round = requireRound(args);
      const key = String(args.key ?? "").trim();
      const fact = String(args.fact ?? "").trim();
      if (!key) die("--key required");
      if (!["applied", "not_applied", "unknown"].includes(fact)) {
        die("--fact applied|not_applied|unknown required");
      }
      const receipt = lastReceipt(readEvents(root), round, key);
      const decision = decide(receipt, fact);
      if (
        decision.action === "skip_already_done" &&
        receipt &&
        receipt.state !== "succeeded"
      ) {
        appendEvent(root, {
          v: 1,
          kind: "side_effect_receipt",
          round,
          ts: nowIso(),
          seat: receipt.seat,
          op: receipt.op,
          idempotencyKey: key,
          state: "succeeded",
          ...(receipt.externalHandle
            ? { externalHandle: receipt.externalHandle }
            : {}),
        });
      }
      out(decision);
      break;
    }
    case "receipt-get": {
      const round = requireRound(args);
      const key = String(args.key ?? "").trim();
      if (!key) die("--key required");
      const receipt = lastReceipt(readEvents(root), round, key);
      out(receipt ?? null);
      break;
    }
    case "evidence-put": {
      const round = requireRound(args);
      let body;
      if (args.file === "-" || args.file === undefined) {
        body = readFileSync(0);
      } else {
        body = readFileSync(String(args.file));
      }
      const id = `r${round}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
      const handle = `${BLOBS_DIR}/${id}`;
      const dest = blobAbs(root, handle);
      const tmp = `${dest}.tmp`;
      mkdirSync(dirname(dest), { recursive: true });
      writeFileSync(tmp, body);
      renameSync(tmp, dest);
      appendEvent(root, {
        v: 1,
        kind: "collection_progress",
        round,
        ts: nowIso(),
        phase: "evidence_ready",
        evidenceHandle: handle,
      });
      out({ handle });
      break;
    }
    case "evidence-get": {
      const handle = String(args.handle ?? "").trim();
      if (!handle) die("--handle required");
      const path = blobAbs(root, handle);
      if (!existsSync(path)) die(`evidence handle unreadable: ${handle}`, 2);
      process.stdout.write(readFileSync(path));
      break;
    }
    default:
      die(`unknown cmd: ${cmd}`);
  }
}

main();
