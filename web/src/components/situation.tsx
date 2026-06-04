import React from "react";
import { createPortal } from "react-dom";
import { formatClosedEffect, formatIssueEffect, issueTone } from "../format";
import type { ClosedIssue, Issue } from "../types";

// 局势分组：长期(贯穿一朝大计) vs 近期。纯前端按 fail_condition 文案判定。
export function groupIssues(issues: Issue[]) {
  const active = issues.filter((i) => i.kind === "situation" || i.kind === "initiative");
  const bySeq = (a: Issue, b: Issue) => {
    if (a.kind !== b.kind) return a.kind === "initiative" ? -1 : 1;
    return a.id - b.id;
  };
  const isLongTerm = (i: Issue) => /甲申|贯穿一朝|倾国之大计/.test(i.fail_condition || "");
  return {
    active,
    longTerm: active.filter(isLongTerm).sort(bySeq),
    nearTerm: active.filter((i) => !isLongTerm(i)).sort(bySeq),
  };
}

export function SituationPanel({ issues, closedIssues, hasLegacies }: {
  issues: Issue[];
  closedIssues: ClosedIssue[];
  hasLegacies: boolean;
}) {
  const { active, longTerm, nearTerm } = groupIssues(issues);
  if (!active.length && !closedIssues.length) return null;
  return (
    <aside className={`situation-panel ${hasLegacies ? "with-legacies" : ""}`} aria-label="局势进度">
      {closedIssues.length ? (
        <div className="situation-closed-list">
          {closedIssues.map((ci) => (
            <div className={`situation-closed-row ${ci.status}`} key={`closed-${ci.id}`} tabIndex={0}>
              <div className="situation-closed-head">
                <span className="situation-closed-badge">{ci.status === "resolved" ? "已结案" : ci.status === "failed" ? "已崩坏" : "已撤"}</span>
                <span className="situation-closed-name">{ci.title}</span>
              </div>
              <div className="situation-closed-effect">{formatClosedEffect(ci.effect)}</div>
            </div>
          ))}
        </div>
      ) : null}
      {longTerm.length ? (
        <div className="situation-group">
          <div className="situation-group-title">长期局势</div>
          <div className="situation-list">
            {longTerm.map((issue) => <SituationRow key={issue.id} issue={issue} />)}
          </div>
        </div>
      ) : null}
      {nearTerm.length ? (
        <div className="situation-group">
          <div className="situation-group-title">近期局势</div>
          <div className="situation-list">
            {nearTerm.map((issue) => <SituationRow key={issue.id} issue={issue} />)}
          </div>
        </div>
      ) : null}
    </aside>
  );
}

export function SituationRow({ issue }: { issue: Issue }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [tipPos, setTipPos] = React.useState<{ x: number; y: number } | null>(null);
  const [detail, setDetail] = React.useState(false);
  const suppressRef = React.useRef(false);  // 关弹窗后抑制 tip，直到鼠标移出再进
  const showTip = () => {
    if (detail || suppressRef.current) return;
    const r = ref.current?.getBoundingClientRect();
    if (r) setTipPos({ x: r.right + 12, y: r.top });
  };
  const hideTip = () => { setTipPos(null); suppressRef.current = false; };  // 鼠标移出，解抑制
  const closeDetail = () => {
    setDetail(false);
    setTipPos(null);
    suppressRef.current = true;  // 关弹窗时鼠标多半还在行上，抑制到下次移出
  };
  return (
    <div ref={ref} className={`situation-row ${issueTone(issue.bar_value)}`} tabIndex={0}
      onClick={() => { setDetail(true); setTipPos(null); }} role="button"
      onMouseEnter={showTip} onMouseLeave={hideTip} onFocus={showTip} onBlur={hideTip}>
      <div className="situation-row-head">
        <span className="situation-name">{issue.title}</span>
        <b>{issue.bar_value}</b>
      </div>
      <div className="situation-bar">
        <i style={{ width: `${Math.max(0, Math.min(100, issue.bar_value))}%` }} />
      </div>
      {tipPos && !detail ? <SituationTip issue={issue} pos={tipPos} /> : null}
      {detail ? <SituationDetailModal issue={issue} onClose={closeDetail} /> : null}
    </div>
  );
}


