import fcntl
import os
import socket
import pty
import struct
import termios
import threading
from pathlib import Path

from deltachat2 import EventType, MsgData, events
from deltabot_cli import BotCli

from db import db
from models import AccountContext, User

INPUT = 0x49
OUTPUT = 0x4f
EXIT = 0x45
RESIZE = 0x52
LIFECYCLE = 0x43
LIFECYCLE_OPEN = 0x01
LIFECYCLE_CLOSE = 0x00
WEBXDC_FILE = str(Path(__file__).resolve().parents[1] / "frontend/dist-release/xdcterm.xdc")

cli = BotCli("xdcterm")

db.init()

_HELP_TEXT = """\
XDCterm — удалённый терминал в Delta Chat

Команды:
/newterm — создать новую сессию терминала
/list — список активных сессий
/help — эта справка
"""


class PTYProcess:
    def __init__(self, ctx: AccountContext, msg_id: int) -> None:
        self.ctx = ctx
        self.msg_id = msg_id
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
                self.ctx.send_realtime(self.msg_id, [OUTPUT] + list(data))
        except OSError:
            pass
        finally:
            self.ctx.send_realtime(self.msg_id, [EXIT])

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


class PTYManager:
    def __init__(self):
        self._ptys: dict[int, PTYProcess] = {}
        self._timers: dict[int, threading.Timer] = {}

    def spawn(self, ctx: AccountContext, msg_id: int) -> None:
        ctx.log("Spawning PTY for msg %d", msg_id)
        self._ptys[msg_id] = PTYProcess(ctx, msg_id)

    def get(self, msg_id: int) -> PTYProcess | None:
        return self._ptys.get(msg_id)

    def handle_open(self, ctx: AccountContext, msg_id: int) -> None:
        if msg_id in self._ptys:
            self._reset_timer(ctx, msg_id)
            return
        user = db.get_user_by_msg(msg_id)
        if not user:
            try:
                msg = ctx.get_message(msg_id)
                c = ctx.get_contact(msg.from_id)
                user = User(c.id, c.display_name, c.address)
                db.upsert_user(user.user_id, user.display_name, user.addr)
                db.add_message(msg_id, user.user_id)
            except Exception:
                user = User(0, "?", "?")
        self.spawn(ctx, msg_id)
        db.open_session(msg_id, user.user_id)
        ctx.log("PTY %d opened by %s with %s", msg_id, user.display_name, user.addr)
        _notify_group(ctx, f"PTY {msg_id} opened by {user.display_name} with {user.addr}")
        self._reset_timer(ctx, msg_id)

    def kill(self, ctx: AccountContext, msg_id: int, reason: str = "exited") -> None:
        self._cancel_timer(msg_id)
        pty = self._ptys.pop(msg_id, None)
        if not pty:
            return
        pty.close()
        db.close_session(msg_id)
        user = db.get_user_by_msg(msg_id)
        if user:
            text = f"PTY {msg_id} closed by {user.display_name} with {user.addr} because {reason}"
        else:
            text = f"PTY {msg_id} closed because {reason}"
        ctx.log(text)
        _notify_group(ctx, text)

    def _reset_timer(self, ctx: AccountContext, msg_id: int) -> None:
        self._cancel_timer(msg_id)
        t = threading.Timer(60.0, self.kill, args=[ctx, msg_id, "timeout"])
        t.daemon = True
        t.start()
        self._timers[msg_id] = t

    def _cancel_timer(self, msg_id: int) -> None:
        t = self._timers.pop(msg_id, None)
        if t:
            t.cancel()


ptys = PTYManager()


def _send_webxdc(ctx: AccountContext, chatid: int, contact_id: int) -> int:
    c = ctx.get_contact(contact_id)
    user = User(c.id, c.display_name, c.address)
    db.upsert_user(user.user_id, user.display_name, user.addr)
    msgid = ctx.send_msg(chatid, MsgData(file=WEBXDC_FILE))
    ctx.send_advertisement(msgid)
    db.add_message(msgid, user.user_id)
    return msgid


def _notify_group(ctx: AccountContext, text: str) -> None:
    group_id = db.get_config("notify_group_id")
    if not group_id:
        return
    try:
        ctx.send_msg(int(group_id), MsgData(text=text))
    except Exception:
        pass


