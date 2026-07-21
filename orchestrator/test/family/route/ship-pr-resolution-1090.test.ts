/**
 * #1090 — ship PR URL resolution: never write a branch name as the shipped
 * ledger `pr`; validate ship.pr as a real PR URL (http(s) + /pull/<number>) and
 * otherwise resolve the open PR for the family branch via `gh pr list`.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../src/externalCall.js", () => ({
  shWithClock: vi.fn(),
}));

import { shWithClock } from "../../../src/externalCall.js";
import { recordShipped } from "../../../src/family/ledger.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
} from "../../../src/family/types.js";

function fakeBackend(appended: FamilyLedgerEntry[]): FamilyBackend {
  return {
    appendFamilyLedger: async (entry: FamilyLedgerEntry) => {
      appended.push(entry);
    },
    readFamilyLedger: async () => appended,
  } as unknown as FamilyBackend;
}

describe("#1090 recordShipped rejects branch-name pr (loud)", () => {
  it("throws on a branch name instead of a PR URL", async () => {
    const appended: FamilyLedgerEntry[] = [];
    await expect(
      recordShipped(fakeBackend(appended), {
        pr: "feat/issue-256",
        familyHeadAfter: "abc123",
      }),
    ).rejects.toThrow(/\/pull\//);
    expect(appended).toEqual([]);
  });

  it("throws on a bare non-http value", async () => {
    const appended: FamilyLedgerEntry[] = [];
    await expect(
      recordShipped(fakeBackend(appended), {
        pr: "not-a-url",
        familyHeadAfter: "abc123",
      }),
    ).rejects.toThrow(/\/pull\//);
    expect(appended).toEqual([]);
  });

  it("accepts a valid https PR URL", async () => {
    const appended: FamilyLedgerEntry[] = [];
    await recordShipped(fakeBackend(appended), {
      pr: "https://github.com/owner/repo/pull/123",
      familyHeadAfter: "abc123",
    });
    expect(appended).toHaveLength(1);
    expect(appended[0]!.pr).toBe("https://github.com/owner/repo/pull/123");
  });

  it("rejects a non-github host that admits the old write-gate regex (#1090 P1)", async () => {
    const appended: FamilyLedgerEntry[] = [];
    await expect(
      recordShipped(fakeBackend(appended), {
        pr: "https://example.com/x/pull/123",
        familyHeadAfter: "abc123",
      }),
    ).rejects.toThrow(/\/pull\//);
    expect(appended).toEqual([]);
  });

  it("rejects a github PR URL with trailing junk after the number (#1090 P1)", async () => {
    const appended: FamilyLedgerEntry[] = [];
    await expect(
      recordShipped(fakeBackend(appended), {
        pr: "https://github.com/o/r/pull/123junk",
        familyHeadAfter: "abc123",
      }),
    ).rejects.toThrow(/\/pull\//);
    expect(appended).toEqual([]);
  });
});

describe("#1090 isPrUrl", () => {
  it("accepts http(s) PR URLs with a numeric pull id", async () => {
    const { isPrUrl } = await import("../../../src/family/verifyCmr.js");
    expect(isPrUrl("https://github.com/owner/repo/pull/123")).toBe(true);
    expect(isPrUrl("http://github.com/owner/repo/pull/1")).toBe(true);
  });

  it("rejects branch names, issue URLs, and bare paths", async () => {
    const { isPrUrl } = await import("../../../src/family/verifyCmr.js");
    expect(isPrUrl("feat/issue-256")).toBe(false);
    expect(isPrUrl("main")).toBe(false);
    expect(isPrUrl("https://github.com/owner/repo/issues/123")).toBe(false);
    expect(isPrUrl("")).toBe(false);
  });

  it("rejects non-github hosts and trailing-junk lookalikes (consumer parity, #1090 P1)", async () => {
    const { isPrUrl } = await import("../../../src/family/verifyCmr.js");
    // Both proven counter-examples admit /^https?:\/\/\S*\/pull\/\d+/ but the
    // online-review consumer (botPolling.parsePrRef) rejects them — the write
    // gate must track the consumer, not a lookalike regex.
    expect(isPrUrl("https://example.com/x/pull/123")).toBe(false);
    expect(isPrUrl("https://github.com/o/r/pull/123junk")).toBe(false);
  });
});

describe("#1090 resolveFamilyShipPr", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.ORCHESTRATOR_REPO;
  });

  it("resolves the open PR URL for a branch via gh pr list", async () => {
    vi.mocked(shWithClock).mockReturnValue(
      JSON.stringify([{ url: "https://github.com/owner/repo/pull/42" }]),
    );
    const { resolveFamilyShipPr } = await import(
      "../../../src/family/verifyCmr.js"
    );
    const url = resolveFamilyShipPr("feat/issue-256");
    expect(url).toBe("https://github.com/owner/repo/pull/42");
    expect(shWithClock).toHaveBeenCalledWith(
      "gh",
      [
        "pr",
        "list",
        "--head",
        "feat/issue-256",
        "--json",
        "url",
        "--limit",
        "1",
      ],
      { stage: "resolve:shipPr" },
    );
  });

  it("appends --repo when ORCHESTRATOR_REPO is set", async () => {
    process.env.ORCHESTRATOR_REPO = "owner/repo";
    vi.mocked(shWithClock).mockReturnValue(
      JSON.stringify([{ url: "https://github.com/owner/repo/pull/42" }]),
    );
    const { resolveFamilyShipPr } = await import(
      "../../../src/family/verifyCmr.js"
    );
    resolveFamilyShipPr("feat/issue-256");
    expect(shWithClock).toHaveBeenCalledWith(
      "gh",
      expect.arrayContaining(["--repo", "owner/repo"]),
      expect.anything(),
    );
  });

  it("returns undefined when gh finds no open PR", async () => {
    vi.mocked(shWithClock).mockReturnValue("[]");
    const { resolveFamilyShipPr } = await import(
      "../../../src/family/verifyCmr.js"
    );
    expect(resolveFamilyShipPr("feat/issue-256")).toBeUndefined();
  });

  it("returns undefined when gh URL is malformed (missing /pull/)", async () => {
    vi.mocked(shWithClock).mockReturnValue(
      JSON.stringify([
        { url: "https://github.com/owner/repo/branch/feat-x" },
      ]),
    );
    const { resolveFamilyShipPr } = await import(
      "../../../src/family/verifyCmr.js"
    );
    expect(resolveFamilyShipPr("feat/issue-256")).toBeUndefined();
  });

  it("returns undefined when gh throws", async () => {
    vi.mocked(shWithClock).mockImplementation(() => {
      throw new Error("gh not authenticated");
    });
    const { resolveFamilyShipPr } = await import(
      "../../../src/family/verifyCmr.js"
    );
    expect(resolveFamilyShipPr("feat/issue-256")).toBeUndefined();
  });
});
