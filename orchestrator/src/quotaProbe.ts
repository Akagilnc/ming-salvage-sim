/**
 * #683 — runner 额度探针：idle 超阈先探 429 再判 hang。
 *
 * 额度墙外观与 hang 不可区分（进程活着、stdout 静默）。人肉 runner 的规程
 * （#440 交接手册第 0 步）是 idle 报警后先 curl/PONG 探针再判死；本模块把该
 * 决策固化为可测状态机：
 *
 *   idle 超阈 → run pool probe →
 *     429/limit  → wait_for_reset（不杀进程、不 abort、ledger 记重置时刻）
 *     探针通过  → hang（只杀该实例 pid 树）
 *     网络错误  → fail-safe hang（≠ 429；不无限等待）
 *
 * 探针本身可注入（单测打桩三种结果）；真探针实现（curl / opencode PONG）是
 * 可选生产路径，不阻塞状态机验收。自动重派/续跑编排属 #686，本模块不管。
 */

import type { StepId } from "./types.js";

/** Provider quota pool the worker is drawing from. */
export type QuotaPoolId = "zai" | "opencode-go" | "grok" | "unknown";

/**
 * Per-pool probe kind (config follows the route/model table companion).
 *   - zai_chat      — minimal chat completions request
 *   - opencode_pong — `opencode run … "Reply with exactly: PONG"`
 *   - grok_tbd      — reserved (SuperGrok probe not yet codified)
 *   - none          — no probe registered → treat as probe error (fail-safe hang)
 */
export type PoolProbeKind = "zai_chat" | "opencode_pong" | "grok_tbd" | "none";

export interface PoolProbeConfig {
  readonly pool: QuotaPoolId;
  readonly kind: PoolProbeKind;
  /** One-line human description of how this pool is probed. */
  readonly description: string;
}

/**
 * Result of a quota probe. Callers inject stubs in tests; production code runs
 * the real probe via {@link runPoolProbe} (or its own fetch/exec).
 */
export type QuotaProbeResult =
  | { readonly kind: "ok" }
  | {
      readonly kind: "quota_limited";
      /** Parsed reset instant when the 429 body carries one. */
      readonly resetAt?: Date;
      readonly detail?: string;
    }
  | {
      readonly kind: "error";
      /** Network / spawn / unexpected failure (NOT a 429). */
      readonly cause: string;
    };

/** What the runner should do after idle-threshold + probe. */
export type IdleDisposition =
  | {
      readonly kind: "hang";
      readonly reason: string;
      readonly pool: QuotaPoolId;
    }
  | {
      readonly kind: "wait_for_reset";
      readonly pool: QuotaPoolId;
      readonly resetAt?: Date;
      readonly reason: string;
    };

/**
 * Append-only ledger row when a worker is parked on a quota wall (#683).
 * Lives in {@link import("./types.js").LedgerBookkeepingEvent}.
 */
export interface QuotaWaitForResetLedgerEvent {
  readonly event: "quota_wait_for_reset";
  readonly pool: QuotaPoolId;
  /** ISO-8601 reset instant when known (from 429 body). */
  readonly resetAt?: string;
  readonly reason: string;
  readonly step?: StepId;
  readonly workerPid?: number;
  readonly ts: string;
}

/** Actions the disposition applier needs from the runner host. */
export interface IdleHangActions {
  /** Kill only this worker's pid tree (never global pgrep/pkill -f). */
  readonly killPidTree: (pid: number) => void | Promise<void>;
  /** Persist the wait-for-reset ledger row. */
  readonly recordLedger: (
    entry: QuotaWaitForResetLedgerEvent,
  ) => void | Promise<void>;
  /** Clock injection for tests. */
  readonly now?: () => Date;
}

export interface IdleWorkerHandle {
  /** OS pid of the worker process (monitor handle; see also #684). */
  readonly pid: number;
  readonly step?: StepId;
}

export interface ApplyIdleDispositionResult {
  readonly killed: boolean;
  readonly ledgerEntry?: QuotaWaitForResetLedgerEvent;
}

