import { execFileSync } from "node:child_process";

export interface AssertionDiffInput {
  readonly baseToBefore: string;
  readonly beforeToFix: string;
}

export interface ReviewFixDecisionGateInput {
  readonly preexistingAssertionTouched: boolean;
  readonly finding: string;
  readonly acceptanceCriterion: string;
}

type DiffLine = { readonly path: string; readonly line: string };

function assertionLines(diff: string, prefix: "+" | "-"): DiffLine[] {
  let path = "";
  const lines: DiffLine[] = [];
  for (const line of diff.split(/\r?\n/)) {
    if (line.startsWith("diff --git a/") && line.includes(" b/")) {
      path = line.slice(line.lastIndexOf(" b/") + 3);
    }
    if (line.startsWith("+++ b/")) path = line.slice(6);
    if (!/(^|\/)test\//.test(path) || !line.startsWith(prefix)) continue;
    const text = line.slice(1).trim();
    if (/\bexpect\s*\(|\bassert(?:\.|\()|\bto(?:Equal|Be|Throw|Match)\s*\(/.test(text)) {
      lines.push({ path, line: text });
    }
  }
  return lines;
}

/** Mechanical signal only: it never decides whether a fix is acceptable. */
export function preexistingAssertionTouched(input: AssertionDiffInput): boolean {
  const sliceAdded = new Set(
    assertionLines(input.baseToBefore, "+").map(({ path, line }) => `${path}\0${line}`),
  );
  return assertionLines(input.beforeToFix, "-").some(
    ({ path, line }) => !sliceAdded.has(`${path}\0${line}`),
  );
}

/** Uses the runner's existing escalation / decision-gate record shape. */
export function reviewFixDecisionGate(input: ReviewFixDecisionGateInput):
  | { readonly escalate: { readonly reason: string; readonly diagnosis: string } }
  | undefined {
  if (!input.preexistingAssertionTouched) return undefined;
  return {
    escalate: {
      reason: "review fix would overturn a preexisting acceptance assertion",
      diagnosis:
        `Finding: ${input.finding}. Acceptance criterion at risk: ` +
        `${input.acceptanceCriterion}. Preserve the ratified assertion or request a decision.`,
    },
  };
}

export function reviewFixAssertionSignal(input: {
  readonly worktreePath: string;
  readonly sliceBase: string;
  readonly beforeFix: string;
  readonly afterFix: string;
}): boolean {
  const diff = (from: string, to: string): string =>
    execFileSync("git", ["-C", input.worktreePath, "diff", "--unified=0", from, to, "--", "**/test/**"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
  try {
    return preexistingAssertionTouched({
      baseToBefore: diff(input.sliceBase, input.beforeFix),
      beforeToFix: diff(input.beforeFix, input.afterFix),
    });
  } catch {
    return false;
  }
}
