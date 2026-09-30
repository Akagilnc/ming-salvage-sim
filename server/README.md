# Steam Auth Server

This is the trusted backend endpoint for Steam login. #1888 retired the Electron
client shell, so no shipped client calls it today; it is kept for a future
Steam release.

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
已撤下；本文件描述的 Steam 登录认证服务端暂留以备后按需接回，正式桌面包装是
PyInstaller + pywebview（见 `scripts/build_release.sh`）。

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
