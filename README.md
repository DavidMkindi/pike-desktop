# ✨ Pike

A polished **AI desktop app** built with **Python + Flask** (backend) and **HTML, CSS, JavaScript & Bootstrap 5** (frontend). It runs in its own native desktop window (via `pywebview`) or in your browser, streams answers token-by-token, and keeps your conversation history in a local SQLite database.

```
┌──────────────┐      HTTP / SSE      ┌────────────────────┐      HTTPS      ┌──────────────────┐
│  Desktop UI  │  ─────────────────►  │   Flask backend    │  ───────────►   │  OpenAI-compatible │
│ (Bootstrap)  │  ◄─────────────────  │  routes + SQLite   │  ◄───────────   │  AI provider       │
└──────────────┘   streaming tokens   └────────────────────┘                 └──────────────────┘
```

---

## Features

- **Native desktop window** with `pywebview` — no browser chrome, own taskbar entry.
- **Real-time streaming** answers over Server-Sent Events (SSE), token by token.
- **Markdown rendering** with code blocks, syntax labels, and one-click copy.
- **Multiple conversations** with history, search, rename, and delete.
- **Multiple models** (GPT-4o, GPT-4o mini, GPT-4.1, …) switchable on the fly.
- **Works with any OpenAI-compatible API** — OpenAI, Groq, Together, OpenRouter, Ollama, LM Studio, …
- **BYO API key**, stored locally on your machine (never in the project).
- **Polished dark UI**: animated welcome orb, suggestion cards, toasts, responsive sidebar.
- **Keyboard friendly**: `Enter` to send, `Shift+Enter` for newline, `Ctrl+K` new chat, `Esc` to stop.
- **One-click `.exe`** build with PyInstaller.

---

## Project structure

```
AI/
├── app.py                 # Flask app: routes, SSE streaming, desktop launcher
├── config.py              # Settings, .env loading, per-user data directory
├── ai_client.py           # OpenAI-compatible client (streaming + non-streaming)
├── database.py            # SQLite persistence for conversations
├── requirements.txt       # Python dependencies
├── build_exe.py           # PyInstaller one-file executable builder
├── run.bat / run.sh       # One-command launchers (venv + install + run)
├── .env.example           # Copy to .env to configure secrets
├── templates/
│   └── index.html         # The app shell (Bootstrap CDN + icons)
└── static/
    ├── css/style.css      # Full custom design system
    └── js/app.js          # Frontend logic: streaming, history, markdown
```

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

> Prefer an isolated environment?
> ```bash
> python -m venv .venv
> .venv\Scripts\activate      # Windows
> source .venv/bin/activate   # macOS / Linux
> pip install -r requirements.txt
> ```

### 2. Run it

```bash
python app.py
```

That's it — the desktop window opens automatically.

**Other launch modes**

| Command | What it does |
| --- | --- |
| `python app.py` | Desktop window (pywebview) |
| `python app.py --browser` | Opens in your default browser |
| `python app.py --server` | Flask server only, no window |
| `python app.py --port 9000` | Use a custom port |

Or just double-click **`run.bat`** (Windows) / run **`./run.sh`** (macOS/Linux) and it will set up everything for you.

### 3. Connect your AI

On first launch, click **API key** in the top bar (or the gear icon in the sidebar):

1. Paste your API key.
2. *(Optional)* Change the **Base URL** if you use a non-OpenAI provider.
3. Click **Test connection** to confirm it works, then **Save connection**.

Your key is stored in your user data folder:

- **Windows:** `%APPDATA%\Pike\settings.json`
- **macOS:** `~/Library/Application Support/Pike/settings.json`
- **Linux:** `~/.local/share/pike/settings.json`

You can also skip the UI and set an environment variable instead (see below).

---

## Configuration

Copy `.env.example` to `.env` and edit it, or set these environment variables directly:

| Variable | Default | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | *(empty)* | Your API key. Overrides the saved key. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Default model on startup. |
| `PIKE_MODELS` | *(built-in list)* | Override models, e.g. `llama3.2,mixtral:Mixtral 8x7B`. |
| `PIKE_REASONING_EFFORT` | `medium` | Thinking level for reasoning models: `off`, `low`, `medium`, `high`. |
| `PIKE_OPENAI_API_KEY` | *(empty)* | Override the OpenAI key without editing `config.py`. |
| `PIKE_OPENAI_BASE_URL` | `https://api.openai.com/v1` | Override the OpenAI base URL. |
| `PIKE_HOST` | `127.0.0.1` | Bind address. |
| `PIKE_PORT` | `8765` | Port. |
| `PIKE_DEBUG` | `false` | Enable Flask debug mode. |
| `PIKE_BROWSER_ONLY` | `false` | Always use the browser instead of the desktop window. |
| `PIKE_TIMEOUT` | `120` | Provider request timeout in seconds. |
| `PIKE_SYSTEM_PROMPT` | friendly assistant | Base system prompt. |
| `PIKE_UPDATE_REPO` | `DavidMkindi/pike-desktop` | GitHub `owner/repo` the **Update** button pulls releases from. |
| `PIKE_GITHUB_TOKEN` | *(empty)* | Token with `repo` scope for reading releases from a **private** repo. |
| `PIKE_UPDATE_URL` | *(empty)* | Optional legacy JSON manifest URL for the **Update** button. |
| `PIKE_RELEASES_URL` | *(empty)* | Fallback link opened when there is no download available. |
| `PIKE_DATA_DIR` | per-user | Where `settings.json` and `history.sqlite3` live. |

### Built-in models

