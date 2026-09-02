import { defineConfig } from "vitest/config";
import { svelte } from "@sveltejs/vite-plugin-svelte";

/**
 * Component tests run against the browser-condition build of Svelte so that
 * lifecycle and transitions behave as they do in the app, and against jsdom
 * rather than a real browser: Bridge ships offline and the desktop shell is
 * the only real runtime, so a headless-browser dependency would buy little
 * over asserting on the DOM these components actually produce.
 */
export default defineConfig({
  plugins: [svelte({ hot: false })],
  resolve: { conditions: ["browser"] },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/lib/components/__tests__/setup.ts"],
    include: ["src/**/*.test.ts"],
    restoreMocks: true,
  },
});
