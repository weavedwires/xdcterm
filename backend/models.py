from dataclasses import dataclass


@dataclass
class User:
    user_id: int
    display_name: str
    addr: str
    created_at: str | None = None
    updated_at: str | None = None


class AccountContext:
    def __init__(self, bot, accid):
        self.bot = bot
        self.accid = accid

    def get_contact(self, contact_id):
        return self.bot.rpc.get_contact(self.accid, contact_id)

    def send_msg(self, chat_id, msg_data):
        return self.bot.rpc.send_msg(self.accid, chat_id, msg_data)

    def send_realtime(self, msg_id, data):
        self.bot.rpc.send_webxdc_realtime_data(self.accid, msg_id, data)

    def send_advertisement(self, msg_id):
        self.bot.rpc.send_webxdc_realtime_advertisement(self.accid, msg_id)

    def get_message(self, msg_id):
        return self.bot.rpc.get_message(self.accid, msg_id)

    def log(self, fmt, *args):
        self.bot.logger.info(fmt, *args)
