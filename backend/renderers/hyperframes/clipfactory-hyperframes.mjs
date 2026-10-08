// Trusted launcher: only local check/render commands, no npx or package downloads.
import {spawn} from "node:child_process";
import {fileURLToPath} from "node:url";
const [command, ...args] = process.argv.slice(2);
if (!["check", "render", "lint", "catalog"].includes(command)) {
  console.error("Unsupported local graphics command");
  process.exit(2);
}
const cli = fileURLToPath(new URL("./node_modules/hyperframes/bin/hyperframes.mjs", import.meta.url));
const offline = fileURLToPath(new URL("./offline.cjs", import.meta.url));
const child = spawn(process.execPath, ["--require", offline, cli, command, ...args], {
  stdio: "inherit",
  env: {...process.env, HYPERFRAMES_NO_TELEMETRY: "1", DO_NOT_TRACK: "1",
    NODE_OPTIONS: `--require=${offline}`},
});
child.on("error", () => process.exit(2));
child.on("exit", code => process.exit(code ?? 2));
