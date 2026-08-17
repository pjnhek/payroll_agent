# Vite manifest shape

Recorded from a real `npm run build` (Vite `8.2.1`), not inferred from documentation. This is
the input `render_react_page()`'s manifest loader is written against.

## Manifest file path

Relative to the configured `build.outDir` (`app/static/dist`, set in `vite.config.ts`), the
manifest lands at:

```
.vite/manifest.json
```

So the full path from the repo root, after a build, is `app/static/dist/.vite/manifest.json`.

## Top-level key for the `runs` entry

The manifest's top-level keys are the entry's **source path relative to the project root**, not
the short name given in `rollupOptions.input`. For the `runs` entry
(`rollupOptions.input.runs = "src/entries/runs.tsx"`), the manifest key is:

```
src/entries/runs.tsx
```

A loader resolving an entry by its short name (`runs`) must build the key as
`` `src/entries/${entry}.tsx` ``, not look up `entry` directly.

## Chunk object key set

For this entry, the chunk object has exactly these keys:

```
file, name, src, isEntry
```

## Does a css array appear for an entry that imports no stylesheet?

No. `frontend/src/entries/runs.tsx` (the Task 2 placeholder) imports no CSS, and the resulting
chunk object has **no `css` key at all** — not an empty array, the key is absent entirely. A
loader must treat a missing `css` key the same as an empty list, not assume the key is always
present.

## Verbatim manifest JSON from the real build

```json
{
  "src/entries/runs.tsx": {
    "file": "assets/runs-BvRk9kiK.js",
    "name": "runs",
    "src": "src/entries/runs.tsx",
    "isEntry": true
  }
}
```

## Build command and output used to produce this

```
$ cd frontend && npm run build

> frontend@0.0.0 build
> vite build

vite v8.2.1 building client environment for production...
transforming...
✓ 2 modules transformed.
rendering chunks...
computing gzip size...
../app/static/dist/.vite/manifest.json      0.14 kB │ gzip: 0.12 kB
../app/static/dist/assets/runs-BvRk9kiK.js  0.00 kB │ gzip: 0.02 kB

✓ built in 14ms
```

Output tree produced:

```
app/static/dist/.vite/manifest.json
app/static/dist/assets/runs-BvRk9kiK.js
```

The hashed filename (`runs-BvRk9kiK.js`) will differ on every real build once
`frontend/src/entries/runs.tsx` is replaced with the real mounting entry (plan 22-04) — only
the manifest's **path**, **key shape**, and **chunk key set** documented above are the stable
contract a loader may depend on.
