/** Backend-owned virtual speaker for the single live audience scene. */
export const AUDIENCE_SCENE_SPEAKER = "殿上";

/** Live audience has one entry; per-minister panel paths are retired (#1849 reopen). */
export const audienceHistoryPath = () => "/api/audience/chat";
export const audienceStreamPath = () => "/api/audience/chat/stream";
export const audienceUndoPath = () => "/api/audience/chat/undo";
export const audienceRetryPath = () => "/api/audience/reply/retry";
