import {
  execFileSync,
  mkdtempSync,
  rmSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  vi,
  here,
  realPromptsDir,
  realSoulsDir,
  buildFamilyEpic,
  cutFamilyBase,
  discoverSubprojects,
  filterExternalBlockedChildren,
  FamilyRootBlockerError,
  inferVerifyCwd,
  parseSubIssueAdmission,
  readFamilyEpic,
  Sh,
  RealFamilyBackend,
  GhBlockedBy,
  git,
  cleanups,
} from "./driver-assembly.shared.js";

afterEach(() => {
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

describe("#291 cutFamilyBase (real local clone)", () => {
  function makeClone(): string {
    const src = mkdtempSync(join(tmpdir(), "cfb-src-"));
    cleanups.push(src);
    git(src, "init", "-q", "-b", "main");
    git(src, "config", "user.email", "t@t.t");
    git(src, "config", "user.name", "t");
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: src });
    const clone = mkdtempSync(join(tmpdir(), "cfb-clone-"));
    cleanups.push(clone);
    const dir = join(clone, "repo");
    git(clone, "clone", "-q", src, dir);
    git(dir, "config", "user.email", "t@t.t");
    git(dir, "config", "user.name", "t");
    return dir;
  }
  function makeLedgerDir(): string {
    const d = mkdtempSync(join(tmpdir(), "cfb-ledger-"));
    cleanups.push(d);
    return d;
  }
  const realSh: Sh = (file, args) => execFileSync(file, args, { encoding: "utf8" }).trim();

  it("cuts the LOCAL family base from origin/main and returns its start head", () => {
    const clone = makeClone();
    const head = cutFamilyBase(clone, "family/291-base", "main", realSh, makeLedgerDir());
    expect(head).toBe(git(clone, "rev-parse", "origin/main"));
    // the local branch exists now.
    expect(git(clone, "rev-parse", "family/291-base")).toBe(head);
  });

  it("persists the cut SHA so resume returns the ORIGINAL start head, NOT the advanced HEAD (cmr R2 #2)", () => {
    // cmr R2 #2: the empty-ledger crash-window net (reconcile.ts) compares the live
    // family head to the recorded START head; if cutFamilyBase returned the CURRENT
    // (advanced) HEAD on resume, `liveHead === startHead` trivially → the net is
    // silently disabled (fail-OPEN). The cut SHA must be PERSISTED at first cut and
    // re-READ on resume, so the start head stays the divergence point even after the
    // base has accumulated merges.
    const clone = makeClone();
    const ledgerDir = makeLedgerDir();
    const first = cutFamilyBase(clone, "family/291-base", "main", realSh, ledgerDir);
    // advance the family base with a commit (a prior wave's merge).
    git(clone, "checkout", "-q", "family/291-base");
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "wave1"], { cwd: clone });
    const advanced = git(clone, "rev-parse", "family/291-base");
    expect(advanced).not.toBe(first);
    // a second cut REUSES the branch (no re-cut, no lost waves) but returns the
    // PERSISTED ORIGINAL start head — NOT the advanced HEAD.
    const resumed = cutFamilyBase(clone, "family/291-base", "main", realSh, ledgerDir);
    expect(resumed).toBe(first);
    expect(resumed).not.toBe(advanced);
  });

  it("fails CLOSED on resume when the persisted start head is missing/unreadable (no fall-back to live HEAD)", () => {
    // If the branch already exists (resume) but the persisted start-head file is
    // gone (manual deletion / corruption), cutFamilyBase must NOT silently fall back
    // to the live HEAD (which defeats the crash-window net) — it must throw so the
    // caller fails closed.
    const clone = makeClone();
    const ledgerDir = makeLedgerDir(); // empty: branch will exist but no persisted head
    // Create the branch WITHOUT going through cutFamilyBase (simulate a stale resume
    // where the branch survives but the persisted start head does not).
    git(clone, "branch", "family/291-base", "origin/main");
    expect(() => cutFamilyBase(clone, "family/291-base", "main", realSh, ledgerDir)).toThrow(
      /start head|persist|fail.?closed/i,
    );
  });

  it("cuts from the CONFIGURED base (not hardcoded main) when the PR target differs", () => {
    // agy R1: the driver advertises a configurable target base (options.base), but a
    // hardcoded "main" would cut the family base off the WRONG branch when the PR
    // targets e.g. "develop" — and familyBaseDiff (`base...familyBase`) would then
    // emit a wrong/polluted diff. Prove the cut honors the passed base.
    const src = mkdtempSync(join(tmpdir(), "cfb-dev-src-"));
    cleanups.push(src);
    git(src, "init", "-q", "-b", "main");
    git(src, "config", "user.email", "t@t.t");
    git(src, "config", "user.name", "t");
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: src });
    // A "develop" branch that DIVERGES from main (a unique commit), so cutting from
    // the wrong branch is observable (different head than origin/main).
    git(src, "checkout", "-q", "-b", "develop");
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "develop-only"], { cwd: src });
    git(src, "checkout", "-q", "main");
    const clone = mkdtempSync(join(tmpdir(), "cfb-dev-clone-"));
    cleanups.push(clone);
    const dir = join(clone, "repo");
    git(clone, "clone", "-q", src, dir);

    const head = cutFamilyBase(dir, "family/291-base", "develop", realSh, makeLedgerDir());
    // The family base head is origin/develop's head, NOT origin/main's.
    expect(head).toBe(git(dir, "rev-parse", "origin/develop"));
    expect(head).not.toBe(git(dir, "rev-parse", "origin/main"));
  });
});

describe("#335 runIntegratedCmr legacy per-method seam (the real cmr is the container worker)", () => {
  it("the RealFamilyBackend's default runIntegratedCmr throws (the production cmr path is dispatchWorker → the container cmr worker, #335)", async () => {
    const repo = mkdtempSync(join(tmpdir(), "cmr-seam-"));
    cleanups.push(repo);
    git(repo, "init", "-q");
    const b = new RealFamilyBackend({
      workingRepo: repo,
      familyBase: "family/291-base",
      ledgerDir: mkdtempSync(join(tmpdir(), "cmr-ledger-")),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });
    await expect(b.runIntegratedCmr({ familyBase: "family/291-base" })).rejects.toThrow(
      /ak-cross-m-review|driver|manual-smoke/i,
    );
  });
});
