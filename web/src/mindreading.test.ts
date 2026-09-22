import { describe, expect, it } from "vitest";
import { chatReducer, projectServerHistory } from "./mindreading";

describe("canonical server history projection", () => {
  it("projects persisted attendant records without altering text", () => {
    const raw = "  皇爷，他这句另有盘算。  \n";
    const history = [{ role: "attendant" as const, content: raw, chat_turn_id: 10, record_id: 4 }];
    expect(projectServerHistory(history)).toEqual([{ role: "attendant", content: raw, chatTurnId: 10, recordId: 4 }]);
    expect(chatReducer([], { type: "history", history })).toEqual(projectServerHistory(history));
  });
});