Providers are declared in `config.py`. Pike ships with the official provider
catalogues (OpenAI, Anthropic, Google Gemini, xAI, DeepSeek, Mistral, Groq,
OpenRouter, Perplexity, Moonshot, Z.ai, Qwen, Together, Cohere, Cerebras,
Amazon Nova, Ollama, LM Studio and a custom endpoint). The model dropdown
always shows **every** model from every provider — adding a key for one
provider never hides the others. Models whose provider has no key yet are
tagged **Add key** and simply prompt you to configure that provider.

Models flagged `reasoning: True` expose a **Thinking** level dropdown styled
exactly like the model selector, sitting next to it in the composer:

| Level | Behaviour |
| --- | --- |
| `off` | Answer straight away, no thinking section. |
| `low` | Quick reasoning. |
| `medium` | Balanced (default). |
| `high` | Deep reasoning. |

The picker only appears for models flagged `reasoning: True` (the GPT models).
DeepSeek V4.1 Flash is **not** a thinking model here, so it shows no picker and
its reasoning is hidden. When a thinking model is selected, the reply grows a
collapsible **Thinking** section while the model works. It collapses by default
— click it to read the full reasoning, and the header shows how long it thought.

### Using a local model (Ollama example)

```env
OPENAI_API_KEY=ollama
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=llama3.2
PIKE_MODELS=llama3.2:Llama 3.2,qwen2.5:Qwen 2.5
```

---

## Build a standalone executable

```bash
pip install pyinstaller
python build_exe.py
```

The result lands in `dist/`:

- Windows → `dist/Pike.exe`
- macOS / Linux → `dist/Pike`

The executable is self-contained (templates + static assets are bundled). Settings and history are written to the per-user data folder so the app works even from a read-only location.

---

## Updates

The title-bar **Update** button (and Settings → About → *Check for updates*)
checks GitHub Releases for the configured repository and, when a newer build
exists, downloads it and runs the bundled Inno Setup installer silently. The
installer closes Pike, replaces it and relaunches it.

Because `DavidMkindi/pike-desktop` is **private**, the updater needs a token
with `repo` scope. It looks in this order:

1. `PIKE_GITHUB_TOKEN` (environment or `.env`).
2. `GITHUB_TOKEN` / `GH_TOKEN`.
3. A token pasted in **Settings → About → GitHub token**.
4. The `gh` CLI, when it is installed and signed in.

Publishing a release is automatic: push a version tag and the
`Build Windows app + installer` workflow attaches `Pike.exe` and
`Pike-<version>-Setup.exe` to the release.

```bash
git tag v1.2.0 && git push origin v1.2.0
```

Downloaded builds are staged in `%APPDATA%\Pike\updates\` and verified
against the asset's SHA-256 digest before installation.

---

## API reference

The Flask backend exposes a small JSON + SSE API (handy if you want to embed the UI elsewhere).

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/` | The single-page frontend |
| `GET` | `/healthz` | Liveness probe |
| `GET` | `/api/status` | Connection status, models, active model |
| `GET` | `/api/update` | Check GitHub Releases for a newer build |
| `POST` | `/api/update/download` | Download the newest release in the background |
| `GET` | `/api/update/progress` | Poll the background download |
| `POST` | `/api/update/cancel` | Cancel an in-flight download |
| `POST` | `/api/update/apply` | Install the downloaded build and restart |
| `GET` / `POST` | `/api/settings` | Read / update API key, base URL, default model, GitHub token |
| `POST` | `/api/settings/test` | Send a tiny test prompt to the provider |
| `POST` | `/api/chat` | Non-streaming completion |
| `POST` | `/api/chat/stream` | **Streaming** completion (SSE: `start`, `delta`, `done`, `error`) |
| `GET` | `/api/conversations?q=` | List / search conversations |
| `POST` | `/api/conversations` | Create an empty conversation |
| `GET` | `/api/conversations/<id>` | Fetch one conversation with messages |
| `PUT` | `/api/conversations/<id>` | Replace messages |
| `PATCH` | `/api/conversations/<id>` | Rename |
| `DELETE` | `/api/conversations/<id>` | Delete one |
| `DELETE` | `/api/conversations` | Delete all |
| `POST` | `/api/conversations/save` | Upsert a conversation (auto-titles) |

### SSE format

```
event: delta
data: {"text": "Hello"}

event: done
data: {"reply": "Hello world", "elapsed": 1.24}
```

---

## Troubleshooting

**"No API key configured"** — Open the API key dialog and save a key, or set `OPENAI_API_KEY` and restart.

**The desktop window is blank / pywebview fails** — make sure `pywebview` installed correctly for your OS. As a fallback, run `python app.py --browser`. On Linux you may need a webkit backend (`sudo apt install python3-gi gir1.2-webkit2-4.1`).

**"Could not reach the AI provider"** — check your internet connection and that the **Base URL** matches your provider.

**401 / 403 errors** — the key is invalid or lacks access to the selected model. Try **Test connection** in the dialog.

**Port already in use** — start with `python app.py --port 9000`.

---

## Tech stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.9+, Flask, requests |
| Desktop shell | pywebview |
| Database | SQLite (standard library) |
| Frontend | HTML5, CSS3, vanilla JS (ES2020) |
| Styling | Bootstrap 5.3 + Bootstrap Icons (CDN) + custom design system |
| Rendering | marked.js + DOMPurify (CDN) |
| Packaging | PyInstaller |

---

## License

Released for free use and modification. Bring your own API key — usage costs are billed by your provider.

Built with care. Enjoy your new thinking partner. ✨