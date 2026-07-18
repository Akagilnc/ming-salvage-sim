import {
  afterEach,
  describe,
  expect,
  it,
  readFileSync,
  rmSync,
  dirname,
  join,
  fileURLToPath,
  RECEIPT_MAX_RETRIES,
  CODER_RECEIPT_TAG,
  coderStationReceiptSchema,
  decodeCoderEnvelope,
  classifyResumeError,
  runOrchestrator,
  skeletonReviewLoopWorkerResult,
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  StepOutput,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  runScriptedStructuredOutput,
  ScriptedAgent,
  PROMPTS_DIR,
  WORKTREE,
  S2_SESSION,
  PersistCoderBackend,
} from "./coder-persist-typed-924.shared.js";

// #962: per-run GIT_CONFIG_GLOBAL isolation removes the old sequential need.
describe("#924 coder station-receipt Output.object (T2 schema)", () => {
  const cleanups: string[] = [];
  afterEach(() => {
    while (cleanups.length > 0) {
      const dir = cleanups.pop();
      if (dir !== undefined) rmSync(dir, { recursive: true, force: true });
    }
  });

  const goodCompleted = {
    station: "coder" as const,
    status: "completed" as const,
    committed: true,
    commitsAdded: 1,
  };

  it("accepts a legal completed envelope via real sc.run (positive)", async () => {
    const { agent, result } = await runScriptedStructuredOutput({
      tag: CODER_RECEIPT_TAG,
      schema: coderStationReceiptSchema(),
      emissions: [{ body: JSON.stringify(goodCompleted) }],
      maxRetries: RECEIPT_MAX_RETRIES,
      sessionId: "sess-924-coder-good",
      cleanups,
    });
    expect(result.output).toMatchObject({
      station: "coder",
      status: "completed",
    });
    expect(agent.callCount).toBe(1);
    const decoded = decodeCoderEnvelope(result.output);
    expect(decoded.ok).toBe(true);
  });

  it("re-asks in-session when the envelope shape is illegal (negative)", async () => {
    // Bad: missing station/status traffic fields → SO re-ask → good on second try.
    const agentOut: { agent?: ScriptedAgent } = {};
    const { agent, result } = await runScriptedStructuredOutput({
      tag: CODER_RECEIPT_TAG,
      schema: coderStationReceiptSchema(),
      emissions: [
        { body: JSON.stringify({ committed: true, commitsAdded: 1 }) },
        { body: JSON.stringify(goodCompleted) },
      ],
      maxRetries: RECEIPT_MAX_RETRIES,
      sessionId: "sess-924-coder-reask",
      cleanups,
      agentOut,
    });
    expect(result.output).toMatchObject({ status: "completed", station: "coder" });
    expect(agent.callCount).toBe(2);
    expect(agent.resumedSessions).toEqual([undefined, "sess-924-coder-reask"]);
    expect(agentOut.agent?.callCount).toBe(2);
  });

});
