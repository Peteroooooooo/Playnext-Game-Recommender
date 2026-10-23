# Playnext web

React 18 + Vite 5 + TypeScript, plain CSS. All UI text is Simplified Chinese.

## Dev

Run the backend and the Vite dev server (it proxies `/api` to `127.0.0.1:8000`):

```
uv run uvicorn --app-dir src playnext.api:app --port 8000
npm --prefix web install
npm --prefix web run dev
```

Open http://localhost:5173.

## Prod

```
npm --prefix web run build
```

Then start the backend as above; it serves `web/dist` at http://127.0.0.1:8000. The backend checks for `web/dist` at startup, so restart it after the first build.

Tests: `npm --prefix web test` (vitest, `src/*.test.ts`).

## Layout

Look and interaction follow `docs/mockups/card_redesign.html`: one search field, blurred game art behind the page, posters, a detail sheet.

- `src/api.ts`: typed API client; types follow `web_fixtures/api_samples.json`
- `src/types.ts`: the form sent with the text (store region) or alone (game search when the LLM is unavailable)
- `src/i18n.ts`: every UI text in Chinese and English, the language toggle's storage, `useT()`; the API client sends the language with each request
- `src/present.ts`: pure text helpers (chips, prices, badges, near-miss labels, reason reveal, progress steps)
- `src/guide.ts`: example games, demo posters and prices behind the home screen and the "?" guide; "+" chip helpers
- `src/components/`: `TopBar` (language + store pill, Steam pill and their popovers), `Search` (field, typed example, hopping "?", × reset), `Guide` (the "?" panel), `Backdrop`, `Results` (shelf, backups, near misses, Steam nudge), `Sheet` (detail dialog), `LibraryConnect`, `FactReport`, `icons`