// 局势悬浮框（精简）：只显数值，hover 触发。详细达成/失败点击弹窗看
export function SituationTip({ issue, pos }: { issue: Issue; pos: { x: number; y: number } }) {
  const W = 280, vw = window.innerWidth, vh = window.innerHeight;
  const left = pos.x + W > vw ? Math.max(8, pos.x - W - 24) : pos.x;
  const top = Math.min(pos.y, vh - 200);
  return createPortal(
    <div className="situation-tip-float" style={{ left, top: Math.max(8, top) }}>
        <div className="situation-tip-float-head">#{issue.id} {issue.title}</div>
        <div className="situation-tip-inner">
        <div className="situation-tip-row"><span>阶段</span><b>{issue.phase}</b></div>
        <div className="situation-tip-row"><span>进度</span><b>{issue.bar_value} / 100</b></div>
        <div className="situation-tip-row">
          <span>月度推进</span>
          <b>{issue.inertia > 0 ? `+${issue.inertia}` : issue.inertia}/月</b>
        </div>
        <div className="situation-tip-row">
          <span>当前影响</span>
          <b>{issue.ongoing_text || "无"}</b>
        </div>
        <p className="situation-tip-stage">{issue.stage_text}</p>
        <div className="situation-tip-more">点击查看达成 / 失败条件</div>
        </div>
    </div>,
    document.body
  );
}


// 局势详情弹窗（点击）：完整达成/失败条件 + 标签。居中模态，Portal 脱离梯形
export function SituationDetailModal({ issue, onClose }: { issue: Issue; onClose: () => void }) {
  return createPortal(
    <div className="situation-detail-backdrop" onClick={onClose}>
      <div className="situation-detail" onClick={(e) => e.stopPropagation()}>
        <div className="situation-detail-head">
          <span>#{issue.id} {issue.title}</span>
          <button className="situation-detail-close" onClick={onClose} aria-label="关闭">×</button>
        </div>
        <div className="situation-tip-inner">
        <div className="situation-tip-row"><span>阶段</span><b>{issue.phase}</b></div>
        <div className="situation-tip-row"><span>进度</span><b>{issue.bar_value} / 100</b></div>
        <div className="situation-tip-row">
          <span>月度推进</span>
          <b>{issue.inertia > 0 ? `+${issue.inertia}` : issue.inertia}/月</b>
        </div>
        <div className="situation-tip-row">
          <span>当前影响</span>
          <b>{issue.ongoing_text || "无"}</b>
        </div>
        <p className="situation-tip-stage">{issue.stage_text}</p>
        <div className="situation-tip-outcome good">
          <div className="situation-tip-outcome-head">达成（{issue.bar_good_meaning}）</div>
          {issue.resolve_condition && <p>{issue.resolve_condition}</p>}
          <div className="situation-tip-effect">{formatIssueEffect(issue.effect_on_resolve)}</div>
        </div>
        <div className="situation-tip-outcome bad">
          <div className="situation-tip-outcome-head">失败（{issue.bar_bad_meaning}）</div>
          {issue.fail_condition && <p>{issue.fail_condition}</p>}
          <div className="situation-tip-effect">{formatIssueEffect(issue.effect_on_fail)}</div>
        </div>
        {issue.tags.length ? (
          <div className="situation-tip-tags">
            {issue.tags.map((tag) => <small key={tag}>{tag}</small>)}
          </div>
        ) : null}
        </div>
      </div>
    </div>,
    document.body
  );
}

export function IssueGroup({ title, issues }: { title: string; issues: Issue[] }) {
  if (!issues.length) return null;
  return (
    <div className="issue-group">
      <h3>{title}</h3>
      <div className="issue-list">
        {issues.map((issue) => (
          <article className={`issue-line ${issueTone(issue.bar_value)}`} key={issue.id}>
            <div className="issue-head">
              <b>#{issue.id} {issue.title}</b>
              <span>{issue.phase} · {issue.bar_value}</span>
            </div>
            <div className="issue-progress" aria-label={`${issue.title}进度 ${issue.bar_value}`}>
              <span>{issue.bar_bad_meaning}</span>
              <div>
                <i style={{ width: `${Math.max(0, Math.min(100, issue.bar_value))}%` }} />
              </div>
              <span>{issue.bar_good_meaning}</span>
            </div>
            <p>{issue.stage_text}</p>
            {issue.tags.length ? (
              <div className="issue-tags">
                {issue.tags.map((tag) => <small key={tag}>{tag}</small>)}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}
