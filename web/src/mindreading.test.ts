import { describe, expect, it } from "vitest";
import { chatReducer, projectServerHistory } from "./mindreading";

describe("canonical server history projection", () => {
  it("projects user/minister turns without altering text", () => {
    const raw = "  臣领旨。  \n";
    const history = [
      { role: "user" as const, content: "准了", chat_turn_id: 10 },
      { role: "minister" as const, content: raw, chat_turn_id: 10, highlights: ["领旨"] },
    ];
    expect(projectServerHistory(history)).toEqual([
      { role: "user", content: "准了", chatTurnId: 10 },
      { role: "minister", content: raw, chatTurnId: 10, highlights: ["领旨"] },
    ]);
    expect(chatReducer([], { type: "history", history })).toEqual(projectServerHistory(history));
  });
});
