export const meta = {
  name: 'epic-orchestrator',
  description: '读取 GitHub 原生子 issue 与 blocked_by 边，按依赖层并行跑各切片 worktree，自检/评审后通过串行队列合入家族分支。',
  whenToUse: 'Issue #225 S6：父 epic issue 号（可带上一段回传的 mergedNumbers / dirty / dismissals / decisions 做段间续跑）-> 层 barrier 并行切片实现 -> 本地 verify -> per-slice codex+agy review -> 串行家族分支 merge 队列 -> 家族集成 verify + base 管理 -> 5a/5b 家族 cmr（codex+Claude+agy，findings 分流 + abort；已裁定 decision finding 不再 HALT 但照旧全量复审）-> 收敛后 gstack-ship 跑完整（coverage/specialist/RedTeam 闸 + push + 建家族 PR）-> 三结束态（ready / needs-user / unconverged）带 handoff payload 回主 session。relaunch 时按 mergedNumbers git 跳过已合片、dirty 片即便已合也重做；编排器始终停在线上 PR 评审前交回主 session。',
  phases: [
    { title: 'Discover', detail: '读取 gh 原生子 issue 与 blocked_by 边' },
    { title: 'Plan', detail: '运行 drift-guarded 的 S0 拓扑内联副本，把 open 切片分组为依赖层' },
    { title: 'Continuation Filter', detail: '运行 drift-guarded 的 S6 continuationPlan 内联副本：按 mergedNumbers git 跳过已合片、dirty 片即便已合也强制进 todo 重做；todoTotal=0 则跳过实现/合并直达 Family Verify/Review/Ship' },
    { title: 'Implement', detail: '同层实现腿并发运行，使用 isolation:"worktree" 并遵守 I7/I8' },
    { title: 'Verify', detail: '任何 review 前先跑本地验证命令' },
    { title: 'Review', detail: '通过 Bash 跑 per-slice codex + agy；隐藏 worktree 下 agy 只看 diff，codex 可完整 grounding' },
    { title: 'Merge', detail: '编排器用单写者 worktree 串行合并 reviewed commit 到家族分支' },
    { title: 'Family Verify', detail: '全片落地后在合并后的家族 worktree 上整体跑 I9 typecheck/unit/full verify' },
    { title: 'Base Management', detail: '进入家族 CMR/gstack-ship 前按 I10 比对启动 target HEAD；base 前进则 rebase 并重跑 I9' },
    { title: 'Family Review', detail: '在合并后家族分支跑 5a/5b cmr（codex+Claude+agy；家族 worktree 在隐藏 .epic-orchestrator 下，agy 只看 diff）；findings 分流（I5：机械 bug 自治修重过 5a/5b、选择回主 session 升级）；不收敛 abort（I1）/可用模型 <2 降级回主 session（I2）' },
    { title: 'Ship', detail: '家族承重闸收敛后调 gstack-ship 跑完整（coverage/specialist/RedTeam 闸 + push + 建家族 PR；闸不可跳）-> inlineShipOutcome 三结束态（ready / needs-user / unconverged）+ inlineBuildHandoffPayload 组 §段间交接 handoff，停在线上评审前（绝不驱动线上 bot 循环）' }
  ]
};

class InlineTopologyError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'TopologyError';
    this.code = code;
  }
}

const isClosed = (state) => state?.toLowerCase() === 'closed';
const sameId = (left, right) => String(left) === String(right);
const idKey = (id) => String(id);
const byIssueIds = (left, right) =>
  compareIssueKeys(idKey(left.issueId), idKey(right.issueId)) || compareIssueKeys(idKey(left.blockedByIssueId), idKey(right.blockedByIssueId));

// Thin inline copy of web/src/orchestratorKernel.ts layerEpicIssues.
// Workflow sandboxes cannot import the TS authority directly; web/src/epicOrchestratorWorkflow.test.ts
// is the drift guard that behavior-diffs this copy against the S0 authority.
export function inlineLayerEpicIssues(input) {
  const epicChildren = input.issues.filter((issue) => sameId(issue.epicId, input.epicId));
  if (epicChildren.length === 0) {
    throw new InlineTopologyError('empty_epic', `Epic ${input.epicId} has no native sub-issues.`);
  }

  const byKey = new Map(input.issues.map((issue) => [idKey(issue.id), issue]));
  const openChildren = epicChildren.filter((issue) => !isClosed(issue.state));
  const openChildKeys = new Set(openChildren.map((issue) => idKey(issue.id)));
  const skippedClosedIssueIds = epicChildren
    .filter((issue) => isClosed(issue.state))
    .map((issue) => issue.id)
    .sort((left, right) => compareIssueKeys(idKey(left), idKey(right)));

  const externalPrerequisites = input.blockedBy
    .filter((edge) => {
      if (!openChildKeys.has(idKey(edge.issueId))) return false;
      if (openChildKeys.has(idKey(edge.blockedByIssueId))) return false;

      const blocker = byKey.get(idKey(edge.blockedByIssueId));
      return blocker === undefined || !isClosed(blocker.state);
    })
    .sort(byIssueIds);

  if (externalPrerequisites.length > 0) {
    return {
      status: 'external_prerequisite',
      layers: [],
      skippedClosedIssueIds,
      externalPrerequisites
    };
  }

  const indegree = new Map();
  const issueIdsByKey = new Map();
  const dependents = new Map();

  for (const issue of openChildren) {
    const key = idKey(issue.id);
    indegree.set(key, 0);
    issueIdsByKey.set(key, issue.id);
    dependents.set(key, []);
  }

  for (const edge of input.blockedBy) {
    const issueKey = idKey(edge.issueId);
    const blockerKey = idKey(edge.blockedByIssueId);
    if (!openChildKeys.has(issueKey) || !openChildKeys.has(blockerKey)) continue;

    dependents.get(blockerKey)?.push(issueKey);
    indegree.set(issueKey, (indegree.get(issueKey) ?? 0) + 1);
  }

  const layers = [];
  let ready = [...indegree.entries()]
    .filter(([, degree]) => degree === 0)
    .map(([key]) => key)
    .sort(compareIssueKeys);
  const emitted = new Set();

  while (ready.length > 0) {
    const currentLayerKeys = ready;
    layers.push(currentLayerKeys.map((key) => issueIdsByKey.get(key)));

    ready = [];
    for (const key of currentLayerKeys) {
      emitted.add(key);
      const nextKeys = dependents.get(key) ?? [];
      for (const nextKey of nextKeys) {
        const nextDegree = (indegree.get(nextKey) ?? 0) - 1;
        indegree.set(nextKey, nextDegree);
        if (nextDegree === 0) ready.push(nextKey);
      }
    }
    ready.sort(compareIssueKeys);
  }

  if (emitted.size !== openChildren.length) {
    const cycleIssueIds = [...indegree.entries()]
      .filter(([key, degree]) => degree > 0 && !emitted.has(key))
      .map(([key]) => key)
      .sort(compareIssueKeys)
      .join(', ');
    throw new InlineTopologyError('cycle', `Open epic children contain a blocked_by cycle: ${cycleIssueIds}.`);
  }

  return {
    status: 'ready',
    layers,
    skippedClosedIssueIds,
    externalPrerequisites: []
  };
}

// Thin inline copy of web/src/orchestratorKernel.ts familyReviewGate (I5 routing + I1 abort).
// Workflow sandboxes cannot import the TS authority; the drift guard in
// web/src/epicOrchestratorWorkflow.test.ts behavior-diffs this copy against the kernel.
export function inlineFamilyReviewGate(input) {
  const { escalateCount, mechanicalCount, round, maxRounds } = input;
  if (escalateCount > 0) return 'escalate';
  if (mechanicalCount === 0) return 'converged';
  return round < maxRounds ? 'fix' : 'abort';
}

// Thin inline copy of web/src/orchestratorKernel.ts routeFindings (I5 classification bucketing).
export function inlineRouteFindings(findings) {
  const autonomousBugFindings = [];
  const decisionFindings = [];
  for (const finding of findings) {
    if (finding && finding.classification === 'mechanical_bug') {
      autonomousBugFindings.push(finding);
    } else {
      decisionFindings.push(finding);
    }
  }
  if (decisionFindings.length > 0) {
    return { status: 'needs_decision', autonomousBugFindings, decisionFindings };
  }
  if (autonomousBugFindings.length > 0) {
    return { status: 'autonomous_repair', autonomousBugFindings, decisionFindings };
  }
  return { status: 'no_findings', autonomousBugFindings, decisionFindings };
}

// Thin inline copy of the family_5a_5b branch of judgeReviewDegradation (I2):
// the family CMR is the load-bearing gate, so <2 distinct available models halts the run.
export function inlineJudgeFamilyDegradation(results) {
  const availableModels = [...new Set(results.filter((result) => result.available).map((result) => result.model))];
  const missingByModel = new Map();
  for (const result of results) {
    if (!result.available && !missingByModel.has(result.model)) missingByModel.set(result.model, result);
  }
  const missingModels = [...missingByModel.keys()];
  if (availableModels.length < 2) {
    return {
      status: 'halt',
      availableModels,
      missingModels,
      flags: ['family 5a/5b requires at least two available models']
    };
  }
  return {
    status: 'continue',
    availableModels,
    missingModels,
    flags: [...missingByModel.values()].map((result) => `review degraded: ${result.model} unavailable${result.reason ? ` (${result.reason})` : ''}`)
  };
}

// Thin inline copy of web/src/orchestratorKernel.ts shipOutcome (S5 exit contract).
// Workflow sandboxes cannot import the TS authority; the drift guard in
// web/src/epicOrchestratorWorkflow.test.ts behavior-diffs this copy against the kernel.
// asked (gstack-ship internal ASK gate) wins first -> needs-user; else gates passed AND PR
// created -> ready; anything else -> unconverged.
export function inlineShipOutcome(input) {
  if (input.asked) return 'needs-user';
  return input.gatesPassed && input.prCreated ? 'ready' : 'unconverged';
}

// Thin inline copy of web/src/orchestratorKernel.ts buildHandoffPayload (§段间交接).
// Assembles the stable handoff payload every run returns to the main session; all three terminal
// states share one shape (missing fields filled with stable nulls / empty arrays). Drift-guarded.
export function inlineBuildHandoffPayload(input) {
  const payload = {
    status: input.status,
    epic: input.epic,
    familyBranch: input.familyBranch,
    baseAtStart: input.baseAtStart,
    familyHead: input.familyHead ?? null,
    merged: input.merged ?? [],
    dirty: input.dirty ?? [],
    question: input.question ?? null,
    detail: input.detail ?? null,
    flags: input.flags ?? [],
    prUrl: input.prUrl ?? null
  };
  if (input.reason !== undefined) payload.reason = input.reason;
  return payload;
}

// Thin inline copy of web/src/orchestratorKernel.ts continuationPlan (S6 segment continuation).
// Workflow sandboxes cannot import the TS authority; the drift guard in
// web/src/epicOrchestratorWorkflow.test.ts behavior-diffs this copy against the kernel.
// Skip a slice iff the family branch already has its commit AND it is not dirty; run it iff it is
// missing OR dirty. Membership is compared via idKey so string/number ids for the same slice match.
export function inlineContinuationPlan(input) {
  const merged = new Set(input.mergedNumbers.map(idKey));
  const dirtyKeys = new Set((input.dirty ?? []).map(idKey));
  const layers = input.layers.map((layer) => {
    const todo = [];
    const skipped = [];
    const layerDirty = [];
    for (const slice of layer) {
      const key = idKey(slice);
      const isDirty = dirtyKeys.has(key);
      if (isDirty) layerDirty.push(slice);
      if (!merged.has(key) || isDirty) todo.push(slice);
      else skipped.push(slice);
    }
    return { todo, skipped, dirty: layerDirty };
  });
  const todoTotal = layers.reduce((sum, layer) => sum + layer.todo.length, 0);
  return { layers, todoTotal };
}

// Thin inline copy of web/src/orchestratorKernel.ts dismissalGate (S6 false-positive non-loop).
// A finding the user already ruled "doesn't count" (id / claim / location) no longer HALTs the run;
// it is NOT removed from the review (full re-review discipline holds), only excluded from the
// escalate count. Match on id, claim (claimQuote/claim_quote unified), or location — any one.
export function inlineDismissalGate(input) {
  const { finding, dismissed = [] } = input;
  if (!finding) return true; // a null/garbage finding cannot match a dismissal -> not dismissed (still HALT-eligible)
  const findingClaim = inlineClaimOf(finding);
  const matched = dismissed.some((entry) => {
    if (entry.id !== undefined && finding.id !== undefined && entry.id === finding.id) return true;
    const entryClaim = inlineClaimOf(entry);
    if (entryClaim !== undefined && findingClaim !== undefined && entryClaim === findingClaim) return true;
    if (entry.location !== undefined && finding.location !== undefined && entry.location === finding.location) return true;
    return false;
  });
  return !matched;
}

