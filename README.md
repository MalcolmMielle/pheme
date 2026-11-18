# Pheme

[![PyPI version](https://img.shields.io/pypi/v/pheme-reviews)](https://pypi.org/project/pheme-reviews/)
[![Forgejo release](https://forge.mielle.dev/MielleLabs/pheme/badges/release.svg)](https://forge.mielle.dev/MielleLabs/pheme/releases)
[![Python CI](https://forge.mielle.dev/MielleLabs/pheme/badges/workflows/python.yml/badge.svg)](https://forge.mielle.dev/MielleLabs/pheme/actions)
[![React CI](https://forge.mielle.dev/MielleLabs/pheme/badges/workflows/react.yml/badge.svg)](https://forge.mielle.dev/MielleLabs/pheme/actions)
[![License](https://img.shields.io/badge/license-AGPL--3.0--only-blue)](LICENSE)

A decentralised review platform that looks and feels like Google Maps /
OpenStreetMap — but built on ActivityPub so that independent servers can
federate reviews with each other.  Mastodon, but for location-based
reviews.

![Pheme — map view with review markers and the sidebar review list](https://forge.mielle.dev/MielleLabs/pheme/raw/branch/main/docs/screenshot.png)

> [!Warning]
>
> This app is:
>
> 1. Coded with Mistral AI (using Mistral Large 4)
> 2. a proof of concept and does not come with any guarantees atm.
>
> This is a disclaimer so you can choose for yourself if you want to use it or not.
> I mostly did this because I didn't have an alternative for Google map and I couldn't
> convince anyone else to do this before.

## Quick start

**Prerequisites:** Python ≥ 3.13, [uv](https://docs.astral.sh/uv/),
Node.js ≥ 20

```bash
# Clone and enter the project
git clone https://forge.mielle.dev/MielleLabs/pheme.git pheme
cd pheme

# Install backend dependencies
uv sync

# Create a .env file from the template and set SECRET_KEY at minimum
cp .env.example .env

# Install + build the React frontend (react-app/)
cd react-app && npm ci && npm run build && cd ..

# Seed demo data (creates actor "alice" + sample reviews)
uv run bootstrap

# Start the development server
uv run pheme
```

Open **<http://localhost:8000>** — you should see a map with coloured
markers.  Click any marker or sidebar card to see the review detail.
Click the **＋** button to write your own review.

## Documentation

- [How it works](docs/how-it-works.md) — the ActivityPub model, the federation
  flow, and the tech stack
- [Development](docs/development.md) — frontend hot reload, tests, linting,
  project layout, releasing
- [Deploying to your own server](docs/deployment.md) — VPS setup with Caddy,
  systemd, firewall, backups (copy-paste, no coding required)
- [Configuration](docs/configuration.md) — every environment variable,
  registration modes, moderation
- [API reference](docs/api.md) — ActivityPub and JSON API endpoints

## Contribute & deploy

- **Contribute** — the source lives on Forgejo:
  <https://forge.mielle.dev/MielleLabs/pheme> (issues and pull requests
  welcome)
- **Deploy your own instance** — install the published package from PyPI:
  <https://pypi.org/project/pheme-reviews/> (`uv tool install pheme-reviews`),
  or follow the [deployment guide](docs/deployment.md)

## Licence

GNU Affero General Public License v3.0 only (AGPL-3.0-only) — see [LICENSE](LICENSE).
