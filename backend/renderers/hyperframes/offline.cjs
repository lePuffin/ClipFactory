// Render-time offline guard: local HTTP/CDP is allowed, external sockets are not.
const net = require("node:net");
const childProcess = require("node:child_process");
const {syncBuiltinESMExports} = require("node:module");
const local = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);
const originalConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const options = Array.isArray(args[0]) ? args[0][0] : args[0];
  const host = typeof options === "object" ? options.host : typeof args[1] === "string" ? args[1] : "localhost";
  const unixSocket = typeof options === "object" && options.path || typeof options === "string";
  if (!unixSocket && host && !local.has(host)) {
    throw new Error("ClipFactory graphics render is offline; external connection denied");
  }
  return originalConnect.apply(this, args);
};
const originalSpawn = childProcess.spawn;
childProcess.spawn = function (command, args, options) {
  if (/chrom(?:e|ium)/i.test(command)) {
    args = [...(args || []), "--disable-background-networking",
      "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=localhost;127.0.0.1;[::1]"];
  }
  return originalSpawn.call(this, command, args, options);
};
syncBuiltinESMExports();