function inlineClaimOf(value) {
  if (!value) return undefined;
  return value.claimQuote !== undefined ? value.claimQuote : value.claim_quote;
}

function compareIssueKeys(left, right) {
  const leftIsDecimal = isDecimalIssueKey(left);
  const rightIsDecimal = isDecimalIssueKey(right);
  if (leftIsDecimal && rightIsDecimal) {
    const numericOrder = Number(left) - Number(right);
    return numericOrder || left.localeCompare(right);
  }
  if (leftIsDecimal) return -1;
  if (rightIsDecimal) return 1;
  return left.localeCompare(right);
}

function isDecimalIssueKey(key) {
  return /^[0-9]+$/.test(key);
}

export function normalizeWorkflowArgs(rawArgs) {
  const rawEpic = typeof rawArgs === 'object' && rawArgs !== null && 'epicIssueNumber' in rawArgs ? rawArgs.epicIssueNumber : rawArgs;
  const epicIssueNumber = String(rawEpic ?? '').trim();
  if (!/^[0-9]+$/.test(epicIssueNumber)) {
    throw new Error('epic-orchestrator requires args to be a positive parent epic issue number, e.g. 217 or {"epicIssueNumber":217}.');
  }
  if (Number(epicIssueNumber) <= 0) {
    throw new Error('epic-orchestrator requires args to be a positive parent epic issue number, e.g. 217 or {"epicIssueNumber":217}.');
  }
  return epicIssueNumber;
}

export async function runEpicDiscoveryWorkflow({ args, Bash, log }) {
  const epicIssueNumber = normalizeWorkflowArgs(args);

  phaseIfAvailable('Discover');
  log?.(`Discovering native sub-issues and native blocked_by edges for epic #${epicIssueNumber}`);
  const discovered = parseBashJson(
    await Bash(`python3 - ${shellQuote(epicIssueNumber)} <<'PY'
import json
import os
import subprocess
import sys

GH_TIMEOUT_SECONDS = 30
epic = sys.argv[1]


def run_gh(args, context):
    try:
        completed = subprocess.run(
            ["gh", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"gh {context} timed out after {GH_TIMEOUT_SECONDS}s") from exc
    if completed.returncode != 0:
        raise SystemExit(f"gh {context} failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed.stdout.strip()


def resolve_repo():
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        repo = run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], "repo view")
    if not repo or "/" not in repo:
        raise SystemExit("Could not resolve GitHub repository. Set GITHUB_REPOSITORY or run inside a gh-linked repository.")
    return repo


REPO = resolve_repo()


def gh_json(path):
    payload = run_gh([
        "api",
        "--paginate",
        "--slurp",
        "--method", "GET",
        "-H", "Accept: application/vnd.github+json",
        "-f", "per_page=100",
        path,
    ], f"api {path}")
    pages = json.loads(payload) if payload else []
    if all(isinstance(page, list) for page in pages):
        return [item for page in pages for item in page]
    return pages

children = gh_json(f"/repos/{REPO}/issues/{epic}/sub_issues")
child_numbers = {str(child["number"]) for child in children}
issues_by_key = {}
blocked_by = []

for child in children:
    child_number = str(child["number"])
    issues_by_key[child_number] = {
        "id": child["number"],
        "epicId": int(epic),
        "state": child.get("state"),
        "title": child.get("title", ""),
        "url": child.get("html_url", ""),
    }
    blockers = gh_json(f"/repos/{REPO}/issues/{child_number}/dependencies/blocked_by")
    for blocker in blockers:
        blocker_number = str(blocker["number"])
        blocked_by.append({"issueId": child["number"], "blockedByIssueId": blocker["number"]})
        if blocker_number not in issues_by_key:
            issues_by_key[blocker_number] = {
                "id": blocker["number"],
                "epicId": int(epic) if blocker_number in child_numbers else "__external__",
                "state": blocker.get("state"),
                "title": blocker.get("title", ""),
                "url": blocker.get("html_url", ""),
            }

print(json.dumps({
    "epicId": int(epic),
    "issues": list(issues_by_key.values()),
    "blockedBy": blocked_by,
}, ensure_ascii=False))
PY`)
  );

  const topologyInput = {
    epicId: discovered.epicId,
    issues: discovered.issues.map((issue) => ({ id: issue.id, epicId: issue.epicId, state: issue.state })),
    blockedBy: discovered.blockedBy
  };

  phaseIfAvailable('Plan');
  const topology = inlineLayerEpicIssues(topologyInput);
  const issueMetadata = Object.fromEntries(discovered.issues.map((issue) => [idKey(issue.id), { title: issue.title, state: issue.state, url: issue.url }]));
  const orderedPlan = buildOrderedExecutionPlan(topology, issueMetadata);
  const boundaryHandling = describeBoundaryHandling(topology);
  const result = {
    epicIssueNumber: Number(epicIssueNumber),
    topology,
    orderedPlan,
    boundaryHandling,
    outOfScope: ['review', 'worktree', 'merge']
  };

  log?.(`Ordered execution plan: ${JSON.stringify(orderedPlan)}`);
  log?.(`Boundary handling: ${JSON.stringify(boundaryHandling)}`);
  return result;
}

export async function runEpicSingleSlicePipeline({ args, Bash, agent: agentRunner, log }) {
  const discovery = await runEpicDiscoveryWorkflow({ args, Bash, log });
  if (discovery.topology.status !== 'ready') {
    return { ...discovery, status: discovery.boundaryHandling.action };
  }

  const plannedIssue = discovery.orderedPlan[0]?.issues[0];
  if (!plannedIssue) {
    throw new Error('S2 single-slice pipeline requires at least one planned open slice.');
  }

  const normalizedArgs = normalizePipelineArgs(args, discovery.epicIssueNumber);
  const plannedSlice = {
    ...plannedIssue,
    isolation: 'worktree'
  };

  phaseIfAvailable('Implement');
  log?.(`Implementing one slice with worktree isolation: #${plannedSlice.issueNumber} ${plannedSlice.title ?? ''}`.trim());
  const runner = agentRunner ?? (typeof agent !== 'undefined' ? agent : undefined);
  if (typeof runner !== 'function') {
    throw new Error('S2 single-slice pipeline requires an agent runner for the implementation leg.');
  }

  const implementations = [];
  const verificationAttempts = [];
  const reviewAttempts = [];
  const reviewFixCommits = [];
  let implementation;
  let implementedCommit;
  let worktreePath;
  let verification;
  let review;
  let observabilityEvidence;

  for (let round = 1; round <= normalizedArgs.maxReviewRounds; round += 1) {
    implementation = await runner({
      isolation: 'worktree',
      issueNumber: plannedSlice.issueNumber,
      issue: plannedSlice,
      prompt:
        round === 1
          ? buildImplementationPrompt(discovery.epicIssueNumber, plannedSlice)
          : buildReviewFixPrompt(discovery.epicIssueNumber, plannedSlice, implementations.at(-1)?.commit, review, round, normalizedArgs.maxReviewRounds),
      ...(round === 1
        ? {}
        : {
            reviewFix: {
              failedCommit: implementations.at(-1)?.commit,
              failedReview: review,
              round,
              maxReviewRounds: normalizedArgs.maxReviewRounds
            }
          })
    });
    implementedCommit = implementation?.commit ?? implementation?.commitSha ?? implementation?.sha;
    worktreePath = implementation?.worktreePath ?? implementation?.path;
    if (!implementedCommit || !worktreePath) {
      throw new Error('实现腿必须返回 commit 和 worktreePath。');
    }
    const previousFailedCommit = implementations.at(-1)?.commit;
    if (implementations.length > 0 && implementedCommit === previousFailedCommit) {
      throw new Error('I7 要求每一轮 review-fix 返回新 commit，不能复用未通过评审的 commit。');
    }
    if (!isHiddenWorktreePath(worktreePath)) {
      throw new Error('实现 worktree 必须位于隐藏点目录下，以便 agy 评审明确只看 diff。');
    }
    observabilityEvidence = validateObservabilityEvidence(implementation?.observabilityEvidence);
    implementations.push({ commit: implementedCommit, worktreePath });
    if (round > 1) reviewFixCommits.push(implementedCommit);

    await Bash(`set -euo pipefail\n# 为切片执行 I7 commit 纪律检查 ${shellQuote(plannedSlice.issueNumber)} round ${shellQuote(round)}\nworktreePath=${shellQuote(worktreePath)}\nimplementedCommit=$(git -C "$worktreePath" rev-parse ${shellQuote(`${implementedCommit}^{commit}`)})\nexpectedHead=$(git -C "$worktreePath" rev-parse HEAD)\nif [ "$expectedHead" != "$implementedCommit" ]; then\n  printf '实现 worktree HEAD %s 与 implementedCommit %s 不一致\\n' "$expectedHead" "$implementedCommit" >&2\n  exit 1\nfi\ngit -C "$worktreePath" rev-list --parents -n 1 "$implementedCommit" | awk 'NF >= 2 { ok=1 } END { exit ok ? 0 : 1 }'${previousFailedCommit ? `\nfailedCommit=$(git -C "$worktreePath" rev-parse ${shellQuote(`${previousFailedCommit}^{commit}`)})\ngit -C "$worktreePath" merge-base --is-ancestor "$failedCommit" "$implementedCommit"` : ''}\nstatus=$(git -C "$worktreePath" status --porcelain)\nif [ -n "$status" ]; then\n  printf 'implementedCommit %s 之后实现 worktree 仍不干净：\\n%s\\n' "$implementedCommit" "$status" >&2\n  exit 1\nfi`);

    phaseIfAvailable('Verify');
    verification = await runVerification({ Bash, worktreePath, verifyCommands: normalizedArgs.verifyCommands });
    verificationAttempts.push({ commit: implementedCommit, ...verification });
    if (verification.status !== 'passed') {
      return {
        ...discovery,
        outOfScope: ['parallelism', 'family_5a_5b', 'online_pr_review_loop'],
        status: 'verify_failed',
        plannedSlice,
        implementation: { commit: implementedCommit, worktreePath },
        implementations,
        verification,
        verificationAttempts,
        i7: i7Evidence(implementedCommit, reviewFixCommits),
        i8: i8Evidence(observabilityEvidence)
      };
    }

    phaseIfAvailable('Review');
    review = await runPerSliceReview({ Bash, worktreePath, commit: implementedCommit, plannedSlice });
    reviewAttempts.push({ commit: implementedCommit, ...review });
    if (review.status === 'passed') break;

    if (round >= normalizedArgs.maxReviewRounds) {
      return {
        ...discovery,
        outOfScope: ['parallelism', 'family_5a_5b', 'online_pr_review_loop'],
        status: 'review_failed',
        plannedSlice,
        implementation: { commit: implementedCommit, worktreePath },
        implementations,
        verification,
        verificationAttempts,
        review,
        reviewAttempts,
        i1: { status: 'aborted', reason: 'max_review_rounds', maxReviewRounds: normalizedArgs.maxReviewRounds },
        i7: i7Evidence(implementedCommit, reviewFixCommits),
        i8: i8Evidence(observabilityEvidence)
      };
    }

    log?.(`#${plannedSlice.issueNumber} 单切片评审未通过；开始同切片 review-fix 第 ${round + 1}/${normalizedArgs.maxReviewRounds} 轮。`);
  }

  phaseIfAvailable('Merge');
  const mergeResult = await mergeReviewedCommit({
    Bash,
    worktreePath,
    familyBranch: normalizedArgs.familyBranch,
    implementedCommit,
    plannedSlice
  });
  if (mergeResult.status === 'conflict') {
    return {
      ...discovery,
      outOfScope: ['parallelism', 'family_5a_5b', 'online_pr_review_loop'],
      status: 'return_to_main_session',
      plannedSlice,
      implementation: { commit: implementedCommit, worktreePath },
      implementations,
      verification,
      verificationAttempts,
      review,
      reviewAttempts,
      merge: { status: 'conflict', familyBranch: normalizedArgs.familyBranch, reviewedCommit: implementedCommit, conflict: mergeResult },
      i4: { status: 'aborted', reason: 'merge_conflict' },
      i7: i7Evidence(implementedCommit, reviewFixCommits),
      i8: i8Evidence(observabilityEvidence)
    };
  }

  return {
    ...discovery,
    outOfScope: ['parallelism', 'family_5a_5b', 'online_pr_review_loop'],
    status: 'merged',
    plannedSlice,
    implementation: { commit: implementedCommit, worktreePath },
    implementations,
    verification,
    verificationAttempts,
    review,
    reviewAttempts,
    merge: {
      status: 'merged',
      familyBranch: normalizedArgs.familyBranch,
      reviewedCommit: implementedCommit,
      mergeCommit: mergeResult.mergeCommit
    },
    i7: i7Evidence(implementedCommit, reviewFixCommits),
    i8: i8Evidence(observabilityEvidence)
  };
}