// ── per-pool config (route-table companion) ──────────────────────────────────

const POOL_PROBE_CONFIG: Readonly<Record<QuotaPoolId, PoolProbeConfig>> = {
  zai: {
    pool: "zai",
    kind: "zai_chat",
    description:
      "POST minimal chat/completions to api.z.ai; 429 body carries 北京时间 reset clock",
  },
  "opencode-go": {
    pool: "opencode-go",
    kind: "opencode_pong",
    description:
      'opencode run --dangerously-skip-permissions -m opencode-go/<model> "Reply with exactly: PONG"',
  },
  grok: {
    pool: "grok",
    kind: "grok_tbd",
    description: "SuperGrok pool probe TBD; until codified, treat as fail-safe hang on idle",
  },
  unknown: {
    pool: "unknown",
    kind: "none",
    description: "no registered pool probe for this model slug",
  },
};

/** Look up the probe config for a pool (always defined, including `unknown`). */
export function probeConfigForPool(pool: QuotaPoolId): PoolProbeConfig {
  return POOL_PROBE_CONFIG[pool];
}

/**
 * Map a route/model reference (slug, `provider/model`, or CLI model id) to a
 * quota pool. Companion to the model route table — pool membership is derived
 * from naming conventions used by the cheap-coder benches (#424 / #440).
 */
export function poolForModelRef(modelRef: string): QuotaPoolId {
  const raw = modelRef.trim().toLowerCase();
  if (raw.length === 0) return "unknown";

  // Explicit provider prefix wins.
  if (raw.startsWith("zai/") || raw === "zai") return "zai";
  if (raw.startsWith("opencode-go/") || raw === "opencode-go") return "opencode-go";

  // Grok CLI family (SuperGrok subscription pool).
  if (raw.startsWith("grok-") || raw === "grok" || raw.startsWith("grok/")) {
    return "grok";
  }

  // Bare GLM ids default to zai (primary free/lite path); long-running GLM can
  // still be addressed as opencode-go/glm-… via the prefix branch above.
  if (raw.startsWith("glm-") || raw.includes("glm-5")) return "zai";

  // kimi bare slug is Go-pool only (openrouter path is retired / #440).
  if (raw.includes("kimi")) return "opencode-go";

  return "unknown";
}

// ── state machine ───────────────────────────────────────────────────────────

/**
 * After idle threshold fires, decide hang vs wait-for-reset from the probe
 * result. Pure: no I/O, no kill.
 */
export function decideIdleAfterProbe(
  pool: QuotaPoolId,
  probe: QuotaProbeResult,
): IdleDisposition {
  if (probe.kind === "quota_limited") {
    return {
      kind: "wait_for_reset",
      pool,
      resetAt: probe.resetAt,
      reason:
        probe.detail !== undefined && probe.detail.length > 0
          ? `quota limited (429); wait for reset: ${probe.detail}`
          : "quota limited (429); wait for reset",
    };
  }
  if (probe.kind === "error") {
    return {
      kind: "hang",
      pool,
      reason: `idle threshold exceeded; quota probe error (fail-safe hang): ${probe.cause}`,
    };
  }
  // probe.kind === "ok"
  return {
    kind: "hang",
    pool,
    reason: "idle threshold exceeded; quota probe ok",
  };
}

/** Build the ledger-visible wait-for-reset row (ISO resetAt when known). */
export function buildQuotaWaitForResetLedgerEntry(input: {
  readonly pool: QuotaPoolId;
  readonly resetAt?: Date;
  readonly reason: string;
  readonly step?: StepId;
  readonly workerPid?: number;
  readonly now: Date;
}): QuotaWaitForResetLedgerEvent {
  return {
    event: "quota_wait_for_reset",
    pool: input.pool,
    ...(input.resetAt !== undefined
      ? { resetAt: input.resetAt.toISOString() }
      : {}),
    reason: input.reason,
    ...(input.step !== undefined ? { step: input.step } : {}),
    ...(input.workerPid !== undefined ? { workerPid: input.workerPid } : {}),
    ts: input.now.toISOString(),
  };
}

