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
            os.execvp("bash", ["bash"])
        else:
            size = struct.pack("HHHH", 30, 80, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, size)
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


def setup_xdcterm_chat(bot, accid: int) -> int:
    chatid = bot.rpc.get_config(accid, "ui.xdcterm_chat_id")
    if chatid is None:
        chatid = bot.rpc.create_group_chat(accid, "XDCTerm", True)
        bot.rpc.set_config(accid, "ui.xdcterm_chat_id", str(chatid))
    chatid = int(chatid)

    info = bot.rpc.get_basic_chat_info(accid, chatid)
    if info.is_unpromoted:
        bot.rpc.misc_send_text_message(accid, chatid, "Hello")

    return chatid


@cli.on_start
def on_start(bot, args) -> None:
    for accid in bot.rpc.get_all_account_ids():
        if not bot.rpc.is_configured(accid):
            continue
        chatid = setup_xdcterm_chat(bot, accid)
        qr = bot.rpc.get_chat_securejoin_qr_code_svg(accid, chatid)[0]
        bot.logger.info("Chat invitation for account %d:\n%s", accid, qr)


@cli.on(events.RawEvent(types=[EventType.INCOMING_MSG]))
def on_incoming_msg(bot, accid, event) -> None:
    chatid = bot.rpc.get_config(accid, "ui.xdcterm_chat_id")
    if chatid is None or event.chat_id != int(chatid):
        return
    send_webxdc(bot, accid, int(chatid))


@cli.on(events.RawEvent(func=lambda e: e.kind == "WebxdcRealtimeData"))
def on_webxdc_data(bot, accid, event) -> None:
    data = bytes(event.data)
    if data[0] != INPUT:
        return
    p = ptys.get(event.msg_id)
    if p:
        p.write(data[1:])


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
