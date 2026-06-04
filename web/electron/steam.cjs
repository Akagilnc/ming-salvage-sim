const STEAM_STAT_NAMES = new Set([
  "STAT_RUNS_STARTED",
  "STAT_TURNS_PLAYED",
  "STAT_DECREES_ISSUED",
  "STAT_SAVES_CREATED",
  "STAT_ENDINGS_REACHED",
  "STAT_MAX_TURN_REACHED",
]);

const MAX_STAT_NAMES = new Set(["STAT_MAX_TURN_REACHED"]);
const DEFAULT_AUTH_IDENTITY = process.env.MING_SIM_STEAM_AUTH_IDENTITY || "ming-salvage-server";
const AUTH_TICKET_TTL_MS = 10 * 60 * 1000;
const DEFAULT_AUTH_URL = process.env.MING_SIM_STEAM_AUTH_URL || "";

let client = null;
let initAttempted = false;
let initError = "";
let nextAuthTicketId = 1;
const activeAuthTickets = new Map();

const log = (...args) => console.log("[steam]", ...args);
const warn = (...args) => console.warn("[steam]", ...args);

const parseAppId = () => {
  const raw = process.env.MING_SIM_STEAM_APP_ID || process.env.STEAM_APP_ID || "";
  const appId = Number.parseInt(raw, 10);
  return Number.isFinite(appId) && appId > 0 ? appId : undefined;
};

const normalizeInt = (value, fallback = 0) => {
  const n = Number.parseInt(String(value), 10);
  if (!Number.isFinite(n)) return fallback;
  return n;
};

const statNameOrThrow = (name) => {
  const statName = String(name || "").trim();
  if (!STEAM_STAT_NAMES.has(statName)) {
    throw new Error(`Unsupported Steam stat: ${statName || "(empty)"}`);
  }
  return statName;
};

const getClient = () => {
  if (client || initAttempted) return client;
  initAttempted = true;
  try {
    const steamworks = require("steamworks.js");
    const appId = parseAppId();
    client = typeof appId === "number" ? steamworks.init(appId) : steamworks.init();
    log(`initialized${typeof appId === "number" ? ` appId=${appId}` : ""}`);
  } catch (error) {
    initError = error instanceof Error ? error.message : String(error);
    client = null;
    warn("unavailable:", initError);
  }
  return client;
};

const unavailable = () => ({
  ok: false,
  available: false,
  appId: parseAppId() ?? null,
  error: initError || "Steamworks is not initialized.",
});

const normalizeIdentity = (identity) => {
  const value = String(identity || DEFAULT_AUTH_IDENTITY).trim();
  return value || DEFAULT_AUTH_IDENTITY;
};

const normalizeAuthUrl = (url) => {
  const value = String(url || DEFAULT_AUTH_URL).trim();
  if (!value) throw new Error("Steam auth server URL is not configured.");
  const parsed = new URL(value);
  const isLocalHttp =
    parsed.protocol === "http:" &&
    ["localhost", "127.0.0.1", "::1"].includes(parsed.hostname);
  if (parsed.protocol !== "https:" && !isLocalHttp) {
    throw new Error("Steam auth server URL must be https://, except localhost development URLs.");
  }
  return parsed.toString();
};

const parseServerResponse = async (response) => {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
};

const statusPayload = (steam) => {
  const steamId = steam.localplayer.getSteamId();
  return {
    appId: steam.utils.getAppId(),
    steamId64: steamId?.steamId64?.toString?.() || "",
    personaName: steam.localplayer.getName(),
  };
};

