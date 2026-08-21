import type { AudienceScrollMessage } from "./types";

export type MinisterScrollLensOptions = {
  /**
   * One-shot presentation claim for a half-turn already owned by this window
   * (replyRetry.chat_turn_id, or in-flight pendingIdentity.chat_turn_id).
   * Only applies when the turn has no named minister owner yet. No cache / durable write.
   */
  claimedTurnId?: number | null;
};

/**
 * #1511 pure presentation lens: campaign-wide night scroll → selected minister window.
 *
 * Consumes only speaker / chat_turn_id / beat (+ optional window claim). No cache, no durable state.
 * - Messages with chat_turn_id and a named minister turnOwner follow that owner in/out as a whole
 *   turn — segment ownerHint never overrides a formal turn.
 * - Messages without chat_turn_id follow the soft segment ownerHint (side interjections travel
 *   with the named entrance/divider stretch).
 * - Single-principal unanchored stretch (empty-speaker entrance + one turn owner): whole stretch
 *   kept for that principal so entrance/scene without chat_turn_id is not orphaned.
 * - 无主消息不泛留: turns without a named minister speaker (and without window claim) are dropped.
 */
export function filterScrollForSelectedMinister(
  messages: AudienceScrollMessage[],
  selectedMinister: string,
  options?: MinisterScrollLensOptions,
): AudienceScrollMessage[] {
  if (!selectedMinister || messages.length === 0) return [];

  const turnOwner = new Map<number, string>();
  for (const message of messages) {
    const turnId = message.chat_turn_id;
    if (message.role === "minister" && turnId && message.speaker) {
      turnOwner.set(turnId, message.speaker);
    }
  }
  // Window-local half-turn claim: only fill a turn that still has no minister owner.
  const claimedTurnId = options?.claimedTurnId;
  if (claimedTurnId && !turnOwner.has(claimedTurnId)) {
    turnOwner.set(claimedTurnId, selectedMinister);
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
    // segmentOwner only governs no-turn messages (soft-segment context).
    const segmentOwner = resolveSegmentOwner(segment, turnOwner);
    for (const message of segment.messages) {
      const turnId = message.chat_turn_id;
      if (turnId) {
        // Formal turn: structured turnOwner wins over any segment ownerHint.
        if (turnOwner.get(turnId) === selectedMinister) {
          out.push(message);
        }
        // else: other minister's turn, or orphan turn — drop from this window
        continue;
      }
      // No chat_turn_id: follow soft segment (side interjection / entrance / local scene).
      if (segmentOwner === selectedMinister) {
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