/**
 * Apply an idle disposition:
 *   - hang           → kill the worker pid tree; no wait-for-reset ledger row
 *   - wait_for_reset → do NOT kill; record ledger (pool + resetAt)
 */
export async function applyIdleDisposition(
  disposition: IdleDisposition,
  worker: IdleWorkerHandle,
  actions: IdleHangActions,
): Promise<ApplyIdleDispositionResult> {
  if (disposition.kind === "hang") {
    await actions.killPidTree(worker.pid);
    return { killed: true };
  }

  const now = actions.now?.() ?? new Date();
  const ledgerEntry = buildQuotaWaitForResetLedgerEntry({
    pool: disposition.pool,
    resetAt: disposition.resetAt,
    reason: disposition.reason,
    step: worker.step,
    workerPid: worker.pid,
    now,
  });
  await actions.recordLedger(ledgerEntry);
  return { killed: false, ledgerEntry };
}

// ── zai 429 body parsing ────────────────────────────────────────────────────

/**
 * Parse a zai (智谱/z.ai coding paas) 429 body for the reset wall-clock.
 * Bodies quote 北京时间 (Asia/Shanghai, UTC+8); convert to a UTC Date.
 *
 * Recognises forms like `2026-07-09 00:10:00` or `2026-07-09T00:10:00`.
 */
export function parseZaiResetAt(body: string): Date | undefined {
  if (body.length === 0) return undefined;
  // YYYY-MM-DD[ T]HH:MM:SS — first match is the reset clock in practice.
  const m = body.match(
    /(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/,
  );
  if (m === null) return undefined;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const hour = Number(m[4]);
  const minute = Number(m[5]);
  const second = m[6] !== undefined ? Number(m[6]) : 0;
  // Asia/Shanghai = UTC+8 year-round (no DST).
  const utcMs = Date.UTC(year, month - 1, day, hour - 8, minute, second);
  const d = new Date(utcMs);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

// ── optional production probe runners (injectable I/O) ──────────────────────

export interface PoolProbeDeps {
  /** HTTP fetch used by the zai probe. Defaults to global fetch. */
  readonly fetch?: typeof fetch;
  /** Shell runner for opencode PONG. Defaults to a tiny spawn wrapper. */
  readonly runCommand?: (
    argv: ReadonlyArray<string>,
    opts: { readonly timeoutMs: number },
  ) => Promise<{ readonly code: number; readonly stdout: string; readonly stderr: string }>;
  /** zai API key. Defaults to env ZAI_API_KEY / GLM_KEY. */
  readonly zaiApiKey?: string;
  /** Model id for the zai minimal chat (default glm-5.2). */
  readonly zaiModel?: string;
  /** Model slug for the opencode-go PONG smoke. */
  readonly opencodeGoModel?: string;
  /** Wall-clock budget for a single probe. */
  readonly timeoutMs?: number;
}

const ZAI_CHAT_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions";
const DEFAULT_PROBE_TIMEOUT_MS = 60_000;

/**
 * Run the registered probe for `pool`. Network/CLI errors surface as
 * `{kind:"error"}` (fail-safe hang), never as infinite wait. 429 / rate-limit
 * text surfaces as `{kind:"quota_limited"}` with a parsed resetAt when present.
 *
 * Production convenience — unit tests inject {@link QuotaProbeResult} directly
 * into {@link decideIdleAfterProbe} and do not need this.
 */
export async function runPoolProbe(
  pool: QuotaPoolId,
  deps: PoolProbeDeps = {},
): Promise<QuotaProbeResult> {
  const cfg = probeConfigForPool(pool);
  switch (cfg.kind) {
    case "zai_chat":
      return runZaiChatProbe(deps);
    case "opencode_pong":
      return runOpencodePongProbe(deps);
    case "grok_tbd":
      return {
        kind: "error",
        cause: "grok pool probe not yet codified (kind=grok_tbd)",
      };
    case "none":
      return {
        kind: "error",
        cause: `no quota probe registered for pool "${pool}"`,
      };
  }
}

async function runZaiChatProbe(deps: PoolProbeDeps): Promise<QuotaProbeResult> {
  const key =
    deps.zaiApiKey ??
    process.env.ZAI_API_KEY ??
    process.env.GLM_KEY ??
    "";
  if (key.length === 0) {
    return { kind: "error", cause: "zai probe missing API key (ZAI_API_KEY/GLM_KEY)" };
  }
  const fetchFn = deps.fetch ?? fetch;
  const model = deps.zaiModel ?? "glm-5.2";
  try {
    const res = await fetchFn(ZAI_CHAT_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: "p" }],
        max_tokens: 4,
      }),
      signal: AbortSignal.timeout(deps.timeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS),
    });
    const body = await res.text();
    if (res.status === 429 || isQuotaLimitBody(body)) {
      return {
        kind: "quota_limited",
        resetAt: parseZaiResetAt(body),
        detail: body.slice(0, 500),
      };
    }
    if (!res.ok) {
      // Non-429 HTTP failure: fail-safe hang (not a quota wall we can wait on).
      return {
        kind: "error",
        cause: `zai probe HTTP ${res.status}: ${body.slice(0, 200)}`,
      };
    }
    return { kind: "ok" };
  } catch (err) {
    return {
      kind: "error",
      cause: err instanceof Error ? err.message : String(err),
    };
  }
}

