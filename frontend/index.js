import "@xterm/xterm/css/xterm.css";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { ImageAddon } from "@xterm/addon-image";
import { TerminalChannel } from "./channel.js";

document.body.style.cssText =
  "margin:0;padding:0;background:#000;height:100vh;overflow:hidden";
document.getElementById("terminal").style.cssText = "height:100vh";

const term = new Terminal({ cursorBlink: true, fontSize: 12, fontFamily: '"JB", monospace' });
const fitAddon = new FitAddon();
term.loadAddon(fitAddon);
term.loadAddon(new ImageAddon({ sixelSupport: true }));

term.open(document.getElementById("terminal"));
fitAddon.fit();

const channel = new TerminalChannel();
channel.onUpdate = (data) => {
  if (data === null) {
    term.dispose();
  } else {
    term.write(data);
  }
};

channel.startHeartbeat();
channel.sendResize(term.cols, term.rows);

window.addEventListener("resize", () => fitAddon.fit());
term.onResize(() => channel.sendResize(term.cols, term.rows));
term.onData((data) => channel.sendInput(data));

document.addEventListener("visibilitychange", () => {
  if (document.hidden) channel.stopHeartbeat(); else channel.startHeartbeat();
});

window.addEventListener("pagehide", () => channel.stopHeartbeat());
window.addEventListener("pageshow", () => channel.startHeartbeat());
