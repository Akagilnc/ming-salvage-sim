export type SteamEvent =
  | { type: "add_stat_int"; name: string; delta: number }
  | { type: "set_stat_int"; name: string; value: number };

export type SteamEventPayload = {
  steam_events?: SteamEvent[];
};

export const forwardSteamEvents = async (payload: unknown) => {
  const events = (payload as SteamEventPayload | null)?.steam_events;
  if (!Array.isArray(events) || !window.steam) return;

  for (const event of events) {
    try {
      if (event.type === "add_stat_int") {
        const result = await window.steam.addStatInt(event.name, event.delta);
        if (!result.ok) console.warn("[steam] addStatInt failed", event, result);
      } else if (event.type === "set_stat_int") {
        const result = await window.steam.setStatInt(event.name, event.value);
        if (!result.ok) console.warn("[steam] setStatInt failed", event, result);
      }
    } catch (error) {
      console.warn("[steam] event forwarding failed", event, error);
    }
  }

  try {
    const result = await window.steam.flushStats();
    if (!result.ok) console.warn("[steam] flushStats failed", result);
  } catch (error) {
    console.warn("[steam] flushStats threw", error);
  }
};
