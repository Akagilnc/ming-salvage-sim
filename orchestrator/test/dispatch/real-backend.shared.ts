import { dirname, join } from "node:path";

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  readFileSync,
  writeFileSync,
} from "node:fs";

import { homedir, tmpdir } from "node:os";

import { fileURLToPath } from "node:url";

import { afterAll, afterEach, describe, expect, it, vi } from "vitest";

import {
  agentForSlug,
  attributeFailure,
  branchForIssue,
  candidateBranches,
  buildAuthPaths,
  buildIssueMeta,
  checkExecutableInstructionSource,
  classifyResumeError,
  cutRefFor,
  extractCoderTag,
  isReadyForAgent,
  issueNumberFromBranch,
  lastSessionId,
  matchWorktreeForBranch,
  modelIdForSlug,
  modelFamilyForSlug,
  modelIsStrongLeg,
  parseBlockedBy,
  parseSubIssueCount,
  promptsDirError,
  soulsDirError,
  REQUIRED_SOUL_FILES,
  resolveModelSlug,
  soulForStep,
  REFERENCED_PROMPT_FILES,
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_GROK_DIR,
  SANDBOX_SKILLS_DIR,
  SUPPORTED_MODEL_PROVIDER_FACTORIES,
  WORKER_IDLE_TIMEOUT_SECONDS,
  type GhBlockedBy,
  type GhIssueJson,
} from "../../src/realBackend.js";

import type {
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

import type * as sc from "@ai-hero/sandcastle";

import { resolveRouteModels } from "../../src/modelRoutes.js";

import * as telemetry from "../../src/telemetry.js";

import * as scRuntime from "@ai-hero/sandcastle";

import { StructuredOutputError } from "@ai-hero/sandcastle";

import {
  DECISION_GATE_TAG,
  RECEIPT_MAX_RETRIES,
  decisionGateSignalSchema,
  isReceiptRecoveryFailure,
  workerReceiptSchema,
} from "../../src/receiptRecovery.js";

import {
  CODER_RECEIPT_TAG,
  coderStationReceiptSchema,
  judgeStationReceiptSchema,
  JUDGE_RECEIPT_TAG,
} from "../../src/stationReceiptContracts.js";

import {
  runScriptedStructuredOutput,
  type ScriptedAgent,
} from "../helpers/scripted-sandcastle-run.js";

const CODER_COMPLETED_ENVELOPE = {
  station: "coder" as const,
  status: "completed" as const,
  committed: true,
  commitsAdded: 1,
};

const CODER_NO_COMMIT_ENVELOPE = {
  station: "coder" as const,
  status: "completed" as const,
  committed: false,
  commitsAdded: 0,
};

const CODER_ESCALATE_ENVELOPE = {
  station: "coder" as const,
  status: "escalate" as const,
  reason: "owner choice",
  diagnosis: "contract fork",
  committed: false,
  commitsAdded: 0,
};

type AgentRunResult = Awaited<ReturnType<typeof sc.run>>;

function agentRunResult({
  stdout,
  commits = [],
  sessionId,
  output,
}: {
  readonly stdout: string;
  readonly commits?: ReadonlyArray<{ sha: string }>;
  readonly sessionId: string;
  readonly output?: unknown;
}): AgentRunResult {
  // #928: do not feed completionSignal — completion is exit + legal sidecar.
  return {
    branch: "test-agent-branch",
    stdout,
    commits: [...commits],
    iterations: [{ sessionId }],
    ...(output !== undefined ? { output } : {}),
  } as AgentRunResult;
}

const tempHomes: string[] = [];

function tempHome(prefix = "rb-home-748-"): string {
  const home = mkdtempSync(join(tmpdir(), prefix));
  tempHomes.push(home);
  return home;
}

function cleanupTempHomes(): void {
  while (tempHomes.length > 0) {
    const home = tempHomes.pop();
    if (home !== undefined) rmSync(home, { recursive: true, force: true });
  }
}

export {
  dirname,
  join,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  readFileSync,
  writeFileSync,
  homedir,
  tmpdir,
  fileURLToPath,
  afterAll,
  afterEach,
  describe,
  expect,
  it,
  vi,
  agentForSlug,
  attributeFailure,
  branchForIssue,
  candidateBranches,
  buildAuthPaths,
  buildIssueMeta,
  checkExecutableInstructionSource,
  classifyResumeError,
  cutRefFor,
  extractCoderTag,
  isReadyForAgent,
  issueNumberFromBranch,
  lastSessionId,
  matchWorktreeForBranch,
  modelIdForSlug,
  modelFamilyForSlug,
  modelIsStrongLeg,
  parseBlockedBy,
  parseSubIssueCount,
  promptsDirError,
  soulsDirError,
  REQUIRED_SOUL_FILES,
  resolveModelSlug,
  soulForStep,
  REFERENCED_PROMPT_FILES,
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_GROK_DIR,
  SANDBOX_SKILLS_DIR,
  SUPPORTED_MODEL_PROVIDER_FACTORIES,
  WORKER_IDLE_TIMEOUT_SECONDS,
  GhBlockedBy,
  GhIssueJson,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  sc,
  resolveRouteModels,
  telemetry,
  scRuntime,
  StructuredOutputError,
  DECISION_GATE_TAG,
  RECEIPT_MAX_RETRIES,
  decisionGateSignalSchema,
  isReceiptRecoveryFailure,
  workerReceiptSchema,
  CODER_RECEIPT_TAG,
  coderStationReceiptSchema,
  judgeStationReceiptSchema,
  JUDGE_RECEIPT_TAG,
  runScriptedStructuredOutput,
  ScriptedAgent,
  CODER_COMPLETED_ENVELOPE,
  CODER_NO_COMMIT_ENVELOPE,
  CODER_ESCALATE_ENVELOPE,
  AgentRunResult,
  agentRunResult,
  tempHomes,
  tempHome,
  cleanupTempHomes,
};
