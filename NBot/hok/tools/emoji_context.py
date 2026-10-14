"""Emoji-only context/cache facade; archived messages stay in PostgreSQL."""


class EmojiContext:
    def __init__(self, user_id, group_id=None):
        self.user_id, self.group_id = str(user_id), group_id

    def recent(self):
        from ..zfunc import recent_emoji_messages
        return recent_emoji_messages(self.user_id, self.group_id)

    def get_action(self, message_hash):
        return self._state("get", message_hash)

    def set_action(self, message_hash, **value):
        return self._state("set", message_hash, value)

    def used(self, message_hash):
        return self._state("used", message_hash)

    def mark_used(self, message_hash):
        return self._state("mark", message_hash)

    def _state(self, action, message_hash, value=None):
        from ..zfunc import emoji_message_state
        return emoji_message_state(self.user_id, self.group_id, action, message_hash, value)