export async function runEpicLayeredPipeline({ args, Bash, agent: agentRunner, log }) {
  const discovery = await runEpicDiscoveryWorkflow({ args, Bash, log });
  if (discovery.topology.status !== 'ready') {
    return { ...discovery, status: discovery.boundaryHandling.action };
  }
  if (discovery.orderedPlan.length === 0) {
    return {
      ...discovery,
      outOfScope: ['family_5a_5b', 'online_pr_review_loop'],
      status: 'return_to_main_session',
      reason: 'no_open_subissues',
      layers: [],
      reviewedSlices: [],
      mergeQueue: [],
      i9: { status: 'aborted', reason: 'no_open_subissues' }
    };
  }

  const normalizedArgs = normalizePipelineArgs(args, discovery.epicIssueNumber);
  const startupTargetHead = await captureStartupTargetHead({ Bash, normalizedArgs });
  const runner = agentRunner ?? (typeof agent !== 'undefined' ? agent : undefined);
  if (typeof runner !== 'function') {
    throw new Error('S3 分层流水线需要 agent runner 执行实现腿。');
  }

  // ── S6 continuation filter: drop git-skipped slices (family branch already has their commit AND
  // they are not dirty) from this segment's execution set; dirty slices stay in todo (re-impl). This
  // uses the drift-guarded inline copy of the S6 continuationPlan authority. A dirty slice is forced
  // back into todo even when merged so it re-runs impl+verify (+ re-passes 5a/5b). todoTotal===0 means
  // the whole epic is already merged with no dirty -> skip implement/merge entirely and run the family
  // branch straight through Family Verify / Family Review / Ship (it is already fully assembled).
  const continuation = inlineContinuationPlan({
    layers: discovery.orderedPlan.map((layerPlan) => layerPlan.issueNumbers),
    mergedNumbers: normalizedArgs.mergedNumbers,
    dirty: normalizedArgs.dirty
  });
  const todoByLayer = continuation.layers.map((layer) => new Set(layer.todo.map(idKey)));

  // S6 continuation: when a prior segment already merged slices, the family branch + worktree exist.
  // Resolve them up front so (a) the first todo slice in this segment bases on the family HEAD (which
  // contains the already-merged blockers) instead of the startup target — preserving topological
  // dependency across a relaunch — and (b) a no-fresh-merge segment (todoTotal===0, or every layer
  // git-skipped) still has the family worktree + HEAD for Family Verify / Review / Ship and the handoff.
  let existingFamily = null;
  if (normalizedArgs.mergedNumbers.length > 0) {
    const resolved = await resolveExistingFamilyWorktree({ Bash, familyBranch: normalizedArgs.familyBranch });
    const head = (await Bash(`set -euo pipefail\n# resolve existing family HEAD (S6 continuation)\ngit -C ${shellQuote(resolved.familyWorktree)} rev-parse HEAD`)).trim();
    existingFamily = { familyWorktree: resolved.familyWorktree, familyHead: head || null };
  }
  const continuationBaseRef = existingFamily?.familyHead || startupTargetHead;
  // Single source of truth for the current family branch tip. Initialized from the existing family
  // HEAD (continuation) and updated at EVERY point that advances it — each slice merge, an I10 rebase,
  // and a family-review fix — so the handoff familyHead / mergeTip is always current even on a
  // no-fresh-merge continuation (where mergeQueue stays empty). Avoids the recurring "stale HEAD on
  // path X" class by tracking it once instead of re-deriving from mergeQueue.at(-1) at each exit.
  let currentFamilyHead = existingFamily?.familyHead ?? null;

  const layers = [];
  const reviewedSlices = [];
  const mergeQueue = [];

  for (const [layerIndex, layerPlan] of discovery.orderedPlan.entries()) {
    const layerTodo = todoByLayer[layerIndex] ?? new Set(layerPlan.issueNumbers.map(idKey));
    const todoIssues = layerPlan.issues.filter((plannedIssue) => layerTodo.has(idKey(plannedIssue.issueNumber)));
    if (todoIssues.length === 0) {
      log?.(`第 ${layerPlan.layer} 层全部已合且无 dirty，git 跳过：${layerPlan.issueNumbers.join(', ')}`);
      layers.push({ layer: layerPlan.layer, issueNumbers: layerPlan.issueNumbers, slices: [], skippedAllMerged: true });
      continue;
    }
    log?.(`开始第 ${layerPlan.layer} 层：${todoIssues.map((issue) => issue.issueNumber).join(', ')}`);
    const sliceBaseContext = buildSliceBaseContext(normalizedArgs, mergeQueue, continuationBaseRef);
    const layerResults = await Promise.all(
      todoIssues.map((plannedIssue) =>
        runSliceReviewLoop({
          discovery,
          normalizedArgs,
          sliceBaseContext,
          plannedIssue,
          Bash,
          runner,
          log
        })
      )
    );

    layers.push({ layer: layerPlan.layer, issueNumbers: layerPlan.issueNumbers, slices: layerResults });

    const failedSlice = layerResults.find((result) => result.status !== 'reviewed');
    if (failedSlice) {
      return {
        ...discovery,
        outOfScope: ['family_5a_5b', 'online_pr_review_loop'],
        status: failedSlice.status,
        layers,
        failedSlice
      };
    }

    for (const slice of layerResults) {
      reviewedSlices.push(slice);
      const mergeResult = await mergeReviewedCommit({
        Bash,
        worktreePath: slice.implementation.worktreePath,
        familyBranch: normalizedArgs.familyBranch,
        implementedCommit: slice.implementation.commit,
        plannedSlice: slice.plannedSlice
      });
      const mergeEntry = {
        status: mergeResult.status === 'conflict' ? 'conflict' : 'merged',
        familyBranch: normalizedArgs.familyBranch,
        reviewedCommit: slice.implementation.commit,
        mergeCommit: mergeResult.mergeCommit,
        familyHead: mergeResult.mergeCommit,
        mergeWorktree: mergeResult.mergeWorktree,
        conflict: mergeResult.status === 'conflict' ? mergeResult : undefined
      };
      mergeQueue.push(mergeEntry);
      if (mergeResult.status !== 'conflict') currentFamilyHead = mergeEntry.familyHead;
      if (mergeResult.status === 'conflict') {
        return {
          ...discovery,
          outOfScope: ['family_5a_5b', 'online_pr_review_loop'],
          status: 'return_to_main_session',
          reason: 'merge_conflict',
          layers,
          reviewedSlices,
          mergeQueue,
          i4: { status: 'aborted', reason: 'merge_conflict' }
        };
      }
    }
  }

  // S6 continuation: when this segment merged no fresh slice (todoTotal===0, or every layer was
  // git-skipped), there is no merge entry to read the worktree from — fall back to the existing
  // family worktree resolved up front, so Family Verify / Review / Ship run on the already-assembled
  // family branch. When slices did merge this segment, use the merge queue's worktree as before.
  const familyWorktree = mergeQueue.at(-1)?.mergeWorktree ?? existingFamily?.familyWorktree;
  if (!familyWorktree) {
    return {
      ...discovery,
      outOfScope: ['family_5a_5b', 'online_pr_review_loop'],
      status: 'return_to_main_session',
      reason: 'missing_family_worktree',
      layers,
      reviewedSlices,
      mergeQueue,
      merge: mergeQueue.at(-1),
      i9: { status: 'aborted', reason: 'missing_family_worktree' }
    };
  }

  const familyVerification = await runFamilyIntegrationVerify({
    Bash,
    familyWorktree,
    verifyCommands: normalizedArgs.verifyCommands
  });
  if (familyVerification.status !== 'passed') {
    return {
      ...discovery,
      outOfScope: ['family_5a_5b', 'online_pr_review_loop'],
      status: 'family_verify_failed',
      layers,
      reviewedSlices,
      mergeQueue,
      merge: mergeQueue.at(-1),
      familyVerification,
      i9: { status: 'failed', reason: 'family_integration_verify_failed' }
    };
  }

  const baseManagement = await manageFamilyBase({
    Bash,
    familyWorktree,
    normalizedArgs,
    startupTargetHead
  });
  if (baseManagement.status === 'conflict') {
    return {
      ...discovery,
      outOfScope: ['family_5a_5b', 'online_pr_review_loop'],
      status: 'return_to_main_session',
      reason: baseManagement.reason ?? 'base_rebase_conflict',
      layers,
      reviewedSlices,
      mergeQueue,
      merge: mergeQueue.at(-1),
      familyVerification,
      baseManagement,
      i10: { status: 'aborted', reason: baseManagement.reason ?? 'base_rebase_conflict' }
    };
  }

  let familyVerificationAfterRebase;
  if (baseManagement.status === 'rebased') {
    familyVerificationAfterRebase = await runFamilyIntegrationVerify({
      Bash,
      familyWorktree,
      verifyCommands: normalizedArgs.verifyCommands
    });
    if (familyVerificationAfterRebase.status !== 'passed') {
      return {
        ...discovery,
        outOfScope: ['family_5a_5b', 'online_pr_review_loop'],
        status: 'family_verify_failed',
        layers,
        reviewedSlices,
        mergeQueue,
        merge: mergeQueue.at(-1),
        familyVerification,
        baseManagement,
        familyVerificationAfterRebase,
        i9: { status: 'failed', reason: 'family_integration_verify_failed_after_rebase' }
      };
    }
    const rebasedFamilyHead = baseManagement.rebaseHead;
    if (rebasedFamilyHead) {
      currentFamilyHead = rebasedFamilyHead;
      const finalMergeEntry = mergeQueue.at(-1);
      if (finalMergeEntry) {
        finalMergeEntry.mergeCommit = rebasedFamilyHead;
        finalMergeEntry.familyHead = rebasedFamilyHead;
      }
    }
  }

  phaseIfAvailable('Family Review');
  const familyReview = await runFamilyReview({
    Bash,
    runner,
    familyWorktree,
    familyBranch: normalizedArgs.familyBranch,
    epicIssueNumber: discovery.epicIssueNumber,
    maxReviewRounds: normalizedArgs.maxReviewRounds,
    verifyCommands: normalizedArgs.verifyCommands,
    diffBase: startupTargetHead,
    // S6: decision findings the user already ruled "doesn't count" (threaded from the prior segment's
    // handoff). They are excluded from the escalate count (no HALT) but remain in the full re-review.
    dismissed: normalizedArgs.dismissals
  });
  // Family review fix rounds add autonomous-fix commits that advance the family worktree HEAD.
  // Only then refresh the final merge entry so every exit reports the reviewed HEAD rather than
  // the stale pre-review merge commit (no fix round -> HEAD unchanged -> skip the rev-parse).
  const hadFixRound = Array.isArray(familyReview.rounds) && familyReview.rounds.some((entry) => entry.gate === 'fix');
  if (hadFixRound) {
    const reviewedFamilyHead = (await Bash(`set -euo pipefail\n# family-review reviewed HEAD\ngit -C ${shellQuote(familyWorktree)} rev-parse HEAD`)).trim();
    if (reviewedFamilyHead) currentFamilyHead = reviewedFamilyHead;
    const finalMergeEntry = mergeQueue.at(-1);
    if (finalMergeEntry && reviewedFamilyHead && finalMergeEntry.familyHead !== reviewedFamilyHead) {
      finalMergeEntry.mergeCommit = reviewedFamilyHead;
      finalMergeEntry.familyHead = reviewedFamilyHead;
    }
  }
  const familyPipelineTail = {
    layers,
    reviewedSlices,
    mergeQueue,
    merge: mergeQueue.at(-1),
    familyVerification,
    baseManagement,
    ...(familyVerificationAfterRebase ? { familyVerificationAfterRebase } : {}),
    // S6 continuation ledger (which slices this segment ran vs git-skipped vs re-ran dirty).
    continuation,
    i9: { status: 'passed', commands: normalizedArgs.verifyCommands },
    i10: { status: baseManagement.status, startupTargetHead, targetBranch: normalizedArgs.targetBranch }
  };

  if (familyReview.status === 'halt') {
    return {
      ...discovery,
      // halt = degradation before the gate ran, so family 5a/5b was NOT performed -> stays out of scope.
      // (escalate/abort/fix_verify_failed below DID run the gate, so they correctly drop it.)
      outOfScope: ['family_5a_5b', 'online_pr_review_loop'],
      status: 'return_to_main_session',
      reason: 'review_degraded',
      ...familyPipelineTail,
      familyReview,
      i2: { status: 'halt', stage: 'family_5a_5b', availableModels: familyReview.degradation.availableModels, missingModels: familyReview.degradation.missingModels }
    };
  }
  if (familyReview.status === 'escalate') {
    return {
      ...discovery,
      outOfScope: ['online_pr_review_loop'],
      status: 'return_to_main_session',
      reason: 'family_review_needs_decision',
      ...familyPipelineTail,
      familyReview,
      decisionFindings: familyReview.decisionFindings,
      i5: { status: 'escalated', reason: 'decision_findings', decisionFindings: familyReview.decisionFindings }
    };
  }
  if (familyReview.status === 'abort') {
    return {
      ...discovery,
      outOfScope: ['online_pr_review_loop'],
      status: 'return_to_main_session',
      reason: 'family_review_unconverged',
      ...familyPipelineTail,
      familyReview,
      i1: { status: 'aborted', reason: 'max_review_rounds', maxReviewRounds: normalizedArgs.maxReviewRounds }
    };
  }
  if (familyReview.status === 'fix_verify_failed') {
    return {
      ...discovery,
      outOfScope: ['online_pr_review_loop'],
      status: 'family_verify_failed',
      ...familyPipelineTail,
      familyReview,
      i9: { status: 'failed', reason: 'family_integration_verify_failed_after_review_fix' }
    };
  }

  // ── S5 Ship phase: gstack-ship (full) -> inlineShipOutcome (3 terminal states) -> handoff ──────
  // Reached only once the load-bearing family 5a/5b CMR has converged. The orchestrator drives
  // gstack-ship to completion (coverage/specialist/RedTeam gates + push + create the family PR; the
  // gates are non-skippable). gstack-ship has an internal ASK gate (version bump MINOR/MAJOR,
  // pre-landing ASK, coverage hard gate) -> on trigger the ship pauses for the user, no PR is built
  // -> terminal state needs-user. All three terminal states return to the main session with the
  // §段间交接 handoff payload (assembled via the drift-guarded inlineBuildHandoffPayload).
  // IRON RULE: "stop before online review" = the orchestrator NEVER drives the online bot multi-round
  // loop; creating the PR is the ship's last step (bots auto-arrive once the PR exists), the loop is
  // the main session's job. online_pr_review_loop stays out of scope on every Ship exit.
  phaseIfAvailable('Ship');

  // The merged-slice ledger for the handoff: reviewedSlices and mergeQueue are pushed in lockstep,
  // so zip slice issue number <-> its STABLE per-slice reviewed commit. We deliberately do NOT report
  // a per-slice family-branch hash here: an I10 rebase / family-review fix rewrites the family-branch
  // commits and only mergeQueue.at(-1) is refreshed, so per-slice family hashes go stale for every
  // non-final slice. The reviewedCommit (the slice's own review commit) is never rewritten by a family
  // rebase, and the current family tip is reported once as familyHead below — S6 probes
  // baseAtStart..familyHead against these reviewed commits.
  // This segment's freshly merged slices, zipped to their stable per-slice reviewed commit.
  const thisSegmentMerged = reviewedSlices.map((slice, index) => ({
    number: slice.plannedSlice.issueNumber,
    reviewedCommit: mergeQueue[index]?.reviewedCommit ?? null
  }));
  // CUMULATIVE ledger: the handoff feeds the NEXT relaunch's mergedNumbers, so it must carry every
  // slice already on the family branch — prior segments' merged slices (git-skipped this segment) PLUS
  // this segment's. A slice re-run this segment (dirty) is superseded by its fresh entry. Prior entries
  // carry reviewedCommit:null (the relaunch passed numbers, not the original review commits). Without
  // this, the next relaunch would re-run already-merged slices.
  const thisSegmentKeys = new Set(thisSegmentMerged.map((entry) => idKey(entry.number)));
  const priorMerged = normalizedArgs.mergedEntries
    .filter((entry) => !thisSegmentKeys.has(idKey(entry.number)))
    .map((entry) => ({ number: entry.number, reviewedCommit: entry.reviewedCommit }));
  const mergedSlices = [...priorMerged, ...thisSegmentMerged];
  // Degradation / absent-voice flags from the load-bearing family gate's converged round.
  const convergedRound = Array.isArray(familyReview.rounds) ? familyReview.rounds.at(-1) : undefined;
  const shipFlags = convergedRound?.degradation?.flags ?? [];
  // baseAtStart = the I10-verified startup target HEAD the family branched from (not the family's
  // own tip). rebaseHead is the family HEAD after an I10 rebase — a tip, not a base — so it must NOT
  // populate this field. The current family tip is reported separately as the top-level handoff
  // familyHead (captured AFTER gstack-ship below, since gstack-ship's version bump advances HEAD).
  const baseAtStart = startupTargetHead;

  const ship = await runFamilyShip({
    Bash,
    familyWorktree,
    targetBranch: normalizedArgs.targetBranch
  });

  // The last slice-merge tip (already refreshed post I10 rebase / family-review fix). This is the
  // correct family HEAD for the no-commit outcomes (needs-user / unconverged). On the READY path
  // gstack-ship bumps VERSION/CHANGELOG and commits, advancing HEAD past this, so ready requires
  // gstack-ship's reported post-ship head loudly (below) rather than silently accepting this stale tip.
  const mergeTip = currentFamilyHead;

  const outcome = inlineShipOutcome({ asked: ship.asked, gatesPassed: ship.gatesPassed, prCreated: ship.prCreated });

  // I8 observability + §段间交接: each terminal state's load-bearing detail field is its hard
  // acceptance — it must not silently go missing. gstack-ship report field -> handoff key:
  //   ready:      ship.prUrl     -> payload.prUrl     (family PR link)
  //   needs-user: ship.askDetail -> payload.question  (pending decision)
  //   unconverged:ship.shipDetail-> payload.detail    (blocking detail)
  // The terminal-detail field is conditional on the outcome, so validate it here and fail LOUDLY
  // (ADR 0005 / CLAUDE.md "fail loud") rather than handing back a null-load handoff to the main session.
  const requireShipDetail = (field, value, label) => {
    if (typeof value !== 'string' || value.trim() === '') {
      throw new Error(
        `epic-orchestrator Ship phase: terminal state "${outcome}" is missing load-bearing field ${field} (${label}) — ` +
          `gstack-ship report did not carry that payload, handoff incomplete. Fix the gstack-ship parse/output and rerun.`
      );
    }
    return value;
  };

  const handoffBase = {
    epic: discovery.epicIssueNumber,
    familyBranch: normalizedArgs.familyBranch,
    baseAtStart,
    merged: mergedSlices,
    dirty: [],
    flags: shipFlags
  };

  if (outcome === 'ready') {
    // ready: gates passed + family PR built by gstack-ship -> return to main session, which takes over
    // the online bot review loop (pr-review-loop, NOT in this script). The orchestrator ends the run
    // here: it does not create a PR itself (gstack-ship already did) and does not drive online review.
    const prUrl = requireShipDetail('prUrl', ship.prUrl, '家族 PR 链接');
    // ready means gstack-ship committed a version bump, so its post-ship HEAD is load-bearing — fail
    // loud if missing rather than silently reporting the stale pre-ship merge tip.
    const readyFamilyHead = requireShipDetail('familyHead', ship.familyHead, '家族 HEAD（gstack-ship 提交后）');
    log?.(`Ship ready: gstack-ship gates passed + family PR created (${prUrl}) -> end run, return to main session`);
    return {
      ...discovery,
      outOfScope: ['online_pr_review_loop'],
      status: 'ready',
      ...familyPipelineTail,
      familyReview: { status: 'converged', rounds: familyReview.rounds, round: familyReview.round },
      ship,
      handoff: inlineBuildHandoffPayload({ ...handoffBase, status: 'ready', prUrl, familyHead: readyFamilyHead })
    };
  }

  if (outcome === 'needs-user') {
    // needs-user: gstack-ship internal ASK gate fired (version / pre-landing / coverage hard gate),
    // the ship paused for the user, no PR -> end run, return to main session with the pending question.
    const question = requireShipDetail('askDetail', ship.askDetail, '待拍问题');
    log?.(`Ship needs-user: gstack-ship internal ASK fired (${question}) -> end run, return to main session`);
    return {
      ...discovery,
      outOfScope: ['online_pr_review_loop'],
      status: 'needs-user',
      ...familyPipelineTail,
      familyReview: { status: 'converged', rounds: familyReview.rounds, round: familyReview.round },
      ship,
      handoff: inlineBuildHandoffPayload({ ...handoffBase, status: 'needs-user', reason: 'gstack-ship-ask', question, familyHead: mergeTip })
    };
  }

  // unconverged: gates not passed / no PR and not an ASK -> stuck or unconverged (suspected
  // implementation/architecture problem) -> end run, return to main session with the blocking detail.
  const detail = requireShipDetail('shipDetail', ship.shipDetail, '卡点细节');
  log?.(`Ship unconverged: gstack-ship gates not passed or PR not created (${detail}) -> end run, return to main session`);
  return {
    ...discovery,
    outOfScope: ['online_pr_review_loop'],
    status: 'unconverged',
    ...familyPipelineTail,
    familyReview: { status: 'converged', rounds: familyReview.rounds, round: familyReview.round },
    ship,
    handoff: inlineBuildHandoffPayload({ ...handoffBase, status: 'unconverged', reason: 'gstack-ship-failed', detail, familyHead: mergeTip })
  };
}

