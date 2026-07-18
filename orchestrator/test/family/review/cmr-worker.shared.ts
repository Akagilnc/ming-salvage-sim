import { execFileSync } from "node:child_process";

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import * as sc from "@ai-hero/sandcastle";

import type { RunResult } from "@ai-hero/sandcastle";

import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

import {
  CMR_ROUTE_FILENAME,
  CMR_FOCUS_FILENAME,
  cmrOutcomeFromResult,
  parseCmrOutcome,
  RealFamilyBackend,
  SANDBOX_AGY_DIR,
  type CmrAuth,
  type CmrWorkerOutcome,
  type ShipAuth,
} from "../../../src/family/realFamilyBackend.js";

import {
  DECISION_GATE_TAG,
  decisionGateSignalSchema,
  isReceiptRecoveryFailure,
  RECEIPT_MAX_RETRIES,
  workerReceiptSchema,
} from "../../../src/receiptRecovery.js";

import {
  CODER_RECEIPT_TAG,
  coderStationReceiptSchema,
} from "../../../src/stationReceiptContracts.js";

import {
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../../../src/dispatchRetry.js";

import {
  runScriptedStructuredOutput,
  type ScriptedAgent,
} from "../../helpers/scripted-sandcastle-run.js";

import {
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_REPO_ENV,
  SANDBOX_SOUL_ENV,
  SPAWNED_WORKER_ENV,
} from "../../../src/realBackend.js";

import {
  cmrWorkerSpec,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
} from "../../../src/family/dispatchFamilyWorker.js";

import { shipOutcomeFromResult } from "../../../src/shipOutcome.js";

import { isRunnerSynthesizedFailureEscalation } from "../../../src/runnerEscalation.js";

import type {

  DispatchContext,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const here = dirname(fileURLToPath(import.meta.url));

const realPromptsDir = join(here, "..", "..", "..", "prompts");

const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

const DEFAULT_CMR_LEGS = ["opus", "gpt-5.6-sol", "agy"] as const;

const FROZEN_NORMAL_CMR_REVIEW_LEGS = [
  { family: "codex", slug: "gpt-5.6-sol" },
  { family: "claude", slug: "opus" },
  { family: "agy", slug: "agy" },
] as const;

const STRONG_LEGS = ["opus", "gpt-5.6-sol"] as const;

const EMPTY_CMR_CLOSURE = {
  claimedFixedFindingIdentityKeys: [],
  priorFindingDispositions: [],
} as const;

const CMR_EVIDENCE_PATHS = ["cmr/review-summary.json"] as const;

const CMR_EVIDENCE = {
  evidencePaths: CMR_EVIDENCE_PATHS,
} as const;

const VALID_CMR_VERDICT_FIELDS = {
  ...EMPTY_CMR_CLOSURE,
  ...CMR_EVIDENCE,
} as const;

const DERIVED_EMPTY_FINDINGS_COUNT = { findingsCount: 0 } as const;

function sandboxRunResult({
  branch = "fb",
  stdout = "",
  commits = [],
  sessionId,
}: {
  readonly branch?: string;
  readonly stdout?: string;
  readonly commits?: ReadonlyArray<{ readonly sha: string }>;
  readonly sessionId?: string;
} = {}): RunResult {
  // #928: do not feed completionSignal — completion is exit + legal sidecar.
  return {
    branch,
    stdout,
    commits: [...commits],
    iterations: sessionId === undefined ? [] : [{ sessionId }],
  };
}

function typedSandboxRunResult<T>(
  output: T,
  fields: Parameters<typeof sandboxRunResult>[0] = {},
): RunResult & { readonly output: T } {
  return { ...sandboxRunResult(fields), output };
}

const cleanups: string[] = [];

function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  cleanups.push(d);
  return d;
}

function makeBackend(over?: {
  home?: string;
  ledgerDir?: string;
}): RealFamilyBackend {
  return new RealFamilyBackend({
    workingRepo: mkDir("cmr-repo-"),
    familyBase: "feat/330-pure-scheduler",
    ledgerDir: over?.ledgerDir ?? mkDir("cmr-ledger-"),
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir: realPromptsDir,
    soulsDir: realSoulsDir,
    imageName: "ming-orchestrator-coder:latest",
    home: over?.home,
  });
}

function realRepo335(): string {
  const repo = mkDir("cmr-guard-repo-");
  execFileSync("git", ["init", "-q"], { cwd: repo });
  return repo;
}

function legacyClaudeCmrSpec(): ReturnType<typeof cmrWorkerSpec> {
  return { ...cmrWorkerSpec(), model: "opus" };
}

export {
  execFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  vi,
  sc,
  RunResult,
  docker,
  CMR_ROUTE_FILENAME,
  CMR_FOCUS_FILENAME,
  cmrOutcomeFromResult,
  parseCmrOutcome,
  RealFamilyBackend,
  SANDBOX_AGY_DIR,
  CmrAuth,
  CmrWorkerOutcome,
  ShipAuth,
  DECISION_GATE_TAG,
  decisionGateSignalSchema,
  isReceiptRecoveryFailure,
  RECEIPT_MAX_RETRIES,
  workerReceiptSchema,
  CODER_RECEIPT_TAG,
  coderStationReceiptSchema,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
  runScriptedStructuredOutput,
  ScriptedAgent,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_REPO_ENV,
  SANDBOX_SOUL_ENV,
  SPAWNED_WORKER_ENV,
  cmrWorkerSpec,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
  shipOutcomeFromResult,
  isRunnerSynthesizedFailureEscalation,
  DispatchContext,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  buildExplicitLandingLiveHooks,
  here,
  realPromptsDir,
  realSoulsDir,
  DEFAULT_CMR_LEGS,
  FROZEN_NORMAL_CMR_REVIEW_LEGS,
  STRONG_LEGS,
  EMPTY_CMR_CLOSURE,
  CMR_EVIDENCE_PATHS,
  CMR_EVIDENCE,
  VALID_CMR_VERDICT_FIELDS,
  DERIVED_EMPTY_FINDINGS_COUNT,
  sandboxRunResult,
  typedSandboxRunResult,
  cleanups,
  mkDir,
  makeBackend,
  realRepo335,
  legacyClaudeCmrSpec,
};
