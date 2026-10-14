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

## Layout

- `src/api.ts`: typed API client; types follow `web_fixtures/api_samples.json`
- `src/types.ts`: form draft state and its mapping to the `/api/recommend` form
- `src/components/`: `TopBar`, `AskBox`, `Questionnaire`, `PartyPanel`, `ResultView`, `GameCard`, `Chips`, plus small inputs (`GameSearch`, `TagPicker`, `LibraryConnect`, `FormBits`)
