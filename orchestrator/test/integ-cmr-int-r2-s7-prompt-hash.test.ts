/**
 * integ-cmr int-r2 — Finding C-int2-1 (P2): S7 ship worker's prompt hash must be
 * threaded into the ledger.
 *
 * S7 is dispatched through `dispatchWorker(backend, shipWorkerSpec(), …)`, but the
 * runner never assigned `shipWorkerSpec().promptFile` ("ship.md") to the loop-scoped
 * `promptFile` it hands `emitLedger`. So the S7 ledger entry's `prompt_hash` degraded
 * to the STEP-NAME hash (`name:<sha(stepId)>`) instead of the ship.md CONTENT hash —
 * violating the WorkerSpec anti-tampering contract (types.ts: "promptFile CONTENT is
 * hashed into the ledger"). The escalate path persisted the same way (promptFile
 * undefined on the failing S7 entry).
 *
 * These tests pin BOTH paths:
 *   1. the happy S7 → its ledger entry carries `content:<sha(ship.md)>` (the SAME
 *      shape S2/S3 agent steps carry), NOT `name:<sha("S7")>`.
 *   2. an escalating S7 → the persisted failing-S7 entry ALSO carries the ship.md
 *      content hash (the resume-truth audit covers the ship step's prompt too).
 */

import { describe, expect, it } from "vitest";
import { shipWorkerSpec } from "../src/dispatchWorker.js";
import { runOrchestrator } from "../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
import type {
  Backend,
  DispatchContext,
  Escalation,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";

// The web-crypto sha256 the runner's hashPrompt uses (runner.ts:sha256Hex).
async function sha256Hex(s: string): Promise<string> {
  const buf = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(s),
  );
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

const SHIP_PROMPT_CONTENT = "SHIP PROMPT BODY — ship the slice (gstack-ship)\n";

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-int2",
  base: "main",
  path: "/resident/worktrees/issue-int2",
};

/**
 * A backend that resolves promptFile→content (so the runner can hash CONTENT) and
 * dispatches the ship worker. Its `dispatchWorker` ship leg can be told to escalate.
 */
class ShipLedgerBackend implements Backend {
  readonly ledgerCalls: PersistentLedgerEntry[] = [];
  constructor(private readonly shipEscalation?: Escalation) {}

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession should not be called in this test");
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return { number: issueNumber, isReadyForAgent: true, hasSubIssues: false, openBlockedBy: [] };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "## Agent Brief\ndo it" };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(): Promise<StepOutput> {
    throw new Error("runStep should not be called directly");
  }
  async push(): Promise<void> {
    throw new Error("push should not be called directly");
  }
  async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
    this.ledgerCalls.push(entry);
  }

  /** Resolve every versioned promptFile to a stable body so the runner hashes CONTENT. */
  async readPromptContent(promptFile: string): Promise<string | undefined> {
    if (promptFile === "ship.md") return SHIP_PROMPT_CONTENT;
    // Stable per-name body for the agent steps (so their hashes are content hashes too).
    return `PROMPT(${promptFile})`;
  }

  async dispatchWorker(spec: WorkerSpec, _ctx: DispatchContext): Promise<WorkerResult> {
    if (spec.kind === "coder") {
      return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
    }
    if (spec.kind === "reviewer") {
      return { kind: "completed", output: { kind: "reviewer", findings: [] } };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) {
      return skeleton;
    }
    // ship (S7)
    if (this.shipEscalation !== undefined) {
      return { kind: "escalated", escalation: this.shipEscalation, sessionId: "ship-sess-1" };
    }
    return { kind: "completed", output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" } };
  }
}

describe("integ-cmr int-r2 C-int2-1 — S7 ledger carries the ship.md CONTENT hash", () => {
  it("happy S7 → prompt_hash is content:<sha(ship.md)>, NOT name:<sha('S7')>", async () => {
    const backend = new ShipLedgerBackend();
    const result = await runOrchestrator({ issueNumber: 4242, backend });
    expect(result.status).toBe("success");

    const s7 = backend.ledgerCalls.find((e) => e.step === "S7");
    expect(s7).toBeDefined();

    const expectedContent = `content:${await sha256Hex(SHIP_PROMPT_CONTENT)}`;
    const degradedName = `name:${await sha256Hex("S7")}`;
    const degradedNameByFile = `name:${await sha256Hex(shipWorkerSpec().promptFile)}`;

    // The anti-tampering audit: the ship STEP's prompt CONTENT is in the ledger.
    expect(s7!.prompt_hash).toBe(expectedContent);
    // And it is NOT the degraded step-name hash (the bug).
    expect(s7!.prompt_hash).not.toBe(degradedName);
    expect(s7!.prompt_hash).not.toBe(degradedNameByFile);
  });

  it("escalating S7 → the persisted failing-S7 entry ALSO carries the ship.md content hash", async () => {
    const backend = new ShipLedgerBackend({ reason: "gstack-ship STOP", diagnosis: "needs human" });
    const result = await runOrchestrator({ issueNumber: 4343, backend });
    expect(result.status).toBe("escalate");

    // escalateTermination persists the failing S7 entry (resume truth) — its
    // prompt_hash must be the ship.md content hash, not the step-name fallback.
    const s7 = backend.ledgerCalls.find((e) => e.step === "S7");
    expect(s7).toBeDefined();

    const expectedContent = `content:${await sha256Hex(SHIP_PROMPT_CONTENT)}`;
    const degradedName = `name:${await sha256Hex("S7")}`;
    expect(s7!.prompt_hash).toBe(expectedContent);
    expect(s7!.prompt_hash).not.toBe(degradedName);
  });
});