// ── runFamilyShip: drive gstack-ship (full) on the family worktree and parse its three-gate result ──
//
// ⚠️ ASSUMED gstack-ship CONTRACT (NOT固化 in the repo — flagged unknown in the epic-orchestration
// blueprint; surface this to the user for confirmation / future dogfood verification):
//   Assumed COMMAND (run from the family worktree):
//     `gstack-ship --json --base <targetBranch>`  (a single non-interactive headless invocation that
//     runs the coverage/specialist/RedTeam gates, bumps VERSION/CHANGELOG, commits, pushes, and
//     creates the family PR — the gates are non-skippable; a rerun-on-prompt is auto-confirmed, not asked).
//   Assumed OUTPUT (one JSON object on stdout, human logs on stderr — same convention as codex exec):
//     { "asked": bool,          // gstack-ship internal ASK gate fired (version MINOR/MAJOR, pre-landing
//                               //   ASK, coverage hard gate) — ship paused for the user, PR not built
//       "gatesPassed": bool,    // coverage + specialist + RedTeam gates all passed (non-skippable)
//       "prCreated": bool,      // family PR was created by gstack-ship
//       "prUrl": string,        // (ready) the family PR link
//       "familyHead": string,   // (ready) the post-ship family HEAD after gstack-ship's version-bump
//                               //   commit (advances past the last slice merge; absent when no commit)
//       "askDetail": string,    // (asked) what is being asked (version / pre-landing / coverage)
//       "shipDetail": string }  // (gates failed / non-ASK ship failure) the blocking detail
//   If the assumed command/shape is wrong at dogfood time, only this function changes — the terminal-
//   state mapping (inlineShipOutcome) and handoff assembly (inlineBuildHandoffPayload) are契约-stable.
//
// This is an orchestration shell (dogfood-not-run): it writes the "orchestrator invokes gstack-ship"
// wiring; it does NOT actually run gstack-ship here. (Carrying a prior ASK decision across a rerun so
// the ship does not stop on the same question is S6's continuation concern — see #225 — and needs a
// real gstack-ship input channel; it is deliberately NOT faked here.)
async function runFamilyShip({ Bash, familyWorktree, targetBranch }) {
  return assertShipReport(parseShipJson(
    await Bash(
      `set -euo pipefail\ncd ${shellQuote(familyWorktree)}\n# reviewer=gstack-ship-family; run gstack-ship FULL on the merged family branch (coverage/specialist/RedTeam gates + push + create family PR; gates non-skippable). ASSUMED contract — see runFamilyShip comment. (branch/base are NOT interpolated into this comment — a newline would break out of it; base rides the command line via shellQuote below.)\n# gstack-ship exits nonzero on a failed gate / internal ASK but still prints its JSON report on\n# stdout — those ARE the needs-user / unconverged outcomes — so capture stdout under set +e rather\n# than letting pipefail abort before parseShipJson. A missing / unparseable report stays a loud\n# failure (parseShipJson throws), so a wrong assumed command still fails loud at dogfood time.\nset +e\nshipReport=$(gstack-ship --json --base ${shellQuote(targetBranch)} 2>/dev/null)\nset -e\nprintf '%s' "$shipReport"`
    )
  ));
}

