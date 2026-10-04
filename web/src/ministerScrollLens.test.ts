import { describe, expect, it } from "vitest";
import { filterScrollForSelectedMinister } from "./ministerScrollLens";
import type { AudienceScrollMessage } from "./types";

const base = {
  audibility: "",
  time: null as string | null,
  soft_boundary: false,
  highlights: [] as string[],
  container: { time_of_day: "戌时", location: "乾清宫", audience_type: "召对" },
};

function msg(partial: Partial<AudienceScrollMessage> & Pick<AudienceScrollMessage, "role" | "content" | "beat">): AudienceScrollMessage {
  return {
    speaker: "",
    ...base,
    ...partial,
  };
}

function rolesSpeakers(scroll: AudienceScrollMessage[]) {
  return scroll.map((message) => {
    const row: { role: string; speaker: string; chat_turn_id?: number } = {
      role: message.role,
      speaker: message.speaker,
    };
    if (message.chat_turn_id != null) row.chat_turn_id = message.chat_turn_id;
    return row;
  });
}

/** Owner fixture: 洪承畴 full semantic turn + 许誉卿 absent. */
function hongSecretOrderScroll(): AudienceScrollMessage[] {
  return [
    msg({ role: "user", speaker: "朕", content: "密令：整饬边备。", beat: "dialogue", chat_turn_id: 11 }),
    msg({ role: "minister", speaker: "洪承畴", content: "臣领旨。", beat: "dialogue", chat_turn_id: 11 }),
    msg({ role: "attendant", speaker: "王承恩", content: "他神色凝重。", beat: "aside", chat_turn_id: 11 }),
    msg({ role: "scene", speaker: "", content: "烛影微动。", beat: "scene", chat_turn_id: 11 }),
  ];
}

/** Soft segment with side interjection (殿侧他臣插话). */
function softSegmentWithAside(): AudienceScrollMessage[] {
  return [
    msg({ role: "scene", speaker: "洪承畴", content: "", beat: "divider", soft_boundary: true }),
    msg({ role: "scene", speaker: "洪承畴", content: "洪承畴趋入殿中。", beat: "scene" }),
    msg({ role: "user", speaker: "朕", content: "边务如何？", beat: "dialogue", chat_turn_id: 1 }),
    msg({ role: "minister", speaker: "洪承畴", content: "臣自三边来。", beat: "dialogue", chat_turn_id: 1 }),
    msg({ role: "minister", speaker: "杨嗣昌", content: "殿侧容臣插一句。", beat: "dialogue" }),
    msg({ role: "attendant", speaker: "王承恩", content: "洪督神色未安。", beat: "aside", chat_turn_id: 1 }),
    msg({ role: "scene", speaker: "", content: "", beat: "divider", soft_boundary: true }),
  ];
}

