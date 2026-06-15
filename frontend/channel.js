import { INPUT, OUTPUT, EXIT, RESIZE, LIFECYCLE, LIFECYCLE_OPEN, LIFECYCLE_CLOSE } from "./protocol.js";

export class TerminalChannel {
  constructor() {
    this._realtime = window.webxdc.joinRealtimeChannel();
    this._realtime.setListener((msg) => this._receiveUpdate(msg));
    this._hbTimer = null;
    this._onUpdate = null;
  }

  set onUpdate(handler) {
    this._onUpdate = handler;
  }

  sendInput(data) {
    const encoded = new TextEncoder().encode(data);
    const buf = new Uint8Array(1 + encoded.length);
    buf[0] = INPUT;
    buf.set(encoded, 1);
    this._realtime.send(buf);
  }

  sendResize(cols, rows) {
    const buf = new Uint8Array(5);
    buf[0] = RESIZE;
    buf[1] = (cols >> 8) & 0xff;
    buf[2] = cols & 0xff;
    buf[3] = (rows >> 8) & 0xff;
    buf[4] = rows & 0xff;
    this._realtime.send(buf);
  }

  sendLifecycle(state) {
    this._realtime.send(new Uint8Array([LIFECYCLE, state]));
  }

  startHeartbeat() {
    if (this._hbTimer) return;
    this.sendLifecycle(LIFECYCLE_OPEN);
    this._hbTimer = setInterval(() => this.sendLifecycle(LIFECYCLE_OPEN), 1000);
  }

  stopHeartbeat() {
    clearInterval(this._hbTimer);
    this._hbTimer = null;
    try { this.sendLifecycle(LIFECYCLE_CLOSE); } catch (_) {}
  }

  _receiveUpdate(msg) {
    if (msg[0] === OUTPUT) {
      this._onUpdate?.(msg.slice(1));
    } else if (msg[0] === EXIT) {
      this._onUpdate?.(null);
    }
  }
}