// gstack-ship reports arbitrary external JSON; the outcome classifier (shipOutcome) keys on three
// booleans, so a malformed-but-parseable report (e.g. gatesPassed:"false" — a truthy string — or a
// missing boolean) would silently misclassify. Validate the contract loudly before classifying.
function assertShipReport(report) {
  if (report === null || typeof report !== 'object' || Array.isArray(report)) {
    throw new Error('epic-orchestrator Ship phase: gstack-ship report is not a JSON object — cannot classify the ship outcome.');
  }
  for (const field of ['asked', 'gatesPassed', 'prCreated']) {
    if (typeof report[field] !== 'boolean') {
      throw new Error(
        `epic-orchestrator Ship phase: gstack-ship report field "${field}" must be a boolean (got ${typeof report[field]}) — ` +
          `refusing to classify the ship outcome on a malformed report. Fix the gstack-ship parse/output and rerun.`
      );
    }
  }
  return report;
}

async function runSliceReviewLoop({ discovery, normalizedArgs, sliceBaseContext, plannedIssue, Bash, runner, log }) {
  const plannedSlice = {
    ...plannedIssue,
    isolation: 'worktree'
  };
  const implementations = [];
  const verificationAttempts = [];
  const reviewAttempts = [];
  const reviewFixCommits = [];
  let implementation;
  let implementedCommit;
  let worktreePath;
  let verification;
  let review;
  let observabilityEvidence;

  for (let round = 1; round <= normalizedArgs.maxReviewRounds; round += 1) {
    implementation = await runner({
      isolation: 'worktree',
      issueNumber: plannedSlice.issueNumber,
      issue: plannedSlice,
      ...(sliceBaseContext ?? {}),
      prompt:
        round === 1
          ? buildImplementationPrompt(discovery.epicIssueNumber, plannedSlice, sliceBaseContext)
          : buildReviewFixPrompt(discovery.epicIssueNumber, plannedSlice, implementations.at(-1)?.commit, review, round, normalizedArgs.maxReviewRounds, sliceBaseContext),
      ...(round === 1
        ? {}
        : {
            reviewFix: {
              failedCommit: implementations.at(-1)?.commit,
              failedReview: review,
              round,
              maxReviewRounds: normalizedArgs.maxReviewRounds
            }
          })
    });
    implementedCommit = implementation?.commit ?? implementation?.commitSha ?? implementation?.sha;
    worktreePath = implementation?.worktreePath ?? implementation?.path;
    if (!implementedCommit || !worktreePath) {
      throw new Error('实现腿必须返回 commit 和 worktreePath。');
    }
    const previousFailedCommit = implementations.at(-1)?.commit;
    if (implementations.length > 0 && implementedCommit === previousFailedCommit) {
      throw new Error('I7 要求每一轮 review-fix 返回新 commit，不能复用未通过评审的 commit。');
    }
    if (!isHiddenWorktreePath(worktreePath)) {
      throw new Error('实现 worktree 必须位于隐藏点目录下，以便 agy 评审明确只看 diff。');
    }
    observabilityEvidence = validateObservabilityEvidence(implementation?.observabilityEvidence);
    implementations.push({ commit: implementedCommit, worktreePath });
    if (round > 1) reviewFixCommits.push(implementedCommit);

    await Bash(`set -euo pipefail\n# 为切片执行 I7 commit 纪律检查 ${shellQuote(plannedSlice.issueNumber)} round ${shellQuote(round)}\nworktreePath=${shellQuote(worktreePath)}\nimplementedCommit=$(git -C "$worktreePath" rev-parse ${shellQuote(`${implementedCommit}^{commit}`)})\nexpectedHead=$(git -C "$worktreePath" rev-parse HEAD)\nif [ "$expectedHead" != "$implementedCommit" ]; then\n  printf '实现 worktree HEAD %s 与 implementedCommit %s 不一致\\n' "$expectedHead" "$implementedCommit" >&2\n  exit 1\nfi\ngit -C "$worktreePath" rev-list --parents -n 1 "$implementedCommit" | awk 'NF >= 2 { ok=1 } END { exit ok ? 0 : 1 }'${sliceBaseContext?.baseRef ? `\nbaseRef=$(git -C "$worktreePath" rev-parse ${shellQuote(`${sliceBaseContext.baseRef}^{commit}`)})\ngit -C "$worktreePath" merge-base --is-ancestor "$baseRef" "$implementedCommit"` : ''}${previousFailedCommit ? `\nfailedCommit=$(git -C "$worktreePath" rev-parse ${shellQuote(`${previousFailedCommit}^{commit}`)})\ngit -C "$worktreePath" merge-base --is-ancestor "$failedCommit" "$implementedCommit"` : ''}\nstatus=$(git -C "$worktreePath" status --porcelain)\nif [ -n "$status" ]; then\n  printf 'implementedCommit %s 之后实现 worktree 仍不干净：\\n%s\\n' "$implementedCommit" "$status" >&2\n  exit 1\nfi`);

    phaseIfAvailable('Verify');
    verification = await runVerification({ Bash, worktreePath, verifyCommands: normalizedArgs.verifyCommands });
    verificationAttempts.push({ commit: implementedCommit, ...verification });
    if (verification.status !== 'passed') {
      return {
        status: 'verify_failed',
        plannedSlice,
        implementation: { commit: implementedCommit, worktreePath },
        implementations,
        verification,
        verificationAttempts,
        i7: i7Evidence(implementedCommit, reviewFixCommits),
        i8: i8Evidence(observabilityEvidence)
      };
    }

    phaseIfAvailable('Review');
    review = await runPerSliceReview({ Bash, worktreePath, commit: implementedCommit, plannedSlice });
    reviewAttempts.push({ commit: implementedCommit, ...review });
    if (review.status === 'passed') {
      return {
        status: 'reviewed',
        plannedSlice,
        implementation: { commit: implementedCommit, worktreePath },
        implementations,
        verification,
        verificationAttempts,
        review,
        reviewAttempts,
        i7: i7Evidence(implementedCommit, reviewFixCommits),
        i8: i8Evidence(observabilityEvidence)
      };
    }

    if (round >= normalizedArgs.maxReviewRounds) {
      return {
        status: 'review_failed',
        plannedSlice,
        implementation: { commit: implementedCommit, worktreePath },
        implementations,
        verification,
        verificationAttempts,
        review,
        reviewAttempts,
        i1: { status: 'aborted', reason: 'max_review_rounds', maxReviewRounds: normalizedArgs.maxReviewRounds },
        i7: i7Evidence(implementedCommit, reviewFixCommits),
        i8: i8Evidence(observabilityEvidence)
      };
    }

    log?.(`#${plannedSlice.issueNumber} 单切片评审未通过；开始同切片 review-fix 第 ${round + 1}/${normalizedArgs.maxReviewRounds} 轮。`);
  }

  throw new Error(`runSliceReviewLoop exhausted without returning a reviewed or failed result for slice #${plannedSlice.issueNumber}; maxReviewRounds=${normalizedArgs.maxReviewRounds}.`);
}

function buildSliceBaseContext(normalizedArgs, mergeQueue, startupTargetHead) {
  const lastMerged = mergeQueue.at(-1);
  if (!lastMerged?.mergeCommit) {
    if (!startupTargetHead || startupTargetHead === 'unknown') return undefined;
    return {
      familyBranch: normalizedArgs.familyBranch,
      baseBranch: normalizedArgs.targetBranch,
      baseRef: startupTargetHead,
      startupTargetHead,
      targetBranch: normalizedArgs.targetBranch,
      mergeQueue: []
    };
  }
  return {
    familyBranch: normalizedArgs.familyBranch,
    baseBranch: normalizedArgs.familyBranch,
    baseRef: lastMerged.mergeCommit,
    lastMergeCommit: lastMerged.mergeCommit,
    startupTargetHead,
    targetBranch: normalizedArgs.targetBranch,
    mergeQueue: mergeQueue.map((entry) => ({
      status: entry.status,
      familyBranch: entry.familyBranch,
      reviewedCommit: entry.reviewedCommit,
      mergeCommit: entry.mergeCommit,
      mergeWorktree: entry.mergeWorktree
    }))
  };
}

