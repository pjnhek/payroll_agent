/// <reference types="vite/client" />

// Vite's own client.d.ts declares module types for common asset extensions but not the
// generic `?raw` query suffix -- this project's own addition, needed by
// MutationForm.test.tsx to read a sibling source file's text as a plain string without
// importing Node's `fs` (which tsconfig.json deliberately omits `"types": ["node"]` for,
// since everything under src/ ships into the browser bundle).
declare module "*?raw" {
  const content: string;
  export default content;
}
