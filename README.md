# Soko Chat

Soko Chat is a Python desktop chat client and a separate FastAPI backend. The desktop UI is a native PySide6 application; it does not open a browser for chat use. The backend must stay online for accounts and messages to work.

## Run locally on Windows

You need Python 3.11 or newer. Open the project folder in PowerShell:

```powershell
cd "$env:USERPROFILE\Documents\Codex\2026-10-09\files-mentioned-by-the-user-prompt\outputs\komunikator"
$python = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
& $python -m venv .venv
Copy-Item .env.example .env
notepad .env
```

In `.env`, set `APP_SECRET` to a private random value with at least 32 characters, then save the file. Install and run the backend:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn server.main:app --reload
```

Leave that PowerShell window open. In a second PowerShell window, install and run the desktop app:

```powershell
cd "$env:USERPROFILE\Documents\Codex\2026-10-09\files-mentioned-by-the-user-prompt\outputs\komunikator"
.\.venv\Scripts\python.exe -m pip install -r client\requirements.txt
.\.venv\Scripts\python.exe -m client.main
```

Use **Utwórz konto** and **Zaloguj się** inside the desktop application. The OpenAPI page at `http://127.0.0.1:8000/docs` is for API development only.

## Current functionality

- Native dark desktop window named Soko Chat.
- Registration and login inside the application.
- Create servers; each new server gets a general text channel.
- Create seven-day invitation codes and join existing servers with a code.
- View the member list for each server.
- Find Soko Chat accounts by username, send/accept/reject friend requests, and remove friends.
- Choose a light or dark theme in Settings; the selection is saved.
- Optional stay-signed-in using the Windows credential vault, with a beta notice after login.
- View channels and the latest 50 messages.
- Send messages with live updates over WebSocket.
- HTTP requests run in worker threads; message WebSocket reconnects automatically.
- FastAPI backend with SQLAlchemy, SQLite, Argon2id password hashing and expiring opaque sessions.

Not implemented yet: private and group conversations, block controls, online presence, and GUI for editing/deleting messages. The Windows build is distributed as a ZIP containing the desktop app. Server invitation codes are currently created by the server owner, expire after seven days, and can be shared with other accounts.

## Hosting and GitHub plan

GitHub holds the source code and release downloads. The static download page is in `site/`; `.github/workflows/pages.yml` publishes it with GitHub Pages. `.github/workflows/build-release.yml` builds the Windows ZIP and updates the beta download when `main` changes. The API runs separately on Render and uses PostgreSQL; `render.yaml` is its deployment blueprint. GitHub Pages cannot run this Python API server or its database.

### Publish the beta online

1. Create a PostgreSQL project with [Neon](https://neon.tech/). Copy its connection string (it starts with `postgresql://` and includes SSL settings). The app converts it to the async PostgreSQL driver automatically.
2. Open the [Render Blueprint deploy page](https://render.com/deploy?repo=https://github.com/antyziel-soko/soko-chat) and connect the `antyziel-soko/soko-chat` repository. When asked for `DATABASE_URL`, paste the Neon connection string. Render generates `APP_SECRET` for you. The blueprint uses Render's free web service for beta testing; free instances sleep after 15 minutes without traffic and can take about a minute to wake up. Neon free usage also has limits; check its current plan before relying on it for important data.
3. The Render service is named `soko-chat-api`; its expected address is `https://soko-chat-api.onrender.com`. If Render assigns another address, set it in the app's **Adres backendu** field and update the hosted API URL in `.github/workflows/build-release.yml` before the next build.
4. In the GitHub repository, open **Settings → Pages** and set **Source** to **GitHub Actions**. The download page will appear at `https://antyziel-soko.github.io/soko-chat/` after the workflow finishes.
5. Push these changes to `main`. GitHub Actions builds the Windows app and publishes the beta ZIP at the download page. New accounts and messages created against the hosted server are separate from data in the local `data/` folder.

For the beta, do not use a password you use on other sites. Never publish `.env`, database connection strings, session secrets, user data, or the SQLite database; `.gitignore` excludes local secrets, virtual environments, and database files.

## Backend API

- `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `POST /auth/logout-all`
- `GET /users/me`, `DELETE /users/me`
- `POST /servers`, `GET /servers`, `POST /servers/{server_id}/channels`, `GET /servers/{server_id}/channels`
- `POST /servers/{server_id}/invites`, `POST /invites/{code}/join`, `GET /servers/{server_id}/members`
- `GET /users/lookup?username=...`, `GET /friends`, `GET /friends/requests`
- `POST /friends/{user_id}/requests`, `POST /friends/{user_id}/accept`, `DELETE /friends/{user_id}`
- `GET /channels/{channel_id}/messages?before_id=&limit=`
- `POST /channels/{channel_id}/messages`, `PATCH /messages/{message_id}`, `DELETE /messages/{message_id}`
- `WS /ws/channels/{channel_id}` — authenticate with the first JSON frame `{"type":"authenticate","token":"..."}`

The initial SQLite schema is created automatically for local development. Before public deployment, add Alembic migrations, use HTTPS and PostgreSQL, and replace the in-process rate limiters with a shared limiter such as Redis.