async function mergeReviewedCommit({ Bash, worktreePath, familyBranch, implementedCommit, plannedSlice }) {
  return parseBashJson(
    await Bash(`set -euo pipefail\n# 将已评审 commit 合入家族分支；reviewer=merge reviewed commit\nsourceWorktreePath=${shellQuote(worktreePath)}\nfamilyBranch=${shellQuote(familyBranch)}\nimplementedCommit=${shellQuote(implementedCommit)}\ncommonDir=$(git -C "$sourceWorktreePath" rev-parse --path-format=absolute --git-common-dir)\nrepoRoot=$(git -C "$sourceWorktreePath" rev-parse --show-toplevel)\nparentRoot=$(dirname "$repoRoot")\nmergeRoot="$parentRoot/.epic-orchestrator"\nsafeBranch=$(printf '%s' "$familyBranch" | tr -c 'A-Za-z0-9._-' '_')\ndefaultMergeWorktree="$mergeRoot/family-$safeBranch"\nexistingMergeWorktree=$(python3 - "$sourceWorktreePath" "$familyBranch" <<'PY'\nimport subprocess, sys\nsource, branch = sys.argv[1], sys.argv[2]\ncurrent = None\nfor line in subprocess.check_output(['git', '-C', source, 'worktree', 'list', '--porcelain'], text=True).splitlines():\n    if line.startswith('worktree '):\n        current = line[9:]\n    elif line == f'branch refs/heads/{branch}' and current:\n        print(current)\n        break\nPY\n)\nif [ -n "$existingMergeWorktree" ]; then\n  mergeWorktree="$existingMergeWorktree"\nelse\n  mergeWorktree="$defaultMergeWorktree"\n  mkdir -p "$mergeRoot"\n  isOwnGitWorktree() { [ -e "$1/.git" ] && git -C "$1" rev-parse --path-format=absolute --git-common-dir >/dev/null 2>&1; }\nisExpectedFamilyWorktree() {\n  [ -e "$1/.git" ] || return 1\n  actualCommonDir=$(git -C "$1" rev-parse --path-format=absolute --git-common-dir) || return 1\n  actualBranch=$(git -C "$1" symbolic-ref --quiet --short HEAD) || return 1\n  [ "$actualCommonDir" = "$commonDir" ] && [ "$actualBranch" = "$familyBranch" ]\n}\n  if [ -e "$mergeWorktree" ] && ! isOwnGitWorktree "$mergeWorktree"; then\n    rm -rf "$mergeWorktree"\n  fi\n  if ! isOwnGitWorktree "$mergeWorktree"; then\n    git -C "$sourceWorktreePath" fetch origin "$familyBranch" || true\n    if git -C "$sourceWorktreePath" show-ref --verify --quiet "refs/heads/\${familyBranch}"; then\n      git -C "$sourceWorktreePath" worktree add "$mergeWorktree" "$familyBranch" >&2\n    elif git -C "$sourceWorktreePath" show-ref --verify --quiet "refs/remotes/origin/\${familyBranch}"; then\n      git -C "$sourceWorktreePath" worktree add -b "$familyBranch" "$mergeWorktree" "origin/\${familyBranch}" >&2\n    else\n      git -C "$sourceWorktreePath" worktree add -b "$familyBranch" "$mergeWorktree" "\${implementedCommit}^" >&2\n    fi\n  fi\nfi\nout=$(mktemp)\ntrap 'rm -f "$out"' EXIT\nset +e\ngit -C "$mergeWorktree" merge --no-ff "$implementedCommit" -m ${shellQuote(`合并已评审切片 #${plannedSlice.issueNumber}`)} >"$out" 2>&1\nrc=$?\nset -e\nif [ "$rc" -ne 0 ]; then\n  git -C "$mergeWorktree" merge --abort >/dev/null 2>&1 || true\n  python3 - "$rc" "$out" <<'PY'\nimport json, sys\nwith open(sys.argv[2], encoding='utf-8', errors='replace') as handle:\n    output = handle.read()\nprint(json.dumps({"status":"conflict", "reason":"merge_conflict", "exitCode": int(sys.argv[1]), "output": output}))\nPY\n  exit 0\nfi\nprintf '{"status":"merged","mergeCommit":"'\ngit -C "$mergeWorktree" rev-parse HEAD | tr -d '\\n'\nprintf '","mergeWorktree":"'\ngit -C "$mergeWorktree" rev-parse --show-toplevel | tr -d '\\n' | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1], end="")'\nprintf '"}'`)
  );
}

// S6 continuation: resolve the EXISTING family-branch worktree when no slice merged this segment
// (todoTotal===0 — every slice is already on the family branch, none dirty). Mirrors the worktree
// resolution in mergeReviewedCommit (existing worktree for the branch, else create one under
// <parent>/.epic-orchestrator/family-<safeBranch> from the local/remote family branch) but WITHOUT
// a merge — there is nothing new to merge, only the already-assembled family branch to verify/review/ship.
async function resolveExistingFamilyWorktree({ Bash, familyBranch }) {
  return parseBashJson(
    await Bash(`set -euo pipefail\n# resolve existing family worktree (S6 todoTotal=0 continuation)\nfamilyBranch=${shellQuote(familyBranch)}\nrepoRoot=$(git rev-parse --show-toplevel)\nparentRoot=$(dirname "$repoRoot")\nmergeRoot="$parentRoot/.epic-orchestrator"\nsafeBranch=$(printf '%s' "$familyBranch" | tr -c 'A-Za-z0-9._-' '_')\ndefaultMergeWorktree="$mergeRoot/family-$safeBranch"\nexistingMergeWorktree=$(python3 - "$repoRoot" "$familyBranch" <<'PY'\nimport subprocess, sys\nsource, branch = sys.argv[1], sys.argv[2]\ncurrent = None\nfor line in subprocess.check_output(['git', '-C', source, 'worktree', 'list', '--porcelain'], text=True).splitlines():\n    if line.startswith('worktree '):\n        current = line[9:]\n    elif line == f'branch refs/heads/{branch}' and current and current != source:\n        print(current)\n        break\nPY\n)\nif [ -n "$existingMergeWorktree" ]; then\n  mergeWorktree="$existingMergeWorktree"\nelse\n  mergeWorktree="$defaultMergeWorktree"\n  mkdir -p "$mergeRoot"\n  repoCommonDir=$(git -C "$repoRoot" rev-parse --path-format=absolute --git-common-dir)\n  isOwnGitWorktree() { [ -e "$1/.git" ] && [ "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" = "$repoCommonDir" ] && [ "$(git -C "$1" symbolic-ref --quiet --short HEAD 2>/dev/null)" = "$familyBranch" ]; }\n  if [ -e "$mergeWorktree" ] && ! isOwnGitWorktree "$mergeWorktree"; then\n    git -C "$repoRoot" worktree remove --force "$mergeWorktree" >/dev/null 2>&1 || rm -rf "$mergeWorktree"\n  fi\n  git -C "$repoRoot" worktree prune >/dev/null 2>&1 || true\n  if ! isOwnGitWorktree "$mergeWorktree"; then\n    git -C "$repoRoot" fetch origin "$familyBranch" || true\n    if git -C "$repoRoot" show-ref --verify --quiet "refs/heads/\${familyBranch}"; then\n      git -C "$repoRoot" worktree add "$mergeWorktree" "$familyBranch" >&2\n    elif git -C "$repoRoot" show-ref --verify --quiet "refs/remotes/origin/\${familyBranch}"; then\n      git -C "$repoRoot" worktree add -b "$familyBranch" "$mergeWorktree" "origin/\${familyBranch}" >&2\n    else\n      printf 'family branch %s not found locally or on origin — cannot resolve an existing family worktree for a continuation relaunch\\n' "$familyBranch" >&2\n      exit 1\n    fi\n  fi\nfi\nprintf '{"status":"resolved","familyWorktree":"'\ngit -C "$mergeWorktree" rev-parse --show-toplevel | tr -d '\\n' | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1], end="")'\nprintf '"}'`)
  );
}

function normalizePipelineArgs(rawArgs, epicIssueNumber) {
  const objectArgs = typeof rawArgs === 'object' && rawArgs !== null ? rawArgs : {};
  const requiredVerifyCommands = ['npm --prefix web run typecheck:orch', 'npm --prefix web test', 'npm --prefix web run build'];
  const extraVerifyCommands = Array.isArray(objectArgs.verifyCommands) ? objectArgs.verifyCommands.map((command) => String(command)) : [];
  const verifyCommands = [...new Set([...requiredVerifyCommands, ...extraVerifyCommands])];
  const mergedEntries = normalizeMergedEntries(objectArgs.mergedNumbers);
  return {
    familyBranch: assertShellSafeRef(String(objectArgs.familyBranch ?? `family/epic-${epicIssueNumber}`), 'familyBranch'),
    targetBranch: assertShellSafeRef(String(objectArgs.targetBranch ?? 'origin/main'), 'targetBranch'),
    startupTargetHead: objectArgs.startupTargetHead === undefined ? undefined : assertShellSafeRef(String(objectArgs.startupTargetHead), 'startupTargetHead'),
    verifyCommands,
    maxReviewRounds: normalizePositiveInteger(objectArgs.maxReviewRounds, 3, 'maxReviewRounds'),
    // S6 cross-segment continuation args, threaded back from the prior segment's handoff by the main
    // session. mergedNumbers = slices the family branch already has a commit for (relaunch git-skip);
    // dirty = merged slices ruled "rework" -> redo even with a commit; dismissals = decision findings
    // the user already ruled "doesn't count" -> no longer HALT (but still fully re-reviewed); decisions
    // = the user's cross-segment decision text (passed through for prompts/observability).
    // KEY DECISION (settled): mergedNumbers is passed in by the main session (NOT git-probed here) —
    // git probing the family branch as a self-verification backstop is a possible future addition
    // (blueprint risk #7) but is deliberately NOT the primary path.
    // mergedEntries preserves the prior handoff's {number, reviewedCommit} so the stable per-slice
    // reviewed commit survives a relaunch round-trip; mergedNumbers is derived for continuationPlan
    // membership. (A raw id carries reviewedCommit:null.)
    mergedEntries,
    mergedNumbers: mergedEntries.map((entry) => entry.number),
    dirty: normalizeIssueNumberList(objectArgs.dirty, 'dirty'),
    dismissals: normalizeDismissals(objectArgs.dismissals),
    decisions: objectArgs.decisions === undefined || objectArgs.decisions === null ? undefined : String(objectArgs.decisions)
  };
}

// Normalize the prior segment's merged ledger: accept raw ids OR handoff {number, reviewedCommit}
// entries, returning {number, reviewedCommit} (reviewedCommit:null for a raw id). Preserves the
// stable per-slice reviewed commit across a relaunch round-trip (handoff.merged -> mergedNumbers).
function normalizeMergedEntries(value) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new Error("epic-orchestrator: mergedNumbers must be an array of slice ids or handoff {number, reviewedCommit} entries.");
  }
  return value.map((element) => {
    const isObject = element !== null && typeof element === 'object';
    if (isObject && !('number' in element)) {
      throw new Error(`epic-orchestrator: mergedNumbers object element must carry a 'number' field (got keys: ${Object.keys(element).join(', ')}).`);
    }
    const raw = isObject ? element.number : element;
    const number = typeof raw === 'number' ? raw : String(raw);
    assertShellSafeRef(String(number), 'mergedNumbers element');
    const reviewedCommit = isObject && element.reviewedCommit !== undefined && element.reviewedCommit !== null ? String(element.reviewedCommit) : null;
    return { number, reviewedCommit };
  });
}

// S6 continuation issue-number lists (mergedNumbers / dirty). Each element is coerced to String/number
// and shell-safety-checked (refnames forbid newlines/control chars; these can flow into git/comments).
function normalizeIssueNumberList(value, name) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new Error(`epic-orchestrator: ${name} must be an array of slice issue numbers.`);
  }
  return value.map((element) => {
    // Accept both a raw id and the handoff's {number, ...} entry shape, so the prior segment's
    // handoff merged[] ({number, reviewedCommit}) / dirty[] ({number, decision}) round-trip directly
    // as mergedNumbers / dirty without the caller having to unwrap them (else they'd stringify to
    // '[object Object]' and silently never match a slice id).
    if (element !== null && typeof element === 'object' && !('number' in element)) {
      throw new Error(`epic-orchestrator: ${name} object element must carry a 'number' field (got keys: ${Object.keys(element).join(', ')}) — refusing to coerce it to '[object Object]'.`);
    }
    const raw = element !== null && typeof element === 'object' ? element.number : element;
    const normalized = typeof raw === 'number' ? raw : String(raw);
    assertShellSafeRef(String(normalized), `${name} element`);
    return normalized;
  });
}

// S6 dismissal list — each entry is {id?, claimQuote?, claim_quote?, location?} (the user's "doesn't
// count" ruling, matched by any one dimension). Only the four known fields are retained; the match
// happens in dismissalGate so no shell interpolation occurs, but they are stringified for safety.
function normalizeDismissals(value) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new Error('epic-orchestrator: dismissals must be an array of {id?, claimQuote?, claim_quote?, location?} entries.');
  }
  return value.map((entry) => {
    if (entry === null || typeof entry !== 'object') {
      throw new Error('epic-orchestrator: each dismissal must be an object with id / claimQuote / claim_quote / location.');
    }
    const normalized = {};
    if (entry.id !== undefined) normalized.id = String(entry.id);
    if (entry.claimQuote !== undefined) normalized.claimQuote = String(entry.claimQuote);
    if (entry.claim_quote !== undefined) normalized.claim_quote = String(entry.claim_quote);
    if (entry.location !== undefined) normalized.location = String(entry.location);
    return normalized;
  });
}

// git refs / branch names / SHAs are interpolated into Bash commands and Bash COMMENTS. shellQuote's
// single-quote escaping protects command args but NOT a comment (a POSIX `#` comment runs to the next
// newline, so a newline in the value would break out of the comment into executable shell). git
// refnames forbid newlines/control chars anyway, so reject them loudly at the source for every site.
function assertShellSafeRef(value, name) {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code < 0x20 || code === 0x7f) {
      throw new Error(`epic-orchestrator: ${name} contains a control character or newline — refusing (it would break Bash quoting/comment safety).`);
    }
  }
  return value;
}

function normalizePositiveInteger(value, fallback, name) {
  if (value === undefined || value === null || value === '') return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} 必须是正整数。`);
  }
  return parsed;
}

function buildImplementationPrompt(epicIssueNumber, plannedSlice, sliceBaseContext) {
  return [
    `Implement epic #${epicIssueNumber} slice #${plannedSlice.issueNumber}: ${plannedSlice.title ?? ''}`,
    'Use isolation:"worktree". Produce exactly one slice commit for the initial implementation.',
    ...baseContextPromptLines(sliceBaseContext),
    'I7: every review-fix round must be a new commit; never amend or squash review history.',
    'I8: enforce loud failures, locator logs, and gameplay DB consequences when applicable; for read-only/UI/tooling slices include substitute observability evidence.',
    'Return JSON-like data containing commit and worktreePath.'
  ].join('\n');
}

function buildReviewFixPrompt(epicIssueNumber, plannedSlice, failedCommit, failedReview, round, maxReviewRounds, sliceBaseContext) {
  return [
    `Fix epic #${epicIssueNumber} slice #${plannedSlice.issueNumber}: ${plannedSlice.title ?? ''}`,
    `Same-slice review-fix round ${round}/${maxReviewRounds}; previous reviewed commit ${failedCommit} did not pass per-slice review.`,
    `Review findings: ${JSON.stringify(failedReview)}`,
    'Use the same isolation:"worktree" and fix only this slice.',
    ...baseContextPromptLines(sliceBaseContext),
    'I7: create a NEW commit for this fix round; never amend, squash, or reuse the failed commit.',
    'After the fix the orchestrator will rerun local verify and codex+agy review.',
    'Return JSON-like data containing the new commit and worktreePath.'
  ].join('\n');
}

function baseContextPromptLines(sliceBaseContext) {
  if (!sliceBaseContext?.baseRef) return [];
  if ((sliceBaseContext.mergeQueue?.length ?? 0) === 0 && sliceBaseContext.startupTargetHead === sliceBaseContext.baseRef) {
    return [
      `Base this first-layer worktree on target branch ${sliceBaseContext.targetBranch} at orchestrator startup HEAD ${sliceBaseContext.baseRef} before implementing.`,
      'Do not start from a stale original epic base or any parent that does not contain the startup target HEAD.',
      `Family branch to be created/updated after review: ${sliceBaseContext.familyBranch}`
    ];
  }
  return [
    `Base this worktree on family branch ${sliceBaseContext.familyBranch} at ${sliceBaseContext.baseRef} before implementing; this includes all blockers merged in earlier dependency layers.`,
    'Do not start from the stale original epic base for this dependent-layer slice.',
    `Merged prerequisite queue: ${JSON.stringify(sliceBaseContext.mergeQueue)}`
  ];
}

