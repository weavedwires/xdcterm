import fcntl
import os
import pty
import struct
import termios
import threading
from pathlib import Path

from deltachat2 import EventType, MsgData, events
from deltabot_cli import BotCli

import db

INPUT = 0x49
OUTPUT = 0x4f
EXIT = 0x45
RESIZE = 0x52
LIFECYCLE = 0x43
LIFECYCLE_OPEN = 0x01
LIFECYCLE_CLOSE = 0x00
WEBXDC_FILE = str(Path(__file__).resolve().parents[1] / "frontend/dist-release/xdcterm.xdc")

db.init()

cli = BotCli("xdcterm")
ptys: dict[int, "PTYProcess"] = {}
_timers: dict[int, threading.Timer] = {}


class PTYProcess:
    def __init__(self, bot, accid: int, msgid: int) -> None:
        self.bot = bot
        self.accid = accid
        self.msgid = msgid
        pid, self.fd = pty.fork()
        if pid == 0:
            shell = os.environ.get("SHELL", "bash")
            os.execvp(shell, [shell])
        else:
            threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        try:
            while True:
                data = os.read(self.fd, 4096)
                if not data:
                    break
                self.bot.rpc.send_webxdc_realtime_data(
                    self.accid, self.msgid, [OUTPUT] + list(data)
                )
        except OSError:
            pass
        finally:
            self.bot.rpc.send_webxdc_realtime_data(self.accid, self.msgid, [EXIT])

    def write(self, data: bytes) -> None:
        os.write(self.fd, data)

    def resize(self, cols: int, rows: int) -> None:
        size = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, size)

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass


def spawn_pty(bot, accid: int, msgid: int) -> None:
    bot.logger.info("Spawning PTY for msg %d", msgid)
    ptys[msgid] = PTYProcess(bot, accid, msgid)


def send_webxdc(bot, accid: int, chatid: int, contact_id: int) -> int:
    c = bot.rpc.get_contact(accid, contact_id)
    db.upsert_user(contact_id, c.display_name, c.address)
    msgid = bot.rpc.send_msg(accid, chatid, MsgData(text="hi", file=WEBXDC_FILE))
    bot.rpc.send_webxdc_realtime_advertisement(accid, msgid)
    db.add_message(msgid, contact_id)
    return msgid


def notify_admin(bot, accid, text):
    try:
        msg_id = db.get_admin_message_id()
        if msg_id:
            msg = bot.rpc.get_message(accid, msg_id)
            bot.rpc.send_msg(accid, msg.chat_id, MsgData(text=text))
    except Exception:
        pass


def _kill_pty(msgid, bot, accid, reason="exited"):
    _cancel_timer(msgid)
    p = ptys.pop(msgid, None)
    if p:
        p.close()
        db.close_session(msgid)
        user = db.get_user_by_msg(msgid)
        if user:
            text = f"PTY {msgid} closed by {user['display_name']} with {user['addr']} because {reason}"
            bot.logger.info(text)
            notify_admin(bot, accid, text)
        else:
            text = f"PTY {msgid} closed because {reason}"
            bot.logger.info(text)
            notify_admin(bot, accid, text)


def _cancel_timer(msgid):
    t = _timers.pop(msgid, None)
    if t:
        t.cancel()


def _reset_timer(msgid, bot, accid):
    _cancel_timer(msgid)
    t = threading.Timer(60.0, _kill_pty, args=[msgid, bot, accid, "timeout"])
    t.daemon = True
    t.start()
    _timers[msgid] = t


@cli.on(events.RawEvent(types=[EventType.SECUREJOIN_INVITER_PROGRESS]))
def on_securejoin(bot, accid, event) -> None:
    if event.progress == 1000 and not bot.rpc.get_contact(accid, event.contact_id).is_bot:
        contact_id = event.contact_id
        chatid = bot.rpc.create_chat_by_contact_id(accid, contact_id)
        send_webxdc(bot, accid, chatid, contact_id)


@cli.on(events.NewMessage(command="/start"))
def on_start_cmd(bot, accid, event) -> None:
    send_webxdc(bot, accid, event.msg.chat_id, event.msg.from_id)


@cli.on(events.NewMessage(command="/list"))
def on_list(bot, accid, event) -> None:
    sessions = db.get_active_sessions()
    if not sessions:
        bot.rpc.send_msg(accid, event.msg.chat_id, MsgData(text="No open terminals"))
    else:
        lines = ["Open terminals:"]
        for s in sessions:
            lines.append(f"msg {s['msg_id']} by {s['display_name']} with {s['addr']} since {s['opened_at']}")
        bot.rpc.send_msg(accid, event.msg.chat_id, MsgData(text="\n".join(lines)))


@cli.on(events.RawEvent(func=lambda e: e.kind == "WebxdcRealtimeData"))
def on_webxdc_data(bot, accid, event) -> None:
    data = bytes(event.data)
    if not data:
        return
    msg_id = event.msg_id
    cmd = data[0]
    if cmd == INPUT:
        p = ptys.get(msg_id)
        if p:
            p.write(data[1:])
    elif cmd == RESIZE and len(data) >= 5:
        p = ptys.get(msg_id)
        if p:
            cols = (data[1] << 8) | data[2]
            rows = (data[3] << 8) | data[4]
            p.resize(cols, rows)
    elif cmd == LIFECYCLE and len(data) >= 2:
        state = data[1]
        if state == LIFECYCLE_CLOSE:
            _kill_pty(msg_id, bot, accid, "exited")
        elif state == LIFECYCLE_OPEN:
            if msg_id not in ptys:
                user = db.get_user_by_msg(msg_id)
                if not user:
                    try:
                        msg = bot.rpc.get_message(accid, msg_id)
                        c = bot.rpc.get_contact(accid, msg.from_id)
                        db.upsert_user(c.id, c.display_name, c.address)
                        db.add_message(msg_id, c.id)
                        user = {"user_id": c.id, "display_name": c.display_name, "addr": c.address}
                    except Exception:
                        user = {"user_id": 0, "display_name": "?", "addr": "?"}
                spawn_pty(bot, accid, msg_id)
                db.open_session(msg_id, user["user_id"])
                text = f"PTY {msg_id} opened by {user['display_name']} with {user['addr']}"
                bot.logger.info(text)
                notify_admin(bot, accid, text)
            _reset_timer(msg_id, bot, accid)


@cli.on(events.RawEvent(func=lambda e: e.kind == "WebxdcRealtimeAdvertisementReceived"))
def on_ad_received(bot, accid, event) -> None:
    bot.rpc.send_webxdc_realtime_advertisement(accid, event.msg_id)


@cli.on(events.RawEvent(func=lambda e: e.kind == "WebxdcInstanceDeleted"))
def on_instance_deleted(bot, accid, event) -> None:
    _kill_pty(event.msg_id, bot, accid, "exited")


if __name__ == "__main__":
    cli.start()
