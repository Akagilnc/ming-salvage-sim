import { execFileSync } from "node:child_process";

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import * as sc from "@ai-hero/sandcastle";

import {
  RealFamilyBackend,
  SHIP_FOCUS_FILENAME,
  type ShipAuth,
} from "../../../src/family/realFamilyBackend.js";

import {
  modelIdForSlug,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_REPO_ENV,
  SANDBOX_SOUL_ENV,
  soulsMount,
  SPAWNED_WORKER_ENV,
} from "../../../src/realBackend.js";

import { cmrWorkerSpec, familyShipWorkerSpec } from "../../../src/family/dispatchFamilyWorker.js";

import {
  isReceiptRecoveryFailure,
  RECEIPT_MAX_RETRIES,
  shipReceiptOutput,
} from "../../../src/receiptRecovery.js";

import {
  SHIP_RECEIPT_TAG,
  shipStationReceiptSchema,
} from "../../../src/stationReceiptContracts.js";

import {
  shipOutcomeFromResult,
  type ShipWorkerOutcome,
} from "../../../src/shipOutcome.js";

import type { DispatchContext, WorkerSpec } from "../../../src/types.js";

import { isRunnerSynthesizedFailureEscalation } from "../../../src/runnerEscalation.js";

import {
  runScriptedStructuredOutput,
  type ScriptedAgent,
} from "../../helpers/scripted-sandcastle-run.js";

import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

function modelOfAgent(agent: unknown): string {
  const build = (agent as { buildPrintCommand?: (p: string) => { command: string } })
    .buildPrintCommand;
  if (typeof build !== "function") throw new Error("agent has no buildPrintCommand");
  const m = /(?:--model|-m) '([^']+)'/.exec(build("x").command);
  if (m === null) throw new Error(`no model flag in: ${build("x").command}`);
  return m[1]!;
}

const here = dirname(fileURLToPath(import.meta.url));

const realPromptsDir = join(here, "..", "..", "..", "prompts");

const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

const cleanups: string[] = [];

function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  cleanups.push(d);
  return d;
}

const FAMILY_BASE = "feat/330-pure-scheduler";

class FixturedShipBackend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

  runShipCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
  outcome: ReturnType<typeof shipOutcomeFromResult> = {
    kind: "shipped",
    branch: FAMILY_BASE,
    status: "pr_opened",
    pr: "https://gh/pr/9",
  };
  protected override async runShipWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ReturnType<typeof shipOutcomeFromResult>> {
    this.runShipCalls.push({ spec, ctx });
    return this.outcome;
  }
}

function fixtured(): FixturedShipBackend {
  return new FixturedShipBackend({
    workingRepo: mkDir("ship-repo-"),
    familyBase: FAMILY_BASE,
    ledgerDir: mkDir("ship-ledger-"),
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir: realPromptsDir,
    soulsDir: realSoulsDir,
    imageName: "ming-orchestrator-coder:latest",
  });
}

export {
  execFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
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
  RealFamilyBackend,
  SHIP_FOCUS_FILENAME,
  ShipAuth,
  modelIdForSlug,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_REPO_ENV,
  SANDBOX_SOUL_ENV,
  soulsMount,
  SPAWNED_WORKER_ENV,
  cmrWorkerSpec,
  familyShipWorkerSpec,
  isReceiptRecoveryFailure,
  RECEIPT_MAX_RETRIES,
  shipReceiptOutput,
  SHIP_RECEIPT_TAG,
  shipStationReceiptSchema,
  shipOutcomeFromResult,
  ShipWorkerOutcome,
  DispatchContext,
  WorkerSpec,
  isRunnerSynthesizedFailureEscalation,
  runScriptedStructuredOutput,
  ScriptedAgent,
  buildExplicitLandingLiveHooks,
  modelOfAgent,
  here,
  realPromptsDir,
  realSoulsDir,
  cleanups,
  mkDir,
  FAMILY_BASE,
  FixturedShipBackend,
  fixtured,
};
