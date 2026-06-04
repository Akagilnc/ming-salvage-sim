# Steam Auth Server

This is the trusted backend endpoint for Electron Steam login.

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

Then launch Electron with:

```bash
MING_SIM_STEAM_APP_ID=your_app_id \
MING_SIM_STEAM_AUTH_URL=http://127.0.0.1:8080/steam/login \
npm --prefix web run electron
```

## Client Payload

Electron sends:

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