async function captureStartupTargetHead({ Bash, normalizedArgs }) {
  if (normalizedArgs.startupTargetHead) return normalizedArgs.startupTargetHead;
  const parsed = parseBashJson(
    await Bash(`set -euo pipefail\n# orchestrator base target HEAD capture\ntargetBranch=${shellQuote(normalizedArgs.targetBranch)}\ntargetRemote=\${targetBranch%%/*}\ntargetRemoteBranch=\${targetBranch#*/}\nif [ "$targetRemote" != "$targetBranch" ] && [ -n "$targetRemote" ] && [ -n "$targetRemoteBranch" ]; then\n  git fetch "$targetRemote" "+refs/heads/$targetRemoteBranch:refs/remotes/$targetRemote/$targetRemoteBranch" >/dev/null 2>&1 || true\nfi\nhead=$(git rev-parse "\${targetBranch}^{commit}")\nprintf '{"status":"captured","targetBranch":'\nprintf '%s' "$targetBranch" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()), end="")'\nprintf ',"head":"%s"}' "$head"`)
  );
  return parsed.head ?? parsed.targetHead ?? 'unknown';
}

async function runFamilyIntegrationVerify({ Bash, familyWorktree, verifyCommands }) {
  const results = [];
  for (const command of verifyCommands) {
    const parsed = parseBashJson(
      await Bash(`set -euo pipefail\n# 家族集成 verify (I9): merged family branch whole-repo verification\ncd ${shellQuote(familyWorktree)}\nout=$(mktemp)\ntrap 'rm -f "$out"' EXIT\nset +e\n( ${command} ) >"$out" 2>&1\nrc=$?\npython3 - "$rc" "$out" <<'PY'\nimport json, sys\nrc = int(sys.argv[1])\nwith open(sys.argv[2], encoding='utf-8', errors='replace') as handle:\n    output = handle.read()\nprint(json.dumps({"status": "passed" if rc == 0 else "failed", "exitCode": rc, "output": output}))\nPY`)
    );
    results.push({ command, ...parsed });
    if (parsed.status && parsed.status !== 'passed') {
      return { status: 'failed', commands: verifyCommands, results };
    }
  }
  return { status: 'passed', commands: verifyCommands, results };
}

async function manageFamilyBase({ Bash, familyWorktree, normalizedArgs, startupTargetHead }) {
  return parseBashJson(
    await Bash(`set -euo pipefail\n# base management (I10): compare startup target HEAD before family CMR/gstack-ship\nfamilyWorktree=${shellQuote(familyWorktree)}\ntargetBranch=${shellQuote(normalizedArgs.targetBranch)}\nstartupTargetHead=${shellQuote(startupTargetHead)}\ntargetRemote=\${targetBranch%%/*}\ntargetRemoteBranch=\${targetBranch#*/}\nif [ "$targetRemote" != "$targetBranch" ] && [ -n "$targetRemote" ] && [ -n "$targetRemoteBranch" ]; then\n  git -C "$familyWorktree" fetch "$targetRemote" "+refs/heads/$targetRemoteBranch:refs/remotes/$targetRemote/$targetRemoteBranch" >/dev/null 2>&1 || true\nfi\ncurrentTargetHead=$(git -C "$familyWorktree" rev-parse "\${targetBranch}^{commit}")\nfamilyHead=$(git -C "$familyWorktree" rev-parse HEAD)\nif [ "$startupTargetHead" = "unknown" ]; then\n  printf '{"status":"conflict","reason":"startup_target_head_unresolved","currentTargetHead":"%s","familyHead":"%s"}' "$currentTargetHead" "$familyHead"\n  exit 0\nfi\nif [ "$startupTargetHead" != "unknown" ] && ! git -C "$familyWorktree" merge-base --is-ancestor "$startupTargetHead" "$familyHead"; then\n  printf '{"status":"conflict","reason":"family_missing_startup_target_head","startupTargetHead":"%s","currentTargetHead":"%s","familyHead":"%s"}' "$startupTargetHead" "$currentTargetHead" "$familyHead"\n  exit 0\nfi\nif [ "$startupTargetHead" = "unknown" ] || [ "$currentTargetHead" = "$startupTargetHead" ]; then\n  printf '{"status":"no_drift","startupTargetHead":"%s","currentTargetHead":"%s","familyHead":"%s"}' "$startupTargetHead" "$currentTargetHead" "$familyHead"\n  exit 0\nfi\nif ! git -C "$familyWorktree" merge-base --is-ancestor "$startupTargetHead" "$currentTargetHead"; then\n  printf '{"status":"conflict","reason":"target_base_not_fast_forward","startupTargetHead":"%s","currentTargetHead":"%s","familyHead":"%s"}' "$startupTargetHead" "$currentTargetHead" "$familyHead"\n  exit 0\nfi\nout=$(mktemp)\ntrap 'rm -f "$out"' EXIT\nset +e\ngit -C "$familyWorktree" rebase "$currentTargetHead" >"$out" 2>&1\nrc=$?\nset -e\nif [ "$rc" -ne 0 ]; then\n  git -C "$familyWorktree" rebase --abort >/dev/null 2>&1 || true\n  python3 - "$rc" "$out" "$startupTargetHead" "$currentTargetHead" <<'PY'\nimport json, sys\nwith open(sys.argv[2], encoding='utf-8', errors='replace') as handle:\n    output = handle.read()\nprint(json.dumps({"status": "conflict", "reason": "base_rebase_conflict", "exitCode": int(sys.argv[1]), "output": output, "startupTargetHead": sys.argv[3], "currentTargetHead": sys.argv[4]}))\nPY\n  exit 0\nfi\nrebaseHead=$(git -C "$familyWorktree" rev-parse HEAD)\nprintf '{"status":"rebased","startupTargetHead":"%s","currentTargetHead":"%s","rebaseHead":"%s"}' "$startupTargetHead" "$currentTargetHead" "$rebaseHead"`)
  );
}

// 5a/5b family CMR (I2 squad + I5 routing + I1 abort). Runs codex + Claude + agy on the
// MERGED family worktree (under the hidden .epic-orchestrator path → agy reviews the diff
// only, no repo grounding; codex reads the repo via codex exec regardless).
// codex + agy run via Bash; the Claude leg runs via the workflow agent() runner (a sibling
// review subagent). Mechanical-only findings drive an autonomous fix (re-run family verify +
// re-run 5a/5b) until a round with no new finding; decision findings escalate to the main
// session; the fix budget is bounded by maxReviewRounds (I1 abort).
async function runFamilyReview({ Bash, runner, familyWorktree, familyBranch, epicIssueNumber, maxReviewRounds, verifyCommands, diffBase, dismissed = [] }) {
  const rounds = [];
  for (let round = 1; round <= maxReviewRounds; round += 1) {
    const cmr = await runFamilyCmrRound({ Bash, runner, familyWorktree, familyBranch, epicIssueNumber, round, diffBase });
    if (cmr.degradation.status === 'halt') {
      return { status: 'halt', round, rounds, degradation: cmr.degradation, reviewers: cmr.reviewers };
    }

    const route = inlineRouteFindings(cmr.findings);
    // S6 dismissal gate (I5 false-positive non-loop): a decision finding the user already ruled
    // "doesn't count" no longer drives escalation. The finding stays in route.decisionFindings AND in
    // cmr.reviewers (full re-review discipline — we do not delete it); it is only filtered out of the
    // escalate count, so a previously-ruled decision can no longer HALT the run on re-raise.
    const escalatableDecisionFindings = route.decisionFindings.filter((finding) => inlineDismissalGate({ finding, dismissed }));
    const gate = inlineFamilyReviewGate({
      escalateCount: escalatableDecisionFindings.length,
      mechanicalCount: route.autonomousBugFindings.length,
      round,
      maxRounds: maxReviewRounds
    });
    rounds.push({ round, reviewers: cmr.reviewers, route, gate, degradation: cmr.degradation });

    if (gate === 'converged') {
      return { status: 'converged', round, rounds };
    }
    if (gate === 'escalate') {
      return { status: 'escalate', round, rounds, decisionFindings: escalatableDecisionFindings };
    }
    if (gate === 'abort') {
      return { status: 'abort', round, rounds, maxReviewRounds };
    }

    // gate === 'fix': capture HEAD, autonomously repair mechanical bugs, then enforce the I7
    // commit discipline (a new descendant commit + clean worktree) before re-running family verify.
    const preFixHead = (await Bash(`set -euo pipefail\n# family-review pre-fix HEAD\ngit -C ${shellQuote(familyWorktree)} rev-parse HEAD`)).trim();
    await runner({
      role: 'family_review_fix',
      familyWorktree,
      familyBranch,
      issueNumber: epicIssueNumber,
      round,
      maxReviewRounds,
      autonomousBugFindings: route.autonomousBugFindings,
      prompt: buildFamilyReviewFixPrompt(epicIssueNumber, familyBranch, route.autonomousBugFindings, round, maxReviewRounds)
    });
    await Bash(`set -euo pipefail\n# family-review I7 fix-commit discipline round ${shellQuote(String(round))}\nworktree=${shellQuote(familyWorktree)}\npreFixHead=$(git -C "$worktree" rev-parse ${shellQuote(`${preFixHead}^{commit}`)})\npostFixHead=$(git -C "$worktree" rev-parse HEAD)\nif [ "$postFixHead" = "$preFixHead" ]; then\n  printf 'family_review_fix round %s produced no new commit (HEAD still %s)\\n' ${shellQuote(String(round))} "$postFixHead" >&2\n  exit 1\nfi\ngit -C "$worktree" merge-base --is-ancestor "$preFixHead" "$postFixHead"\ndirty=$(git -C "$worktree" status --porcelain)\nif [ -n "$dirty" ]; then\n  printf 'family worktree not clean after family_review_fix round %s:\\n%s\\n' ${shellQuote(String(round))} "$dirty" >&2\n  exit 1\nfi`);
    const fixVerification = await runFamilyIntegrationVerify({
      Bash,
      familyWorktree,
      verifyCommands
    });
    rounds.at(-1).fixVerification = fixVerification;
    if (fixVerification.status !== 'passed') {
      return { status: 'fix_verify_failed', round, rounds, fixVerification };
    }
  }
  // Unreachable: the final round (round === maxReviewRounds) always resolves to converged/escalate/
  // abort inside the loop, because the gate never returns 'fix' once round === maxRounds (round < max is false).
  throw new Error('family review loop exited without a terminal decision');
}

async function runFamilyCmrRound({ Bash, runner, familyWorktree, familyBranch, epicIssueNumber, round, diffBase }) {
  const codex = await runFamilyCodexLeg({ Bash, familyWorktree, familyBranch, diffBase });
  const agy = await runFamilyAgyLeg({ Bash, familyWorktree, familyBranch, diffBase });
  const claude = await runFamilyClaudeLeg({ runner, familyWorktree, familyBranch, epicIssueNumber, round, diffBase });

  const reviewers = [
    { model: 'codex', available: codex.available, reason: codex.reason, fullGrounding: true, findings: codex.findings },
    { model: 'claude', available: claude.available, reason: claude.reason, findings: claude.findings },
    // agy refuses hidden (dot-path) workspaces and the family worktree lives under .epic-orchestrator,
    // so the agy leg reviews the diff only (no repo grounding).
    { model: 'agy', available: agy.available, reason: agy.reason, fullGrounding: false, diffOnly: true, findings: agy.findings }
  ];
  const degradation = inlineJudgeFamilyDegradation(
    reviewers.map((reviewer) => ({ model: reviewer.model, available: reviewer.available, reason: reviewer.reason }))
  );
  const findings = reviewers
    .filter((reviewer) => reviewer.available)
    .flatMap((reviewer) => (Array.isArray(reviewer.findings) ? reviewer.findings : []));
  return { reviewers, degradation, findings };
}

// Shell expr for the family CMR diff base: prefer the I10 startup target HEAD threaded in,
// falling back to merge-base origin/main (then HEAD^/HEAD) only when no base was provided.
function familyDiffBaseExpr(diffBase) {
  const fallback = 'git merge-base origin/main HEAD 2>/dev/null || git rev-parse HEAD^ 2>/dev/null || git rev-parse HEAD';
  if (!diffBase) return `$(${fallback})`;
  return `$(git rev-parse ${shellQuote(`${diffBase}^{commit}`)} 2>/dev/null || ${fallback})`;
}

