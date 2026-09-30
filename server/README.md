# Steam Auth Server

This is the trusted backend endpoint for Steam login. #1888 retired the Electron
client shell, so no shipped client calls it today. Its transport/auth residue is
owned by #1816, which retires the login seam server-side; this file documents
what still exists until that work lands, and makes no retention decision.

Do not bundle this server or `STEAM_PUBLISHER_WEB_API_KEY` with the game client.

## Run

```bash
export STEAM_PUBLISHER_WEB_API_KEY="your publisher web api key"
export STEAM_APP_ID="your_app_id"
export STEAM_AUTH_IDENTITY="ming-salvage-server"
export STEAM_AUTH_ALLOWED_ORIGINS="https://your-domain.example"

uvicorn server.steam_auth_server:app --host 0.0.0.0 --port 8080
```

For local development only:

```bash
export STEAM_PUBLISHER_WEB_API_KEY="your publisher web api key"
export STEAM_APP_ID="your_app_id"
export STEAM_AUTH_IDENTITY="ming-salvage-server"

uvicorn server.steam_auth_server:app --host 127.0.0.1 --port 8080
```

#1888：Electron 客户端壳已退役，客户端调用方（`window.steam` 与 `web/electron/`）
已撤下；正式桌面包装是 PyInstaller + pywebview（见 `scripts/build_release.sh`）。
本服务端本身归 #1816 处置，本票不代删、也不代其决定去留。

## Client Payload

The Steam client sends:

```json
{
  "appid": "your_app_id",
  "identity": "ming-salvage-server",
  "ticket": "hex-encoded steam auth ticket",
  "steamId64": "client-reported value for logs only",
  "personaName": "client-reported value for logs only"
}
```

The server trusts only the `steamid` returned by Steam's `AuthenticateUserTicket` response.
