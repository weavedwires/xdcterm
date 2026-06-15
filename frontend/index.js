import "@xterm/xterm/css/xterm.css";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { ImageAddon } from "@xterm/addon-image";

const INPUT = 0x49;
const OUTPUT = 0x4f;
const EXIT = 0x45;
const RESIZE = 0x52;

document.body.style.cssText =
  "margin:0;padding:0;background:#000;height:100vh;overflow:hidden";
document.getElementById("terminal").style.cssText = "height:100vh";

const term = new Terminal({ cursorBlink: true, fontSize: 14, fontFamily: '"JB", monospace' });
const fitAddon = new FitAddon();
term.loadAddon(fitAddon);
term.loadAddon(new ImageAddon({ sixelSupport: true }));

term.open(document.getElementById("terminal"));
fitAddon.fit();
term.write("");

function sendResize() {
  const { cols, rows } = term;
  const buf = new Uint8Array(5);
  buf[0] = RESIZE;
  buf[1] = (cols >> 8) & 0xff;
  buf[2] = cols & 0xff;
  buf[3] = (rows >> 8) & 0xff;
  buf[4] = rows & 0xff;
  realtime.send(buf);
}

window.addEventListener("resize", () => {
  fitAddon.fit();
  sendResize();
});

term.onResize(sendResize);

term.onData((data) => {
  const encoded = new TextEncoder().encode(data);
  const buf = new Uint8Array(1 + encoded.length);
  buf[0] = INPUT;
  buf.set(encoded, 1);
  realtime.send(buf);
});

function receiveUpdate(msg) {
  if (msg[0] === OUTPUT) {
    term.write(msg.slice(1));
  } else if (msg[0] === EXIT) {
    term.dispose();
  }
}

const realtime = window.webxdc.joinRealtimeChannel();
realtime.setListener(receiveUpdate);
sendResize();
