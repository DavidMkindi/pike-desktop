# Pike — website

The public marketing and documentation site for **Pike**, the desktop AI
workspace. It is a standalone Flask application that lives beside the desktop
app and shares its design language, but it has no dependency on the app's code
and can be deployed on its own.

```
website/
├── app.py                  # Flask app: pages, context, small JSON API
├── requirements.txt        # Flask only
├── run.bat / run.sh        # One-command launchers
├── templates/
│   ├── base.html           # Shared shell: head, nav, footer
│   ├── index.html          # Landing page
│   ├── features.html       # Feature deep dive
│   ├── download.html       # Downloads + run-from-source
│   ├── docs.html           # Documentation
│   ├── changelog.html      # Release timeline
│   ├── about.html          # Project story
│   ├── contact.html        # Get in touch
│   ├── error.html          # 404 / 500
│   └── partials/
│       ├── nav.html        # Header + navigation
│       ├── footer.html     # Site footer
│       └── icons.html      # Inline SVG icon sprite
└── static/
    ├── css/site.css        # Full design system (app tokens)
    ├── js/site.js          # Theme, nav, reveal, copy, TOC
    └── img/                # pike.svg, favicon.svg
```

## Run it

```bash
cd website
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000/>.

### Options

| Command | What it does |
| --- | --- |
| `python app.py` | Start on `127.0.0.1:5000` |
| `python app.py --port 8000` | Use a custom port |
| `python app.py --host 0.0.0.0` | Bind to all interfaces |
| `python app.py --debug` | Debug mode + auto-reload |

Or with the Flask CLI:

```bash
flask --app app run --port 5000
```

Environment variables `PIKE_WEB_HOST` and `PIKE_WEB_PORT` work too.

## Pages

| Route | Page |
| --- | --- |
| `/` | Landing page |
| `/features` | Feature deep dive |
| `/download` | Platform downloads + run from source |
| `/docs` | Documentation (quick start, config, providers, API) |
| `/changelog` | Release timeline |
| `/about` | Project story |
| `/contact` | Contact channels |
| `/healthz` | Liveness probe (JSON) |
| `/api/product` | Product metadata (JSON) |

## Design

The site reuses the desktop app's design tokens — the same grey scale, the muted
blue accent (`#7aa2f7`), the violet brand gradient, Inter + JetBrains Mono, and
the same radii and shadows. It ships a dark theme by default with a light theme
toggle, both driven by CSS custom properties.

## Editing content

- **Product metadata** (version, links, tagline) lives in the `PRODUCT` dict at
  the top of `app.py`.
- **Providers, features and changelog entries** are plain lists in `app.py`.
- **Styling** is entirely in `static/css/site.css`; every colour comes from a
  token in `:root`.

## Notes

- No build step, no JavaScript framework, no CDN JS. Only Google Fonts is
  loaded remotely; everything else is local.
- The Flask app exposes a few security headers (`X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`) by default.