async function runOpencodePongProbe(
  deps: PoolProbeDeps,
): Promise<QuotaProbeResult> {
  const model = deps.opencodeGoModel ?? "opencode-go/deepseek-v4-flash";
  const timeoutMs = deps.timeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS;
  const run =
    deps.runCommand ??
    (async (argv, opts) => {
      const { spawn } = await import("node:child_process");
      return await new Promise<{
        code: number;
        stdout: string;
        stderr: string;
      }>((resolve, reject) => {
        const child = spawn(argv[0]!, argv.slice(1), {
          stdio: ["ignore", "pipe", "pipe"],
        });
        let stdout = "";
        let stderr = "";
        const timer = setTimeout(() => {
          child.kill("SIGTERM");
          reject(new Error(`opencode PONG probe timed out after ${opts.timeoutMs}ms`));
        }, opts.timeoutMs);
        child.stdout?.on("data", (c: Buffer) => {
          stdout += c.toString("utf8");
        });
        child.stderr?.on("data", (c: Buffer) => {
          stderr += c.toString("utf8");
        });
        child.on("error", (err) => {
          clearTimeout(timer);
          reject(err);
        });
        child.on("close", (code) => {
          clearTimeout(timer);
          resolve({ code: code ?? 1, stdout, stderr });
        });
      });
    });

  try {
    const out = await run(
      [
        "opencode",
        "run",
        "--dangerously-skip-permissions",
        "-m",
        model,
        "Reply with exactly: PONG",
      ],
      { timeoutMs },
    );
    const combined = `${out.stdout}\n${out.stderr}`;
    if (isQuotaLimitBody(combined)) {
      return {
        kind: "quota_limited",
        detail: combined.slice(0, 500),
      };
    }
    if (out.code !== 0) {
      return {
        kind: "error",
        cause: `opencode PONG exit ${out.code}: ${combined.slice(0, 200)}`,
      };
    }
    if (!/\bPONG\b/i.test(out.stdout)) {
      // No PONG within a successful exit is treated as a soft wall (Go pool
      // often returns empty stdout when rate-limited and silently retrying).
      return {
        kind: "quota_limited",
        detail: "opencode PONG missing from stdout (treat as quota wall)",
      };
    }
    return { kind: "ok" };
  } catch (err) {
    return {
      kind: "error",
      cause: err instanceof Error ? err.message : String(err),
    };
  }
}

function isQuotaLimitBody(body: string): boolean {
  const lower = body.toLowerCase();
  return (
    lower.includes("429") ||
    lower.includes("rate limit") ||
    lower.includes("rate_limit") ||
    lower.includes("quota") ||
    body.includes("额度") ||
    body.includes("余额不足") ||
    body.includes("配额")
  );
}
