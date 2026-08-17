import React from "react";
import { MinisterPortrait, cacheBust } from "./hud";
import { parseLeadingStageDirection, stripOrganicMarkdown } from "../format";
import { matchHighlightPhrases, segmentHighlightedContent } from "../highlights";
import type { AudienceScrollMessage, ChatDisplayMessage, Minister } from "../types";

export function portraitSources(minister: Minister, portraitPrefix = "minister_") {
  const isCustom = minister.portrait_id?.startsWith("custom:");
  return {
    primary: isCustom
      ? `/portraits/custom/${encodeURIComponent(minister.name)}?t=${cacheBust(minister.portrait_id!)}`
      : `/portraits/${portraitPrefix}${minister.id ?? minister.name}.png`,
    fallback: !isCustom && minister.portrait_id ? `/portraits/${minister.portrait_id}.png` : undefined,
  };
}

export function ScrollMessages({
  messages,
  ministerName,
  ministers,
}: {
  messages: Array<ChatDisplayMessage | AudienceScrollMessage>;
  ministerName: string;
  ministers: Minister[];
}) {
  return <>{messages.map((message, index) => {
    const pending = "pending" in message && message.pending;
    const speaker = "speaker" in message ? message.speaker : message.role === "user" ? "朕" : message.role === "attendant" ? "近臣" : ministerName;
    const beat = "beat" in message ? message.beat : "dialogue";
    if (message.role === "scene") return <div className={`chat-message scene beat-${beat}`} key={`${message.role}-${index}-${message.content}`}>
      {beat === "divider" ? <div className="scene-divider"><hr aria-label={speaker ? `宣${speaker}` : "分隔"} />{speaker ? <strong>{speaker}</strong> : null}</div> : message.content ? <p>{message.content}</p> : null}
    </div>;
    const isAside = message.role === "attendant" && "audibility" in message && message.audibility === "御前低语";
    const attendant = isAside ? ministers.find((candidate) => candidate.name === speaker) : undefined;
    const attendantPortrait = attendant ? portraitSources(attendant) : undefined;
    const text = message.role === "minister" ? stripOrganicMarkdown(message.content) : message.content;
    const { action, content } = parseLeadingStageDirection(text);
    // #544 / ADR 0045：只标大臣气泡；短语先过同一剥离链再精确匹配，未命中静默丢弃。
    const rawHighlights = message.role === "minister" && "highlights" in message
      ? (message as { highlights?: string[] }).highlights
      : undefined;
    const matched = message.role === "minister"
      ? matchHighlightPhrases(message.content, rawHighlights)
      : [];
    const body = matched.length
      ? segmentHighlightedContent(content, matched).map((seg, segIndex) =>
          seg.highlight
            ? <mark className="hl" key={`h-${segIndex}`}>{seg.text}</mark>
            : <React.Fragment key={`t-${segIndex}`}>{seg.text}</React.Fragment>)
      : content;
    return <div className={`chat-message ${message.role} ${isAside ? "aside" : ""} ${pending ? "pending" : ""}`} key={`${message.role}-${index}-${message.content}`}>
      {isAside ? <MinisterPortrait className="aside-avatar" primary={attendantPortrait?.primary ?? ""} fallback={attendantPortrait?.fallback} name={speaker} /> : null}
      <span>{speaker}</span>
      {action ? <em className="action">{action}</em> : null}
      <p>{body}</p>
    </div>;
  })}</>;
}
