import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { ChatModal } from "./modals";
import type { Minister } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MINISTER_MOCK: Minister = {
  name: "周延儒",
  office: "内阁首辅",
  office_type: "cabinet",
  faction: "东林",
  style: "字玉绳",
  status: "active",
  status_label: "在朝",
  summary: "东林领袖",
  favorite: false,
  skills: [],
};

const CONSORT_MOCK: Minister = {
  name: "周贵人",
  office: "贵人",
  office_type: "后宫",
  faction: "",
  style: "",
  status: "active",
  status_label: "在宫",
  summary: "后宫嫔妃",
  favorite: false,
  skills: [],
};

function renderModal(props: { minister: Minister; portraitPrefix: string }) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <ChatModal
        minister={props.minister}
        portraitPrefix={props.portraitPrefix}
        chat={[]}
        suggestions={[]}
        pendingUserMessage=""
        streamingMinisterMessage=""
        chatNotice=""
        canUndoLastChat={false}
        composerHint=""
        input=""
        busy=""
        error=""
        secretOrders={[]}
        onInput={() => {}}
        onSend={() => {}}
        onUndo={() => {}}
        onHint={() => {}}
        onFavorite={() => {}}
        onOpenEdict={() => {}}
        onClose={() => {}}
      />
    )
  );
  return {
    cleanup: () => {
      act(() => root.unmount());
      host.remove();
    },
  };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ChatModal — placeholder switches on character type", () => {
  it("shows 大臣 and 他 in placeholder for ministers", () => {
    const { cleanup } = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
    });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder).toContain("大臣");
    expect(textarea.placeholder).toContain("他");
    cleanup();
  });

  it("does NOT show 大臣 or 他 in placeholder for consorts", () => {
    const { cleanup } = renderModal({
      minister: CONSORT_MOCK,
      portraitPrefix: "consort_",
    });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder).not.toContain("大臣");
    expect(textarea.placeholder).not.toContain("他");
    cleanup();
  });

  it("consort placeholder has meaningful length", () => {
    const { cleanup } = renderModal({
      minister: CONSORT_MOCK,
      portraitPrefix: "consort_",
    });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder.length).toBeGreaterThan(5);
    cleanup();
  });
});
