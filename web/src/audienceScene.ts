/** Backend-owned virtual speaker for the single live audience scene. */
export const AUDIENCE_SCENE_SPEAKER = "殿上";

export const audienceHistoryPath = (scene: string) => scene === AUDIENCE_SCENE_SPEAKER
  ? "/api/audience/chat"
  : `/api/ministers/${encodeURIComponent(scene)}/chat`;

export const audienceStreamPath = (scene: string) => `${audienceHistoryPath(scene)}/stream`;
export const audienceUndoPath = (scene: string) => `${audienceHistoryPath(scene)}/undo`;
export const audienceRetryPath = (scene: string) => scene === AUDIENCE_SCENE_SPEAKER
  ? "/api/audience/reply/retry"
  : `/api/ministers/${encodeURIComponent(scene)}/reply/retry`;