async function runFamilyCodexLeg({ Bash, familyWorktree, familyBranch, diffBase }) {
  const baseExpr = familyDiffBaseExpr(diffBase);
  try {
    const parsed = parseReviewerJson(
      await Bash(`set -euo pipefail\ncd ${shellQuote(familyWorktree)}\n# reviewer=codex-family; 5a/5b family CMR on merged family branch (codex reads the repo via codex exec, unaffected by the hidden worktree path)\n{\n  printf '%s\\n' 'Review the merged family branch diff for cross-slice completeness (5a) and correctness regressions (5b).'\n  printf '%s\\n' 'Return only one JSON object on stdout with shape {"status":"passed"|"failed","findings":[{"id":...,"classification":"mechanical_bug"|"choice","claim_quote":...,"location":...}]}. Do not include markdown or prose outside the JSON object.'\n  printf '%s\\n' 'Diff stat against the startup target base for human context:'\n  git diff --stat ${baseExpr} HEAD\n  printf '%s\\n' 'Full diff:'\n  git diff ${baseExpr} HEAD\n} | codex exec --skip-git-repo-check --ephemeral -`),
      'codex-family'
    );
    return { available: true, findings: parsed.findings ?? [] };
  } catch (error) {
    return { available: false, reason: error?.message ?? 'codex family leg unavailable', findings: [] };
  }
}

async function runFamilyAgyLeg({ Bash, familyWorktree, familyBranch, diffBase }) {
  const baseExpr = familyDiffBaseExpr(diffBase);
  try {
    const parsed = parseReviewerJson(
      await Bash(`set -euo pipefail\ncd ${shellQuote(familyWorktree)}\n# reviewer=agy-family; diff-based review only (agy refuses the hidden .epic-orchestrator worktree, so no repo grounding). Review instructions + JSON schema go on stdin; agy is agentic, so a hard read-only constraint is mandatory.\n{\n  printf '%s\\n' 'REVIEW ONLY — HARD CONSTRAINT. Do NOT modify, create, rename, or delete any file; do NOT run commands. Output only the review.'\n  printf '%s\\n' 'Review the merged family branch diff for cross-slice completeness (5a) and correctness regressions (5b).'\n  printf '%s\\n' 'Return only one JSON object on stdout with shape {"status":"passed"|"failed","findings":[{"id":...,"classification":"mechanical_bug"|"choice","claim_quote":...,"location":...}]}. Do not include markdown or prose outside the JSON object.'\n  printf '%s\\n' 'Diff stat for context:'\n  git diff --stat ${baseExpr} HEAD\n  printf '%s\\n' 'Full diff:'\n  git diff ${baseExpr} HEAD\n} | agy --sandbox --diff-only --print ''`),
      'agy-family'
    );
    return { available: true, findings: parsed.findings ?? [] };
  } catch (error) {
    return { available: false, reason: error?.message ?? 'agy family leg unavailable', findings: [] };
  }
}

async function runFamilyClaudeLeg({ runner, familyWorktree, familyBranch, epicIssueNumber, round, diffBase }) {
  try {
    const review = await runner({
      role: 'family_review',
      familyWorktree,
      familyBranch,
      issueNumber: epicIssueNumber,
      round,
      diffBase,
      prompt: buildFamilyReviewPrompt(epicIssueNumber, familyBranch, round, diffBase)
    });
    if (!review || review.available === false) {
      return { available: false, reason: review?.reason ?? 'claude family review leg unavailable', findings: [] };
    }
    return { available: true, findings: review.findings ?? [] };
  } catch (error) {
    return { available: false, reason: error?.message ?? 'claude family review leg unavailable', findings: [] };
  }
}

function buildFamilyReviewPrompt(epicIssueNumber, familyBranch, round, diffBase) {
  return [
    `Family 5a/5b CMR (round ${round}) for epic #${epicIssueNumber} on merged family branch ${familyBranch}.`,
    diffBase ? `Review the cumulative diff of the family branch against its startup target base ${diffBase} (git diff ${diffBase} HEAD).` : 'Review the cumulative diff of the family branch against its startup target base (git merge-base origin/main HEAD).',
    'You are the Claude review leg. Review the merged family branch for cross-slice completeness (5a) and correctness regressions (5b).',
    'Classify each finding: mechanical_bug (one correct fix) vs choice (design/architecture/ADR — escalate). Ambiguous defaults to choice.',
    'Return data containing findings:[{id, classification, claim_quote, location}]; empty findings means no new issue this round.'
  ].join('\n');
}

function buildFamilyReviewFixPrompt(epicIssueNumber, familyBranch, autonomousBugFindings, round, maxReviewRounds) {
  return [
    `Autonomously fix mechanical bugs on family branch ${familyBranch} for epic #${epicIssueNumber} (fix round ${round}/${maxReviewRounds}).`,
    `Mechanical bug findings: ${JSON.stringify(autonomousBugFindings)}`,
    'Fix only these mechanical bugs in the merged family worktree; the orchestrator will rerun family integration verify and re-run 5a/5b.',
    'I7: each fix round is a new commit; never amend or squash family review history.'
  ].join('\n');
}

async function runVerification({ Bash, worktreePath, verifyCommands }) {
  const results = [];
  for (const command of verifyCommands) {
    const parsed = parseBashJson(
      await Bash(`set -euo pipefail\ncd ${shellQuote(worktreePath)}\nout=$(mktemp)\ntrap 'rm -f "$out"' EXIT\nset +e\n( ${command} ) >"$out" 2>&1\nrc=$?\npython3 - "$rc" "$out" <<'PY'\nimport json, sys\nrc = int(sys.argv[1])\nwith open(sys.argv[2], encoding='utf-8', errors='replace') as handle:\n    output = handle.read()\nprint(json.dumps({"status": "passed" if rc == 0 else "failed", "exitCode": rc, "output": output}))\nPY`)
    );
    results.push({ command, ...parsed });
    if (parsed.status && parsed.status !== 'passed') {
      return { status: 'failed', commands: verifyCommands, results };
    }
  }
  return { status: 'passed', commands: verifyCommands, results };
}

async function runPerSliceReview({ Bash, worktreePath, commit, plannedSlice }) {
  const codex = parseReviewerJson(
    await Bash(`set -euo pipefail\ncd ${shellQuote(worktreePath)}\n# reviewer=codex; full grounding fallback enabled: inspect repo files if diff alone is insufficient\n{\n  printf '%s\\n' 'Review the following git diff for correctness regressions.'\n  printf '%s\\n' 'Return only one JSON object on stdout with shape {"status":"passed"|"failed","findings":[...]}. Do not include markdown, prose, or diff-stat text outside the JSON object.'\n  printf '%s\\n' 'Diff stat for human context:'\n  git diff --stat ${shellQuote(`${commit}^`)} ${shellQuote(commit)}\n  printf '%s\\n' 'Full diff:'\n  git diff ${shellQuote(`${commit}^`)} ${shellQuote(commit)}\n} | codex exec --skip-git-repo-check --ephemeral -`),
    'codex'
  );
  const agy = parseReviewerJson(
    await Bash(`set -euo pipefail\ncd ${shellQuote(worktreePath)}\n# reviewer=agy; hidden worktree path forces diff-only review\ngit diff ${shellQuote(`${commit}^`)} ${shellQuote(commit)} | agy -p --sandbox --diff-only`),
    'agy'
  );
  const reviewers = [
    { model: 'codex', status: reviewStatus(codex), groundingFallback: true, findings: codex.findings ?? [] },
    { model: 'agy', status: reviewStatus(agy), diffOnly: true, hiddenWorktree: true, findings: agy.findings ?? [] }
  ];
  const failed = reviewers.find((reviewer) => reviewer.status !== 'passed');
  return {
    status: failed ? 'failed' : 'passed',
    sliceIssueNumber: plannedSlice.issueNumber,
    reviewers,
    flags: ['per-slice review uses codex+agy via Bash', 'agy is diff-only for hidden-dot worktrees', 'codex has full grounding fallback']
  };
}

function reviewStatus(reviewResult) {
  if (Array.isArray(reviewResult.findings) && reviewResult.findings.length > 0) return 'failed';
  return reviewResult.status === 'passed' ? 'passed' : 'failed';
}

function isHiddenWorktreePath(worktreePath) {
  return String(worktreePath).split('/').some((part) => part.startsWith('.') && part.length > 1);
}

function i7Evidence(commit, reviewFixCommits = []) {
  const evidence = { sliceCommit: commit, amendmentsForbidden: true, reviewFixesRequireNewCommits: true };
  if (reviewFixCommits.length > 0) evidence.reviewFixCommits = reviewFixCommits;
  return evidence;
}

function validateObservabilityEvidence(evidence) {
  if (!evidence || evidence.loudFailure !== true || evidence.locatorLogs !== true) {
    throw new Error('I8 可观测性证据必须包含 loudFailure:true 和 locatorLogs:true。');
  }
  if (!evidence.gameplayDbConsequences && !evidence.notApplicableReason) {
    throw new Error('I8 可观测性证据必须包含 gameplayDbConsequences；只读/UI/工具切片可改填 notApplicableReason。');
  }
  return evidence;
}

function i8Evidence(evidence) {
  return {
    required: true,
    loudFailure: evidence.loudFailure,
    locatorLogs: evidence.locatorLogs,
    gameplayDbConsequences: evidence.gameplayDbConsequences ?? 'N/A',
    notApplicableReason: evidence.notApplicableReason
  };
}

function buildOrderedExecutionPlan(topology, issueMetadata) {
  if (topology.status !== 'ready') return [];
  return topology.layers.map((layer, index) => ({
    layer: index + 1,
    issueNumbers: layer,
    issues: layer.map((issueId) => ({ issueNumber: issueId, ...(issueMetadata[idKey(issueId)] ?? {}) }))
  }));
}

function describeBoundaryHandling(topology) {
  if (topology.status === 'external_prerequisite') {
    return {
      action: 'return_to_main_session',
      reason: 'one or more unresolved blockers are outside this epic',
      externalPrerequisites: topology.externalPrerequisites
    };
  }
  return {
    action: 'continue',
    skippedClosedIssueIds: topology.skippedClosedIssueIds,
    note: 'empty epic and cycles throw TopologyError; closed child issues are skipped; closed blockers are treated as satisfied'
  };
}

function parseBashJson(raw) {
  const output = bashText(raw);
  if (output !== null) return JSON.parse(output);
  throw new Error('Bash did not return JSON output.');
}

function parseReviewerJson(raw, reviewerName) {
  const output = bashText(raw);
  if (output === null) throw new Error(`${reviewerName} review did not return output.`);

  try {
    return JSON.parse(output);
  } catch (fullOutputError) {
    const trimmed = output.trim();
    for (let index = trimmed.lastIndexOf('{'); index >= 0; index = index === 0 ? -1 : trimmed.lastIndexOf('{', index - 1)) {
      try {
        return JSON.parse(trimmed.slice(index));
      } catch {
        // Keep scanning for a trailing reviewer JSON object after human context.
      }
    }
    const lines = trimmed.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).reverse();
    for (const line of lines) {
      if (!line.startsWith('{') || !line.endsWith('}')) continue;
      try {
        return JSON.parse(line);
      } catch {
        // Keep scanning for the explicit reviewer JSON object.
      }
    }
    throw new Error(`${reviewerName} review did not return parseable reviewer JSON: ${fullOutputError.message}`);
  }
}

// Parse gstack-ship's JSON report off stdout. gstack-ship is assumed (see runFamilyShip) to print
// human progress on stderr and one JSON object on stdout, but the exact stdout framing is an assumed
// contract — so scan for a trailing JSON object the same way parseReviewerJson does, tolerating any
// preceding human context, and fail loudly when nothing parses (ADR 0005 — never swallow a bad report).
function parseShipJson(raw) {
  const output = bashText(raw);
  if (output === null) throw new Error('gstack-ship did not return output.');
  try {
    return JSON.parse(output);
  } catch (fullOutputError) {
    const trimmed = output.trim();
    for (let index = trimmed.lastIndexOf('{'); index >= 0; index = index === 0 ? -1 : trimmed.lastIndexOf('{', index - 1)) {
      try {
        return JSON.parse(trimmed.slice(index));
      } catch {
        // Keep scanning for a trailing gstack-ship JSON object after human context.
      }
    }
    const lines = trimmed.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).reverse();
    for (const line of lines) {
      if (!line.startsWith('{') || !line.endsWith('}')) continue;
      try {
        return JSON.parse(line);
      } catch {
        // Keep scanning for the explicit gstack-ship JSON object.
      }
    }
    throw new Error(`gstack-ship did not return parseable JSON: ${fullOutputError.message}`);
  }
}

function bashText(raw) {
  if (typeof raw === 'string') return raw;
  if (raw && typeof raw.output === 'string') return raw.output;
  if (raw && typeof raw.stdout === 'string') return raw.stdout;
  return null;
}

function phaseIfAvailable(title) {
  if (typeof phase !== 'undefined') phase(title);
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

if (typeof args !== 'undefined') {
  await runEpicLayeredPipeline({
    args,
    Bash,
    agent: typeof agent !== 'undefined' ? agent : undefined,
    log
  });
}