const getStatus = () => {
  const steam = getClient();
  if (!steam) return unavailable();
  try {
    return {
      ok: true,
      available: true,
      ...statusPayload(steam),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    warn("status failed:", message);
    return { ...unavailable(), error: message };
  }
};

const cancelAuthTicket = (ticketId) => {
  const key = String(ticketId || "");
  const entry = activeAuthTickets.get(key);
  if (!entry) {
    return { ok: false, available: Boolean(client), ticketId: key, error: "Auth ticket not found." };
  }
  activeAuthTickets.delete(key);
  clearTimeout(entry.timer);
  try {
    entry.ticket.cancel();
    return { ok: true, available: Boolean(client), ticketId: key };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    warn("cancelAuthTicket failed:", message);
    return { ok: false, available: Boolean(client), ticketId: key, error: message };
  }
};

const rememberAuthTicket = (ticket) => {
  const ticketId = String(nextAuthTicketId++);
  const timer = setTimeout(() => {
    cancelAuthTicket(ticketId);
  }, AUTH_TICKET_TTL_MS);
  timer.unref?.();
  activeAuthTickets.set(ticketId, { ticket, timer });
  return ticketId;
};

const getAuthTicket = async (identity) => {
  const steam = getClient();
  if (!steam) return unavailable();
  const normalizedIdentity = normalizeIdentity(identity);
  try {
    const ticket = await steam.auth.getAuthTicketForWebApi(normalizedIdentity);
    const ticketBytes = ticket.getBytes();
    const ticketId = rememberAuthTicket(ticket);
    return {
      ok: true,
      available: true,
      ...statusPayload(steam),
      identity: normalizedIdentity,
      ticket: Buffer.from(ticketBytes).toString("hex"),
      ticketId,
      expiresInSeconds: Math.floor(AUTH_TICKET_TTL_MS / 1000),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    warn("getAuthTicket failed:", message);
    return { ok: false, available: true, identity: normalizedIdentity, error: message };
  }
};

const authenticateWithServer = async (options = {}) => {
  let authTicket = null;
  try {
    const url = normalizeAuthUrl(options.url);
    const identity = normalizeIdentity(options.identity);
    authTicket = await getAuthTicket(identity);
    if (!authTicket.ok) return authTicket;

    const requestBody = {
      appid: authTicket.appId,
      identity: authTicket.identity,
      ticket: authTicket.ticket,
      steamId64: authTicket.steamId64,
      personaName: authTicket.personaName,
      ...(options.payload && typeof options.payload === "object" ? options.payload : {}),
    };

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(options.headers && typeof options.headers === "object" ? options.headers : {}),
      },
      body: JSON.stringify(requestBody),
    });
    const data = await parseServerResponse(response);

    return {
      ok: response.ok,
      available: true,
      appId: authTicket.appId,
      steamId64: authTicket.steamId64,
      personaName: authTicket.personaName,
      identity: authTicket.identity,
      status: response.status,
      data,
      error: response.ok ? undefined : `Steam auth server returned HTTP ${response.status}.`,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    warn("authenticateWithServer failed:", message);
    return { ok: false, available: Boolean(client), error: message };
  } finally {
    if (authTicket?.ticketId) {
      cancelAuthTicket(authTicket.ticketId);
    }
  }
};

const readStatInt = (steam, statName) => {
  const value = steam.stats.getInt(statName);
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
};

const storeStats = (steam) => {
  const stored = steam.stats.store();
  if (!stored) warn("storeStats returned false");
  return stored;
};

const addStatInt = (name, delta) => {
  const steam = getClient();
  if (!steam) return unavailable();
  try {
    const statName = statNameOrThrow(name);
    const amount = normalizeInt(delta, 0);
    const previous = readStatInt(steam, statName);
    const value = previous + amount;
    const setOk = steam.stats.setInt(statName, value);
    const storeOk = storeStats(steam);
    return { ok: Boolean(setOk && storeOk), available: true, name: statName, previous, value };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    warn("addStatInt failed:", message);
    return { ok: false, available: true, error: message };
  }
};

const setStatInt = (name, value) => {
  const steam = getClient();
  if (!steam) return unavailable();
  try {
    const statName = statNameOrThrow(name);
    const requested = normalizeInt(value, 0);
    const previous = readStatInt(steam, statName);
    const next = MAX_STAT_NAMES.has(statName) ? Math.max(previous, requested) : requested;
    const setOk = steam.stats.setInt(statName, next);
    const storeOk = storeStats(steam);
    return { ok: Boolean(setOk && storeOk), available: true, name: statName, previous, value: next };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    warn("setStatInt failed:", message);
    return { ok: false, available: true, error: message };
  }
};

const flushStats = () => {
  const steam = getClient();
  if (!steam) return unavailable();
  try {
    return { ok: Boolean(storeStats(steam)), available: true };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    warn("flushStats failed:", message);
    return { ok: false, available: true, error: message };
  }
};

module.exports = {
  getStatus,
  getAuthTicket,
  cancelAuthTicket,
  authenticateWithServer,
  addStatInt,
  setStatInt,
  flushStats,
};
