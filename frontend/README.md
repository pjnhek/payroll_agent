# frontend

React + TypeScript + Vite toolchain, built as a set of page islands mounted into the
existing Jinja2 dashboard shell. See `../app/routes/templating.py` for how a built entry is
served, and `vite.config.ts` for the build configuration.

## Dependency override: `openapi-typescript` vs the pinned TypeScript version

`package.json` pins TypeScript to `6.0.3` and carries this `overrides` block:

```json
"overrides": {
  "openapi-typescript": {
    "typescript": "$typescript"
  }
}
```

Without it, `npm install` fails: `openapi-typescript` (every published version, including the
one pinned here) declares a peer dependency of `typescript: ^5.x` only, which does not accept
the pinned `6.0.3`. That peer declaration is stale metadata rather than a real
incompatibility for this project's use — `openapi-typescript` drives the TypeScript compiler's
AST factory and printer APIs to turn an OpenAPI document into `.d.ts` text, and those APIs are
unchanged across this version boundary for the surface it touches.

Before relying on this override, it was verified end to end, not just accepted on the
resolver's say-so: a clean install with the override reported the actually-resolved
TypeScript version as `6.0.3` (not a silent fallback to a `5.x` line), `openapi-typescript` ran
against this project's real generated OpenAPI document (30 paths, 7 component schemas) and
produced real output (over 1,800 lines, all 7 schemas present by name, over 100 typed
members), and that generated output typechecked cleanly under `tsc --noEmit --strict` on
TypeScript `6.0.3` with zero errors.

Do not widen this override to any other package, and do not reach for
`npm install --legacy-peer-deps` if a future package hits the same class of stale-peer
problem — verify the actual generated output typechecks under the pinned TypeScript version
first, the way this one was.