describe("filterScrollForSelectedMinister (#1511 lens)", () => {
  it("许誉卿场景：无记录大臣空白开场，不见他臣密令整卷", () => {
    const scroll = hongSecretOrderScroll();
    const lens = filterScrollForSelectedMinister(scroll, "许誉卿");
    expect(lens).toEqual([]);
    // 来源权限：他臣密令卷不得泄漏进空白窗
    expect(lens.map((m) => m.content).join("")).not.toContain("密令");
  });

  it("切回有记录大臣：该臣语义轮完整（朕问/回话/递话/scene 同进）", () => {
    const scroll = hongSecretOrderScroll();
    const lens = filterScrollForSelectedMinister(scroll, "洪承畴");
    expect(rolesSpeakers(lens)).toEqual([
      { role: "user", speaker: "朕", chat_turn_id: 11 },
      { role: "minister", speaker: "洪承畴", chat_turn_id: 11 },
      { role: "attendant", speaker: "王承恩", chat_turn_id: 11 },
      { role: "scene", speaker: "", chat_turn_id: 11 },
    ]); // structure only — no free dialogue body lock
  });

  it("归属反例：本臣轮内非本臣 speaker 保留；他臣轮不泄漏；无主不泛留", () => {
    const scroll: AudienceScrollMessage[] = [
      // 洪 turn: emperor + 洪 + 王承恩 (non-hong speakers must stay)
      msg({ role: "user", speaker: "朕", content: "洪问", beat: "dialogue", chat_turn_id: 1 }),
      msg({ role: "minister", speaker: "洪承畴", content: "洪答", beat: "dialogue", chat_turn_id: 1 }),
      msg({ role: "attendant", speaker: "王承恩", content: "洪递话", beat: "aside", chat_turn_id: 1 }),
      // 王绍徽 turn: must not leak into 洪 lens
      msg({ role: "user", speaker: "朕", content: "王问", beat: "dialogue", chat_turn_id: 2 }),
      msg({ role: "minister", speaker: "王绍徽", content: "王答", beat: "dialogue", chat_turn_id: 2 }),
      msg({ role: "attendant", speaker: "王承恩", content: "王递话", beat: "aside", chat_turn_id: 2 }),
      // Orphan attendant / user without named minister on the turn — 无主不泛留
      msg({ role: "user", speaker: "朕", content: "无主问话", beat: "dialogue", chat_turn_id: 3 }),
      msg({ role: "attendant", speaker: "王承恩", content: "无主递话", beat: "aside", chat_turn_id: 3 }),
      msg({ role: "scene", speaker: "", content: "无主 scene", beat: "scene" }),
    ];

    const hong = filterScrollForSelectedMinister(scroll, "洪承畴");
    expect(rolesSpeakers(hong)).toEqual([
      { role: "user", speaker: "朕", chat_turn_id: 1 },
      { role: "minister", speaker: "洪承畴", chat_turn_id: 1 },
      { role: "attendant", speaker: "王承恩", chat_turn_id: 1 },
    ]);
    // Per-speaker filter would have dropped 朕/王承恩 — must NOT reproduce that mistake
    expect(hong.some((m) => m.speaker === "朕")).toBe(true);
    expect(hong.some((m) => m.speaker === "王承恩")).toBe(true);

    const wang = filterScrollForSelectedMinister(scroll, "王绍徽");
    expect(rolesSpeakers(wang)).toEqual([
      { role: "user", speaker: "朕", chat_turn_id: 2 },
      { role: "minister", speaker: "王绍徽", chat_turn_id: 2 },
      { role: "attendant", speaker: "王承恩", chat_turn_id: 2 },
    ]);
    expect(wang.some((m) => m.speaker === "洪承畴")).toBe(false);

    const orphan = filterScrollForSelectedMinister(scroll, "许誉卿");
    expect(orphan).toEqual([]);
  });

  it("无锚轮按 chat_turn_id 绑定具名 minister，整轮同进同退", () => {
    const scroll: AudienceScrollMessage[] = [
      msg({ role: "user", speaker: "朕", content: "A问", beat: "dialogue", chat_turn_id: 10 }),
      msg({ role: "minister", speaker: "洪承畴", content: "A答", beat: "dialogue", chat_turn_id: 10 }),
      msg({ role: "user", speaker: "朕", content: "B问", beat: "dialogue", chat_turn_id: 20 }),
      msg({ role: "minister", speaker: "许誉卿", content: "B答", beat: "dialogue", chat_turn_id: 20 }),
      msg({ role: "attendant", speaker: "王承恩", content: "B递话", beat: "aside", chat_turn_id: 20 }),
    ];
    expect(rolesSpeakers(filterScrollForSelectedMinister(scroll, "许誉卿"))).toEqual([
      { role: "user", speaker: "朕", chat_turn_id: 20 },
      { role: "minister", speaker: "许誉卿", chat_turn_id: 20 },
      { role: "attendant", speaker: "王承恩", chat_turn_id: 20 },
    ]);
    expect(rolesSpeakers(filterScrollForSelectedMinister(scroll, "洪承畴"))).toEqual([
      { role: "user", speaker: "朕", chat_turn_id: 10 },
      { role: "minister", speaker: "洪承畴", chat_turn_id: 10 },
    ]);
  });

  it("同一归档轮有两名正式发言人时，两人都能回看整轮", () => {
    const scroll = [
      msg({ role: "user", speaker: "朕", content: "同问", beat: "dialogue", chat_turn_id: 30 }),
      msg({ role: "minister", speaker: "洪承畴", content: "洪答", beat: "dialogue", chat_turn_id: 30 }),
      msg({ role: "minister", speaker: "许誉卿", content: "许答", beat: "dialogue", chat_turn_id: 30 }),
    ];
    expect(filterScrollForSelectedMinister(scroll, "洪承畴")).toEqual(scroll);
    expect(filterScrollForSelectedMinister(scroll, "许誉卿")).toEqual(scroll);
  });

  it("场景/divider 软段 + 殿侧他臣插话：不串窗且不误删本段上下文", () => {
    const scroll = softSegmentWithAside();

    const hong = filterScrollForSelectedMinister(scroll, "洪承畴");
    // 杨's interjection stays as 洪 segment context
    expect(hong.some((m) => m.speaker === "杨嗣昌")).toBe(true);
    expect(hong.some((m) => m.speaker === "王承恩")).toBe(true);
    expect(rolesSpeakers(hong)).toEqual([
      { role: "scene", speaker: "洪承畴" },
      { role: "scene", speaker: "洪承畴" },
      { role: "user", speaker: "朕", chat_turn_id: 1 },
      { role: "minister", speaker: "洪承畴", chat_turn_id: 1 },
      { role: "minister", speaker: "杨嗣昌" },
      { role: "attendant", speaker: "王承恩", chat_turn_id: 1 },
      { role: "scene", speaker: "" },
    ]);

    // 杨 window must not inherit 洪's whole segment (不串窗)
    const yang = filterScrollForSelectedMinister(scroll, "杨嗣昌");
    expect(yang.some((m) => m.speaker === "洪承畴" && m.role === "minister")).toBe(false);
    expect(yang.some((m) => m.speaker === "朕")).toBe(false);

    // 许 blank
    expect(filterScrollForSelectedMinister(scroll, "许誉卿")).toEqual([]);
  });

  it("empty-speaker scene still binds the soft stretch to the turn principal", () => {
    const scroll: AudienceScrollMessage[] = [
      msg({ role: "scene", speaker: "", content: "洪承畴入殿。", beat: "scene" }),
      msg({ role: "user", speaker: "朕", content: "问", beat: "dialogue", chat_turn_id: 5 }),
      msg({ role: "minister", speaker: "洪承畴", content: "答", beat: "dialogue", chat_turn_id: 5 }),
      msg({ role: "minister", speaker: "杨嗣昌", content: "侧言", beat: "dialogue" }),
    ];
    const hong = filterScrollForSelectedMinister(scroll, "洪承畴");
    expect(rolesSpeakers(hong)).toEqual([
      { role: "scene", speaker: "" },
      { role: "user", speaker: "朕", chat_turn_id: 5 },
      { role: "minister", speaker: "洪承畴", chat_turn_id: 5 },
      { role: "minister", speaker: "杨嗣昌" },
    ]);
    expect(filterScrollForSelectedMinister(scroll, "杨嗣昌")).toEqual([]);
  });

  it("镜头键是 selected minister 参数，不从卷轴推导 currentMinister", () => {
    const scroll = softSegmentWithAside();
    // Even though scroll anchors point at 洪, asking for 许 yields empty — proves key is the argument.
    expect(filterScrollForSelectedMinister(scroll, "许誉卿")).toEqual([]);
    expect(filterScrollForSelectedMinister(scroll, "洪承畴").length).toBeGreaterThan(0);
  });

  it("具名 divider 段内后续他臣正式 turn：前臣窗移除、后臣窗完整、无 turn 殿侧插话仍随软段", () => {
    const scroll: AudienceScrollMessage[] = [
      msg({ role: "scene", speaker: "洪承畴", content: "", beat: "divider", soft_boundary: true }),
      msg({ role: "scene", speaker: "洪承畴", content: "洪承畴趋入殿中。", beat: "scene" }),
      msg({ role: "user", speaker: "朕", content: "边务如何？", beat: "dialogue", chat_turn_id: 1 }),
      msg({ role: "minister", speaker: "洪承畴", content: "臣自三边来。", beat: "dialogue", chat_turn_id: 1 }),
      // Formal later turn by another minister inside the same named soft segment
      msg({ role: "user", speaker: "朕", content: "杨卿以为如何？", beat: "dialogue", chat_turn_id: 2 }),
      msg({ role: "minister", speaker: "杨嗣昌", content: "臣以为当先清饷。", beat: "dialogue", chat_turn_id: 2 }),
      msg({ role: "attendant", speaker: "王承恩", content: "杨部神色郑重。", beat: "aside", chat_turn_id: 2 }),
      // No-turn side interjection still rides the soft segment
      msg({ role: "minister", speaker: "孙传庭", content: "殿侧容臣插一句。", beat: "dialogue" }),
      msg({ role: "scene", speaker: "", content: "", beat: "divider", soft_boundary: true }),
    ];

    const hong = filterScrollForSelectedMinister(scroll, "洪承畴");
    expect(rolesSpeakers(hong)).toEqual([
      { role: "scene", speaker: "洪承畴" },
      { role: "scene", speaker: "洪承畴" },
      { role: "user", speaker: "朕", chat_turn_id: 1 },
      { role: "minister", speaker: "洪承畴", chat_turn_id: 1 },
      { role: "minister", speaker: "孙传庭" },
      { role: "scene", speaker: "" },
    ]);
    expect(hong.some((m) => m.speaker === "杨嗣昌")).toBe(false);

    const yang = filterScrollForSelectedMinister(scroll, "杨嗣昌");
    expect(rolesSpeakers(yang)).toEqual([
      { role: "user", speaker: "朕", chat_turn_id: 2 },
      { role: "minister", speaker: "杨嗣昌", chat_turn_id: 2 },
      { role: "attendant", speaker: "王承恩", chat_turn_id: 2 },
    ]);
    expect(yang.some((m) => m.speaker === "洪承畴" && m.role === "minister")).toBe(false);
    expect(yang.some((m) => m.speaker === "孙传庭")).toBe(false);
  });

  it("半轮 claim：无 minister 气泡的 user 问话按 claimedTurnId 留在本窗", () => {
    const scroll: AudienceScrollMessage[] = [
      msg({ role: "user", speaker: "朕", content: "辽饷何解？", beat: "dialogue", chat_turn_id: 12 }),
      msg({ role: "user", speaker: "朕", content: "他臣密令", beat: "dialogue", chat_turn_id: 11 }),
      msg({ role: "minister", speaker: "洪承畴", content: "臣领旨。", beat: "dialogue", chat_turn_id: 11 }),
    ];
    // Without claim, half-turn user is orphan and must not leak.
    expect(filterScrollForSelectedMinister(scroll, "许誉卿")).toEqual([]);
    expect(
      rolesSpeakers(filterScrollForSelectedMinister(scroll, "许誉卿", { claimedTurnId: 12 })),
    ).toEqual([{ role: "user", speaker: "朕", chat_turn_id: 12 }]);
    // Claim must not override an already-named minister owner on another turn.
    expect(
      filterScrollForSelectedMinister(scroll, "许誉卿", { claimedTurnId: 11 }),
    ).toEqual([]);
  });

  it("现行单场景轮按参与臣过滤时保留殿上正式对话", () => {
    const scroll = [
      msg({ role: "user", speaker: "朕", content: "诸卿以为如何？", beat: "dialogue", chat_turn_id: 30 }),
      msg({ role: "minister", speaker: "殿上", content: "群臣各陈所见。", beat: "dialogue", chat_turn_id: 30 }),
      msg({ role: "attendant", speaker: "王承恩", content: "洪承畴亦在列。", beat: "aside", chat_turn_id: 30 }),
    ];
    expect(
      rolesSpeakers(filterScrollForSelectedMinister(scroll, "洪承畴", { sceneSpeaker: "殿上" })),
    ).toEqual([
      { role: "user", speaker: "朕", chat_turn_id: 30 },
      { role: "minister", speaker: "殿上", chat_turn_id: 30 },
      { role: "attendant", speaker: "王承恩", chat_turn_id: 30 },
    ]);
  });

  it("未转译的无主轮保留为中性记录，不将他臣具名轮归给当前臣", () => {
    const scroll = [
      msg({ role: "user", speaker: "朕", content: "待整理问话", beat: "dialogue", chat_turn_id: 40 }),
      msg({ role: "scene", speaker: "", content: "待整理回话", beat: "dialogue", chat_turn_id: 40 }),
      msg({ role: "minister", speaker: "洪承畴", content: "已具名回话", beat: "dialogue", chat_turn_id: 41 }),
    ];
    const visible = filterScrollForSelectedMinister(scroll, "许誉卿", { pendingTranslationTurnIds: [40] });
    expect(rolesSpeakers(visible)).toEqual([
      { role: "user", speaker: "朕", chat_turn_id: 40 },
      { role: "scene", speaker: "", chat_turn_id: 40 },
    ]);
  });
});
