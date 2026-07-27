import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "happy-dom",
    globals: false,
    coverage: {
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["**/*.test.{ts,tsx}", "**/*.d.ts"],
      reporter: ["text-summary", "json-summary"],
      // RE-BASELINED for vitest 4, and the old numbers here were not a floor -
      // they were decorative. vitest 4's v8 provider remaps coverage through the
      // AST to SOURCE constructs; vitest 3 counted what the raw v8 ranges happened
      // to attribute. On an unchanged tree and an unchanged suite:
      //
      //   metric      vitest 3            vitest 4
      //   statements   5.82% ( 274/4702)   1.95% (  34/1742)
      //   branches    77.77% (  91/ 117)   2.72% (  21/ 770)
      //   functions   77.35% (  82/ 106)   2.72% (  13/ 477)
      //   lines        5.82% ( 274/4702)   1.99% (  31/1551)
      //
      // The `functions: 70` gate was being met against a denominator that saw 106
      // of the site's 477 functions, and `branches: 70` against 117 of 770. A
      // threshold measured over a sixth of its subject cannot fail, which is the
      // one thing a threshold exists to be able to do.
      //
      // So these are the TRUE figures, and they say plainly what is true: this
      // site has four test files and almost no coverage. That is a real gap, not
      // one to paper over with a number picked to pass. Ratchet upward as the
      // interaction suite grows; never lower these to fit a change.
      thresholds: {
        lines: 1,
        statements: 1,
        functions: 2,
        branches: 2,
      },
    },
  },
  esbuild: {
    jsx: "automatic",
  },
});
