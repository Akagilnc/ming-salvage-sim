import type { AudienceScrollMessage } from "./types";

/**
 * #1511 pure presentation lens: campaign-wide night scroll → selected minister window.
 *
 * Consumes only speaker / chat_turn_id / beat. No cache, no durable state.
 * - Soft segments (named entrance/divider anchors): whole segment kept iff owned by selected.
 *   Side interjections inside the segment travel with the segment (不串窗、不误删上下文).
 * - Unanchored stretches (e.g. 密令): bind by chat_turn_id to the turn's named minister;
 *   emperor / attendant / scene on that turn go in/out together.
 * - Single-principal unanchored stretch (empty-speaker entrance + one turn owner): whole stretch
 *   kept for that principal so entrance/scene without chat_turn_id is not orphaned.
 * - 无主消息不泛留: turns without a named minister speaker are dropped.
 */
export function filterScrollForSelectedMinister(
  messages: AudienceScrollMessage[],
  selectedMinister: string,
): AudienceScrollMessage[] {
  if (!selectedMinister || messages.length === 0) return [];

  const turnOwner = new Map<number, string>();
  for (const message of messages) {
    const turnId = message.chat_turn_id;
    if (message.role === "minister" && turnId && message.speaker) {
      turnOwner.set(turnId, message.speaker);
    }
  }

  type Segment = { ownerHint: string | null; messages: AudienceScrollMessage[] };
  const segments: Segment[] = [];
  let current: Segment = { ownerHint: null, messages: [] };

  const flush = () => {
    if (current.messages.length === 0) return;
    segments.push(current);
    current = { ownerHint: null, messages: [] };
  };

  for (const message of messages) {
    // Named entrance/divider starts a new soft segment. Empty-speaker anchors stay put
    // (backend entrance speaker is often ""; final divider speaker is often "").
    const startsSegment = (message.beat === "entrance" || message.beat === "divider") && !!message.speaker;
    if (startsSegment && current.messages.length > 0) {
      flush();
    }
    current.messages.push(message);
    if (startsSegment) {
      current.ownerHint = message.speaker;
    }
  }
  flush();

  const out: AudienceScrollMessage[] = [];
  for (const segment of segments) {
    const owner = resolveSegmentOwner(segment, turnOwner);
    if (owner === selectedMinister) {
      out.push(...segment.messages);
      continue;
    }
    if (owner != null) {
      // Other minister's full semantic segment — drop entirely.
      continue;
    }
    // Multi-principal or empty unanchored stretch: keep only turns bound to selected.
    const keepTurns = new Set<number>();
    for (const message of segment.messages) {
      const turnId = message.chat_turn_id;
      if (turnId && turnOwner.get(turnId) === selectedMinister) {
        keepTurns.add(turnId);
      }
    }
    for (const message of segment.messages) {
      const turnId = message.chat_turn_id;
      if (turnId && keepTurns.has(turnId)) {
        out.push(message);
      }
    }
  }
  return out;
}

function resolveSegmentOwner(
  segment: { ownerHint: string | null; messages: AudienceScrollMessage[] },
  turnOwner: Map<number, string>,
): string | null {
  if (segment.ownerHint) return segment.ownerHint;
  for (const message of segment.messages) {
    if ((message.beat === "entrance" || message.beat === "divider") && message.speaker) {
      return message.speaker;
    }
  }
  // No named anchor: prefer chat_turn principals. A single turn principal owns the
  // whole stretch (empty-speaker entrance / local scene / side lines without turns).
  // Side interjections without chat_turn_id must not create a second principal.
  const turnPrincipals = new Set<string>();
  for (const message of segment.messages) {
    const turnId = message.chat_turn_id;
    if (turnId && turnOwner.has(turnId)) {
      turnPrincipals.add(turnOwner.get(turnId)!);
    }
  }
  if (turnPrincipals.size === 1) {
    return turnPrincipals.values().next().value ?? null;
  }
  if (turnPrincipals.size > 1) return null;

  // Fixture / sparse scroll without chat_turn_id: unique role=minister speaker.
  const ministerSpeakers = new Set<string>();
  for (const message of segment.messages) {
    if (message.role === "minister" && message.speaker) {
      ministerSpeakers.add(message.speaker);
    }
  }
  if (ministerSpeakers.size === 1) {
    return ministerSpeakers.values().next().value ?? null;
  }
  return null;
}
