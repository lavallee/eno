# eno-plugin

Obsidian plugin for [eno](../..). UI surface; all logic lives in `eno-service`.

## Build

```sh
npm install
npm run build      # writes main.js
npm run typecheck  # tsc --noEmit
npm run dev        # esbuild watch mode
```

## Install into a vault

```sh
mkdir -p <vault>/.obsidian/plugins/eno
cp main.js manifest.json styles.css <vault>/.obsidian/plugins/eno/
```

Then enable in Obsidian → Settings → Community plugins.

For development, symlink the build output instead of copying so `npm run dev` updates land live (Obsidian → Cmd-R to reload):

```sh
ln -s "$(pwd)/main.js"      <vault>/.obsidian/plugins/eno/main.js
ln -s "$(pwd)/manifest.json" <vault>/.obsidian/plugins/eno/manifest.json
ln -s "$(pwd)/styles.css"   <vault>/.obsidian/plugins/eno/styles.css
```

## Configure

Settings → Eno:

- **Service URL** — defaults to `http://127.0.0.1:7891` (local). Set to `http://dash-main:7891` (or its tailnet IP) when pointing at the dash-main daemon.
- **Reports folder** — vault-relative folder where `eno garden` and `eno hygiene --propose` write reports. Default `9 Vault Health`.

## What it does

- **Right-pane "Vault Health" view** (ribbon icon: 🌸): service status + counts from the latest garden + hygiene reports.
- **Commands** (palette):
  - `Eno: Open vault health view`
  - `Eno: Garden now` (POST /garden, summary toast)
  - `Eno: Open latest garden report`
  - `Eno: Open latest hygiene proposals`
  - `Eno: Show neighbors of active note`

## Wire format

Counts come from the report files' frontmatter (Python's `render_garden_report` and `render_report` add structured YAML at the top of every file). The plugin reads via Obsidian's `metadataCache.getFileCache(...).frontmatter.counts` — no markdown parsing.