def _send_help(bot, accid, chatid) -> None:
    bot.rpc.send_msg(accid, chatid, MsgData(text=_HELP_TEXT))


@cli.on(events.RawEvent(types=[EventType.SECUREJOIN_INVITER_PROGRESS]))
def on_securejoin(bot, accid, event) -> None:
    if event.progress != 1000:
        return
    if bot.rpc.get_contact(accid, event.contact_id).is_bot:
        return
    chatid = bot.rpc.create_chat_by_contact_id(accid, event.contact_id)
    _send_help(bot, accid, chatid)


@cli.on(events.NewMessage(command="/start"))
def on_start(bot, accid, event) -> None:
    _send_help(bot, accid, event.msg.chat_id)


@cli.on(events.NewMessage(command="/newterm"))
def on_newterm(bot, accid, event) -> None:
    ctx = AccountContext(bot, accid)
    _send_webxdc(ctx, event.msg.chat_id, event.msg.from_id)


@cli.on(events.NewMessage(command="/help"))
def on_help(bot, accid, event) -> None:
    _send_help(bot, accid, event.msg.chat_id)


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


def _handle_input(ctx: AccountContext, msg_id: int, raw: bytes) -> None:
    p = ptys.get(msg_id)
    if p:
        p.write(raw[1:])


def _handle_resize(ctx: AccountContext, msg_id: int, raw: bytes) -> None:
    if len(raw) < 5:
        return
    p = ptys.get(msg_id)
    if p:
        cols = (raw[1] << 8) | raw[2]
        rows = (raw[3] << 8) | raw[4]
        p.resize(cols, rows)


def _handle_lifecycle(ctx: AccountContext, msg_id: int, raw: bytes) -> None:
    if len(raw) < 2:
        return
    state = raw[1]
    if state == LIFECYCLE_CLOSE:
        ptys.kill(ctx, msg_id, "exited")
    elif state == LIFECYCLE_OPEN:
        ptys.handle_open(ctx, msg_id)


CMD_HANDLERS = {
    INPUT: _handle_input,
    RESIZE: _handle_resize,
    LIFECYCLE: _handle_lifecycle,
}


@cli.on(events.RawEvent(func=lambda e: e.kind == "WebxdcRealtimeData"))
def on_webxdc_data(bot, accid, event) -> None:
    raw = bytes(event.data)
    if not raw:
        return
    ctx = AccountContext(bot, accid)
    handler = CMD_HANDLERS.get(raw[0])
    if handler:
        handler(ctx, event.msg_id, raw)


@cli.on(events.RawEvent(func=lambda e: e.kind == "WebxdcRealtimeAdvertisementReceived"))
def on_ad_received(bot, accid, event) -> None:
    ctx = AccountContext(bot, accid)
    ctx.send_advertisement(event.msg_id)


@cli.on(events.RawEvent(func=lambda e: e.kind == "WebxdcInstanceDeleted"))
def on_instance_deleted(bot, accid, event) -> None:
    ctx = AccountContext(bot, accid)
    ptys.kill(ctx, event.msg_id, "exited")


@cli.on_start
def on_start(bot, args) -> None:
    hostname = os.environ.get("HOSTNAME") or socket.gethostname()
    display_name = f"{hostname} terminal"
    for accid in bot.rpc.get_all_account_ids():
        current = bot.rpc.get_config(accid, "displayname")
        if not current:
            bot.rpc.set_config(accid, "displayname", display_name)

    group_id = db.get_config("notify_group_id")
    if not group_id:
        accids = bot.rpc.get_all_account_ids()
        if accids:
            try:
                group_name = f"{hostname} terminal logs"
                chat_id = bot.rpc.create_group_chat(accids[0], group_name, False)
                db.set_config("notify_group_id", str(chat_id))
                group_id = str(chat_id)
                bot.logger.info("Notification group created: id=%d name=%s", chat_id, group_name)
            except Exception as e:
                bot.logger.warning("Failed to create notification group: %s", e)

    if group_id:
        accids = bot.rpc.get_all_account_ids()
        if accids:
            try:
                qr_link = bot.rpc.get_chat_securejoin_qr_code(accids[0], int(group_id))
                bot.logger.info("Notification group invite: %s", qr_link)
            except Exception as e:
                bot.logger.warning("Failed to get group invite: %s", e)


if __name__ == "__main__":
    cli.start()
