import fcntl
import os
import pty
import struct
import termios
import threading
from pathlib import Path

from deltachat2 import EventType, MsgData, events
from deltabot_cli import BotCli

INPUT = 0x49
OUTPUT = 0x4f
EXIT = 0x45
RESIZE = 0x52
WEBXDC_FILE = str(Path(__file__).resolve().parents[1] / "frontend/dist-release/xdcterm.xdc")

cli = BotCli("xdcterm")
ptys: dict[int, "PTYProcess"] = {}


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


def send_webxdc(bot, accid: int, chatid: int) -> int:
    msgid = bot.rpc.send_msg(accid, chatid, MsgData(text="hi", file=WEBXDC_FILE))
    bot.rpc.send_webxdc_realtime_advertisement(accid, msgid)
    spawn_pty(bot, accid, msgid)
    return msgid


@cli.on(events.RawEvent(types=[EventType.SECUREJOIN_INVITER_PROGRESS]))
def on_securejoin(bot, accid, event) -> None:
    if event.progress == 1000 and not bot.rpc.get_contact(accid, event.contact_id).is_bot:
        chatid = bot.rpc.create_chat_by_contact_id(accid, event.contact_id)
        send_webxdc(bot, accid, chatid)


@cli.on(events.NewMessage(command="/start"))
def on_start_cmd(bot, accid, event) -> None:
    send_webxdc(bot, accid, event.msg.chat_id)


@cli.on(events.RawEvent(func=lambda e: e.kind == "WebxdcRealtimeData"))
def on_webxdc_data(bot, accid, event) -> None:
    data = bytes(event.data)
    if not data:
        return
    p = ptys.get(event.msg_id)
    if not p:
        return
    if data[0] == INPUT:
        p.write(data[1:])
    elif data[0] == RESIZE and len(data) >= 5:
        cols = (data[1] << 8) | data[2]
        rows = (data[3] << 8) | data[4]
        p.resize(cols, rows)


@cli.on(events.RawEvent(func=lambda e: e.kind == "WebxdcRealtimeAdvertisementReceived"))
def on_ad_received(bot, accid, event) -> None:
    if event.msg_id in ptys:
        return
    msg = bot.rpc.get_message(accid, event.msg_id)
    if msg.from_id != 1:
        return
    bot.rpc.send_webxdc_realtime_advertisement(accid, event.msg_id)
    spawn_pty(bot, accid, event.msg_id)


@cli.on(events.RawEvent(func=lambda e: e.kind == "WebxdcInstanceDeleted"))
def on_instance_deleted(bot, accid, event) -> None:
    p = ptys.pop(event.msg_id, None)
    if p:
        p.close()


if __name__ == "__main__":
    cli.start()
