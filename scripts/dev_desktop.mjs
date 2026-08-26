import { build, preview } from "vite";

const port = Number.parseInt(process.env.BRIDGE_DESKTOP_DEV_PORT ?? "1420", 10);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error(`Invalid BRIDGE_DESKTOP_DEV_PORT: ${process.env.BRIDGE_DESKTOP_DEV_PORT}`);
}

console.log("Building the desktop frontend before local launch...");
await build();

const server = await preview({
  preview: {
    host: "127.0.0.1",
    port,
    strictPort: true,
  },
});

server.printUrls();
console.log("Desktop preview is ready. Restart this command after changing Svelte/TypeScript files.");
