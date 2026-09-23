import React from "react";
import { MinisterPortrait, cacheBust } from "./hud";
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
  const highlightedContent = (message: ChatDisplayMessage | AudienceScrollMessage) => {
    const rawHighlights = message.role === "minister" && "highlights" in message ? message.highlights : undefined;
    const matched = message.role === "minister" ? matchHighlightPhrases(message.content, rawHighlights) : [];
    return matched.length
      ? segmentHighlightedContent(message.content, matched).map((segment, segmentIndex) => segment.highlight
          ? <strong className="hl" key={`h-${segmentIndex}`}>{segment.text}</strong>
          : <React.Fragment key={`t-${segmentIndex}`}>{segment.text}</React.Fragment>)
      : message.content;
  };
  const groups: Array<{ key: string; turnId?: number; messages: typeof messages }> = [];
  const turnOccurrences = new Map<number, number>();
  messages.forEach((message, index) => {
    const turnId = "chat_turn_id" in message ? message.chat_turn_id : undefined;
    if (turnId != null) {
      let group = groups[groups.length - 1];
      if (!group || group.turnId !== turnId) {
        const occurrence = turnOccurrences.get(turnId) ?? 0;
        turnOccurrences.set(turnId, occurrence + 1);
        group = { key: `turn-${turnId}-${occurrence}`, turnId, messages: [] };
        groups.push(group);
      }
      group.messages.push(message);
      return;
    }
    groups.push({ key: `loose-${message.role}-${index}`, messages: [message] });
  });

  const renderMessage = (message: ChatDisplayMessage | AudienceScrollMessage, index: number) => {
    const persistedId = "record_id" in message && message.record_id != null
      ? `record-${message.record_id}`
      : `${message.role}-${index}`;
    const pending = "pending" in message && message.pending;
    const speaker = "speaker" in message ? message.speaker : message.role === "user" ? "朕" : message.role === "attendant" ? "近臣" : ministerName;
    const beat = "beat" in message ? message.beat : "dialogue";
    if (message.role === "scene") {
      return <div className={`chat-message scene beat-${beat}`} key={persistedId}>
        {beat === "divider" ? <div className="scene-divider"><hr aria-label={speaker ? `宣${speaker}` : "分隔"} />{speaker ? <strong>{speaker}</strong> : null}</div> : message.content ? <p>{message.content}</p> : null}
      </div>;
    }
    const isAside = message.role === "attendant" && "audibility" in message && message.audibility === "御前低语";
    const attendant = isAside ? ministers.find((candidate) => candidate.name === speaker) : undefined;
    const attendantPortrait = attendant ? portraitSources(attendant) : undefined;
    return <div className={`chat-message ${message.role} ${isAside ? "aside" : ""} ${pending ? "pending" : ""}`} key={persistedId}>
      {isAside ? <MinisterPortrait className="aside-avatar" primary={attendantPortrait?.primary ?? ""} fallback={attendantPortrait?.fallback} name={speaker} /> : null}
      <span>{speaker}</span>
      <p>{highlightedContent(message)}</p>
    </div>;
  };

  const renderTurnSegment = (message: ChatDisplayMessage | AudienceScrollMessage, index: number) => {
    const persistedId = "record_id" in message && message.record_id != null
      ? `record-${message.record_id}`
      : `${message.role}-${index}`;
    const speaker = "speaker" in message ? message.speaker : message.role === "user" ? "朕" : ministerName;
    const beat = "beat" in message ? message.beat : "dialogue";
    const isAside = message.role === "attendant" && "audibility" in message && message.audibility === "御前低语";
    const attendant = isAside ? ministers.find((candidate) => candidate.name === speaker) : undefined;
    const attendantPortrait = attendant ? portraitSources(attendant) : undefined;
    return <div className={`turn-segment ${message.role} ${isAside ? "aside" : ""} beat-${beat}`} key={persistedId}>
      {isAside ? <MinisterPortrait className="aside-avatar" primary={attendantPortrait?.primary ?? ""} fallback={attendantPortrait?.fallback} name={speaker} /> : null}
      {message.role === "scene" && beat === "divider"
        ? <div className="scene-divider"><hr aria-label={speaker ? `宣${speaker}` : "分隔"} />{speaker ? <strong>{speaker}</strong> : null}</div>
        : <>
            {message.role !== "scene" && speaker ? <span className="turn-speaker">{speaker}</span> : null}
            {message.content ? <p>{highlightedContent(message)}</p> : null}
          </>}
    </div>;
  };

  return <>{groups.map((group) => (
    <div className="audience-turn" data-audience-turn-id={group.turnId} key={group.key}>
      {group.turnId == null
        ? group.messages.map(renderMessage)
        : <div className="audience-turn-content">{group.messages.map(renderTurnSegment)}</div>}
    </div>
  ))}</>;
}
