/** Backend-owned virtual speaker for the single live audience scene. */
export const AUDIENCE_SCENE_SPEAKER = "殿上";

export const audienceHistoryPath = (speaker: string) => speaker === AUDIENCE_SCENE_SPEAKER
  ? "/api/audience/chat"
  : `/api/ministers/${encodeURIComponent(speaker)}/chat`;

export const audienceStreamPath = (speaker: string) => `${audienceHistoryPath(speaker)}/stream`;
export const audienceUndoPath = (speaker: string) => `${audienceHistoryPath(speaker)}/undo`;
export const audienceRetryPath = (speaker: string) => speaker === AUDIENCE_SCENE_SPEAKER
  ? "/api/audience/reply/retry"
  : `/api/ministers/${encodeURIComponent(speaker)}/reply/retry`;
