import { spawn } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const launcher = fileURLToPath(new URL("./dev_desktop.mjs", import.meta.url));
const port = 1421;
const baseUrl = `http://127.0.0.1:${port}`;
let output = "";
let exited = false;

const server = spawn(process.execPath, [launcher], {
  cwd: repoRoot,
  env: { ...process.env, BRIDGE_DESKTOP_DEV_PORT: String(port) },
  stdio: ["ignore", "pipe", "pipe"],
  windowsHide: true,
});
server.once("exit", () => { exited = true; });
for (const stream of [server.stdout, server.stderr]) {
  stream.on("data", (chunk) => {
    output = `${output}${String(chunk)}`.slice(-12_000);
  });
}

async function waitForServer() {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (exited) throw new Error(`Desktop preview exited before becoming ready.\n${output}`);
    try {
      const response = await fetch(baseUrl, { signal: AbortSignal.timeout(1_000) });
      if (response.ok) return response.text();
    } catch {
      // The production compile or preview server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Desktop preview did not become ready within 30 seconds.\n${output}`);
}

try {
  const html = await waitForServer();
  const scriptPath = html.match(/<script[^>]+src="([^"]+)"/)?.[1];
  if (!html.includes('id="app"') || !scriptPath) {
    throw new Error(`Desktop preview returned an unusable index.\n${output}`);
  }
  const scriptResponse = await fetch(`${baseUrl}${scriptPath}`, {
    signal: AbortSignal.timeout(10_000),
  });
  const script = await scriptResponse.text();
  if (!scriptResponse.ok || script.length < 100_000) {
    throw new Error(`Desktop bundle was not usable (${scriptResponse.status}, ${script.length} bytes).\n${output}`);
  }
  console.log(`Desktop dev smoke passed: index and ${script.length}-byte application bundle are ready.`);
} finally {
  if (!exited) {
    server.kill();
    await Promise.race([
      once(server, "exit"),
      new Promise((resolve) => setTimeout(resolve, 3_000)),
    ]);
  }
}
