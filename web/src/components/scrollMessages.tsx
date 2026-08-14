import React from "react";
import { MinisterPortrait, cacheBust } from "./hud";
import { stripOrganicMarkdown } from "../format";
import type { AudienceScrollMessage, ChatDisplayMessage, Minister } from "../types";

function highlightedMinisterText(message: ChatDisplayMessage | AudienceScrollMessage, text: string): React.ReactNode {
  const phrases = (message.highlights || [])
    .map(stripOrganicMarkdown)
    .filter((phrase) => phrase && text.includes(phrase));
  if (!phrases.length) return text;
  const ranges = phrases
    .map((phrase) => ({ start: text.indexOf(phrase), phrase }))
    .sort((a, b) => a.start - b.start || b.phrase.length - a.phrase.length);
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  ranges.forEach(({ start, phrase }) => {
    if (start < cursor) return;
    if (start > cursor) nodes.push(text.slice(cursor, start));
    nodes.push(<mark key={`${start}-${phrase}`}>{text.slice(start, start + phrase.length)}</mark>);
    cursor = start + phrase.length;
  });
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

export function parseLeadingStageDirection(source: string): { action: string | null; content: string } {
  const match = source.match(/^（[^（）\r\n]+）/);
  return match
    ? { action: match[0], content: source.slice(match[0].length) }
    : { action: null, content: source };
}

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
    return <div className={`chat-message ${message.role} ${isAside ? "aside" : ""} ${pending ? "pending" : ""}`} key={`${message.role}-${index}-${message.content}`}>
      {isAside ? <MinisterPortrait className="aside-avatar" primary={attendantPortrait?.primary ?? ""} fallback={attendantPortrait?.fallback} name={speaker} /> : null}
      <span>{speaker}</span>
      {action ? <em className="action">{action}</em> : null}
      <p>{message.role === "minister" ? highlightedMinisterText(message, content) : content}</p>
    </div>;
  })}</>;
}
