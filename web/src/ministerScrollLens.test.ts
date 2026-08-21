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
    msg({ role: "scene", speaker: "洪承畴", content: "洪承畴趋入殿中。", beat: "entrance" }),
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
    expect(lens.map((m) => m.content).join("")).not.toContain("密令");
    expect(lens.map((m) => m.content).join("")).not.toContain("臣领旨");
    expect(lens.map((m) => m.content).join("")).not.toContain("神色凝重");
  });

  it("切回有记录大臣：该臣语义轮完整（朕问/回话/递话/scene 同进）", () => {
    const scroll = hongSecretOrderScroll();
    const lens = filterScrollForSelectedMinister(scroll, "洪承畴");
    expect(lens.map((m) => m.content)).toEqual([
      "密令：整饬边备。",
      "臣领旨。",
      "他神色凝重。",
      "烛影微动。",
    ]);
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
    expect(hong.map((m) => m.content)).toEqual(["洪问", "洪答", "洪递话"]);
    // Per-speaker filter would have dropped 朕/王承恩 — must NOT reproduce that mistake
    expect(hong.some((m) => m.speaker === "朕")).toBe(true);
    expect(hong.some((m) => m.speaker === "王承恩")).toBe(true);

    const wang = filterScrollForSelectedMinister(scroll, "王绍徽");
    expect(wang.map((m) => m.content)).toEqual(["王问", "王答", "王递话"]);
    expect(wang.some((m) => m.content.startsWith("洪"))).toBe(false);

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
    expect(filterScrollForSelectedMinister(scroll, "许誉卿").map((m) => m.content)).toEqual([
      "B问", "B答", "B递话",
    ]);
    expect(filterScrollForSelectedMinister(scroll, "洪承畴").map((m) => m.content)).toEqual([
      "A问", "A答",
    ]);
  });

  it("entrance/divider 软段 + 殿侧他臣插话：不串窗且不误删本段上下文", () => {
    const scroll = softSegmentWithAside();

    const hong = filterScrollForSelectedMinister(scroll, "洪承畴");
    expect(hong.map((m) => m.content)).toEqual([
      "",
      "洪承畴趋入殿中。",
      "边务如何？",
      "臣自三边来。",
      "殿侧容臣插一句。",
      "洪督神色未安。",
      "",
    ]);
    // 杨's interjection stays as 洪 segment context
    expect(hong.some((m) => m.speaker === "杨嗣昌")).toBe(true);
    expect(hong.some((m) => m.speaker === "王承恩")).toBe(true);

    // 杨 window must not inherit 洪's whole segment (不串窗)
    const yang = filterScrollForSelectedMinister(scroll, "杨嗣昌");
    expect(yang.some((m) => m.content === "臣自三边来。")).toBe(false);
    expect(yang.some((m) => m.content === "洪承畴趋入殿中。")).toBe(false);
    expect(yang.some((m) => m.content === "殿侧容臣插一句。")).toBe(false);

    // 许 blank
    expect(filterScrollForSelectedMinister(scroll, "许誉卿")).toEqual([]);
  });

  it("backend-shaped empty-speaker entrance still binds the soft stretch to the turn principal", () => {
    const scroll: AudienceScrollMessage[] = [
      msg({ role: "scene", speaker: "", content: "洪承畴入殿。", beat: "entrance" }),
      msg({ role: "user", speaker: "朕", content: "问", beat: "dialogue", chat_turn_id: 5 }),
      msg({ role: "minister", speaker: "洪承畴", content: "答", beat: "dialogue", chat_turn_id: 5 }),
      msg({ role: "minister", speaker: "杨嗣昌", content: "侧言", beat: "dialogue" }),
    ];
    const hong = filterScrollForSelectedMinister(scroll, "洪承畴");
    expect(hong.map((m) => m.content)).toEqual(["洪承畴入殿。", "问", "答", "侧言"]);
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
      msg({ role: "scene", speaker: "洪承畴", content: "洪承畴趋入殿中。", beat: "entrance" }),
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
    expect(hong.map((m) => m.content)).toEqual([
      "",
      "洪承畴趋入殿中。",
      "边务如何？",
      "臣自三边来。",
      "殿侧容臣插一句。",
      "",
    ]);
    expect(hong.some((m) => m.content.includes("杨"))).toBe(false);
    expect(hong.some((m) => m.content === "杨部神色郑重。")).toBe(false);

    const yang = filterScrollForSelectedMinister(scroll, "杨嗣昌");
    expect(yang.map((m) => m.content)).toEqual([
      "杨卿以为如何？",
      "臣以为当先清饷。",
      "杨部神色郑重。",
    ]);
    expect(yang.some((m) => m.content === "臣自三边来。")).toBe(false);
    expect(yang.some((m) => m.content === "洪承畴趋入殿中。")).toBe(false);
    expect(yang.some((m) => m.content === "殿侧容臣插一句。")).toBe(false);
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
      filterScrollForSelectedMinister(scroll, "许誉卿", { claimedTurnId: 12 }).map((m) => m.content),
    ).toEqual(["辽饷何解？"]);
    // Claim must not override an already-named minister owner on another turn.
    expect(
      filterScrollForSelectedMinister(scroll, "许誉卿", { claimedTurnId: 11 }).map((m) => m.content),
    ).toEqual([]);
  });
});
