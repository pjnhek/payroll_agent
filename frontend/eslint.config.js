import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";

// One command (npm run check) both typechecks and lints; this file is the lint half.
// typescript-eslint's type-checked recommended set is the base, composed with the React
// Hooks plugin's recommended rules. exhaustive-deps is bumped from its default "warn" to
// "error" -- it is the entire reason this project chose ESLint over Biome (usePoller's
// effect dependency array is the one place a stale closure would silently poll a wrong URL
// or never stop polling), so it must block a merge, not just print a warning.
export default tseslint.config(
  {
    ignores: ["dist/**", "node_modules/**"],
  },
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        // The Vite/Vitest config files aren't listed in tsconfig.json (src only) and
        // projectService only auto-discovers files named exactly tsconfig.json -- it does
        // not walk tsconfig.node.json's own include list. allowDefaultProject gives those
        // two config files an inferred single-file project instead of a parse error.
        projectService: {
          allowDefaultProject: ["vite.config.ts", "vitest.config.ts"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  reactHooks.configs.flat.recommended,
  {
    rules: {
      "react-hooks/exhaustive-deps": "error",
    },
  },

  // This file itself is plain JS, outside both tsconfig.json ("src" only) and
  // tsconfig.node.json (the *.config.ts files) -- type-aware parsing has no project to
  // attach it to, so it must opt out of the type-checked rule set rather than error.
  {
    files: ["eslint.config.js"],
    ...tseslint.configs.disableTypeChecked,
  },

  // Project-specific safety rules, scoped to application source. Each rule bans a
  // construct that would otherwise let a component bypass a safety property this project
  // depends on -- network calls happening outside the one reviewed poller path, mutation
  // submissions bypassing the confirm()/preventDefault() wrapper, and raw HTML injection
  // reopening an XSS surface React's default text-node escaping already closes.
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-globals": [
        "error",
        {
          name: "fetch",
          message:
            "fetch is banned outside src/hooks/usePoller.ts, the one reviewed network call site. See eslint.config.js for the sanctioned override.",
        },
        {
          name: "XMLHttpRequest",
          message:
            "XMLHttpRequest is banned outside src/hooks/usePoller.ts, the one reviewed network call site. See eslint.config.js for the sanctioned override.",
        },
      ],
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "axios",
              message:
                "axios is banned everywhere in this project -- mutations are native <form method=\"post\"> submissions and the one legitimate read is a plain fetch() inside src/hooks/usePoller.ts.",
            },
          ],
        },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXOpeningElement[name.name='form']",
          message:
            "Raw <form> elements are banned outside MutationForm and ConfirmForm. Every mutation submission must go through one of those two shared wrapper components so the confirm() dialog and preventDefault() safety guard are never silently bypassed by a hand-written form.",
        },
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message:
            "dangerouslySetInnerHTML is banned everywhere in this project. React's default text-node escaping is sufficient and safe by default; this rule is a standing rule ahead of the conversation-thread surface that will render client-supplied text.",
        },
      ],
    },
  },

  // The poller hook is the one reviewed, sanctioned call site for a real network request
  // (a plain GET to refresh in-place badge state). The project-wide ban above exists
  // specifically so this is the only file where a network global is legal.
  {
    files: ["src/hooks/usePoller.ts"],
    rules: {
      "no-restricted-globals": "off",
    },
  },

  // MutationForm and ConfirmForm are the only two components allowed to emit a raw <form>
  // element; every other component composes one of these two instead.
  {
    files: ["src/components/MutationForm.tsx", "src/components/ConfirmForm.tsx"],
    rules: {
      "no-restricted-syntax": "off",
    },
  },
);
