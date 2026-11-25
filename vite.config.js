import { defineConfig } from "vite";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const grabScript = path.join(root, "scripts", "grab-native.py");
const shapeScript = path.join(root, "scripts", "grab-shape.py");

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function runPython(script, args = [], timeoutMs = 120_000) {
  return new Promise((resolve) => {
    const child = spawn("python3", [script, ...args], {
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      resolve({ status: 504, body: { error: `Grab timed out (${timeoutMs / 1000}s)` } });
    }, timeoutMs);

    child.stdout.on("data", (d) => {
      stdout += d.toString();
    });
    child.stderr.on("data", (d) => {
      stderr += d.toString();
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      let parsed;
      try {
        parsed = JSON.parse(stdout.trim() || "{}");
      } catch {
        resolve({
          status: 500,
          body: { error: "Invalid grabber output", detail: stdout || stderr },
        });
        return;
      }

      if (code !== 0 || parsed.error) {
        resolve({
          status: 500,
          body: { error: parsed.error || stderr || "Grab failed" },
        });
        return;
      }

      resolve({ status: 200, body: parsed });
    });
  });
}

function colorGrabApi() {
  return {
    name: "colorgrab-api",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url || "/", "http://127.0.0.1");
        if (!url.pathname.startsWith("/api/grab")) {
          next();
          return;
        }

        if (req.method === "OPTIONS") {
          res.statusCode = 204;
          res.setHeader("Allow", "POST, OPTIONS");
          res.end();
          return;
        }

        if (req.method === "POST") {
          await readBody(req);
        } else {
          res.statusCode = 405;
          res.setHeader("Content-Type", "application/json");
          res.setHeader("Allow", "POST, OPTIONS");
          res.end(JSON.stringify({ error: "Use POST to start a grab" }));
          return;
        }

        let result;
        if (url.pathname === "/api/grab/rect") {
          result = await runPython(shapeScript, ["--mode", "rect"]);
        } else if (url.pathname === "/api/grab/circle") {
          result = await runPython(shapeScript, ["--mode", "circle"]);
        } else if (url.pathname === "/api/grab") {
          result = await runPython(grabScript);
        } else {
          res.statusCode = 404;
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify({ error: "Unknown grab endpoint" }));
          return;
        }

        res.statusCode = result.status;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result.body));
      });
    },
  };
}

export default defineConfig({
  plugins: [colorGrabApi()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    open: false,
    strictPort: true,
  },
});
