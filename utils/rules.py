from nonebot.adapters.onebot.v11 import Bot, Event, GroupMessageEvent
from nonebot.typing import T_State


async def ensure_group(bot: Bot, event: Event, state: T_State) -> bool:
    """确保消息来自群聊"""
    return isinstance(event, GroupMessageEvent)
