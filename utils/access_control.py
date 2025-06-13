from collections.abc import Callable
from functools import wraps
from typing import Any

from nonebot.adapters.onebot.v11 import Bot, Event, GroupMessageEvent
from nonebot.typing import T_State
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage

from zhenxun.models.ban_console import BanConsole
from zhenxun.models.bot_console import BotConsole
from zhenxun.models.group_console import GroupConsole
from zhenxun.services.log import logger


def require_plugin_enabled(plugin_name: str = "summary_group"):
    """权限检查装饰器，检查Bot状态、插件是否被禁用、用户是否被封禁等"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(bot: Bot, event: Event, *args, **kwargs) -> Any:
            bot_id = bot.self_id
            user_id_str = event.get_user_id()
            group_id = getattr(event, "group_id", None) if isinstance(event, GroupMessageEvent) else None

            try:
                if not await BotConsole.get_bot_status(bot_id):
                    logger.info(
                        f"Bot {bot_id} is inactive, skipping command.",
                        command=plugin_name,
                        session=user_id_str,
                        group_id=group_id,
                    )
                    return

                if await BotConsole.is_block_plugin(bot_id, plugin_name):
                    logger.info(
                        f"Plugin '{plugin_name}' is blocked for Bot {bot_id}.",
                        command=plugin_name,
                        session=user_id_str,
                    )
                    return

                if group_id:
                    if await GroupConsole.is_block_plugin(group_id, plugin_name):
                        logger.info(
                            f"Plugin '{plugin_name}' is blocked for Group {group_id}.",
                            command=plugin_name,
                            session=user_id_str,
                            group_id=group_id,
                        )
                        for arg in args:
                            if isinstance(arg, MsgTarget):
                                await UniMessage.text("群聊总结功能在本群已被禁用。").send(arg)
                                break
                        return

                    if await BanConsole.is_ban(None, group_id):
                        logger.info(
                            f"Group {group_id} is banned.",
                            command=plugin_name,
                            group_id=group_id,
                        )
                        return

                if await BanConsole.is_ban(user_id_str, group_id):
                    logger.info(
                        f"User {user_id_str} is banned in Group {group_id or 'global'}.",
                        command=plugin_name,
                        session=user_id_str,
                        group_id=group_id,
                    )
                    return

                return await func(bot, event, *args, **kwargs)

            except Exception as e:
                logger.error(
                    f"权限检查时出错: {e}",
                    command=plugin_name,
                    session=user_id_str,
                    group_id=group_id,
                    e=e,
                )
                return

        return wrapper

    return decorator


async def check_command_preconditions(
    bot: Bot, event: Event, plugin_name: str = "summary_group", target: MsgTarget | None = None
) -> bool:
    """通用的命令前置条件检查函数"""
    bot_id = bot.self_id
    user_id_str = event.get_user_id()
    group_id = getattr(event, "group_id", None) if isinstance(event, GroupMessageEvent) else None

    try:
        if not await BotConsole.get_bot_status(bot_id):
            logger.info(
                f"Bot {bot_id} is inactive, skipping command.",
                command=plugin_name,
                session=user_id_str,
                group_id=group_id,
            )
            return False

        if await BotConsole.is_block_plugin(bot_id, plugin_name):
            logger.info(
                f"Plugin '{plugin_name}' is blocked for Bot {bot_id}.",
                command=plugin_name,
                session=user_id_str,
            )
            return False

        if group_id:
            if await GroupConsole.is_block_plugin(group_id, plugin_name):
                logger.info(
                    f"Plugin '{plugin_name}' is blocked for Group {group_id}.",
                    command=plugin_name,
                    session=user_id_str,
                    group_id=group_id,
                )
                if target:
                    await UniMessage.text("群聊总结功能在本群已被禁用。").send(target)
                return False

            if await BanConsole.is_ban(None, group_id):
                logger.info(
                    f"Group {group_id} is banned.",
                    command=plugin_name,
                    group_id=group_id,
                )
                return False

        if await BanConsole.is_ban(user_id_str, group_id):
            logger.info(
                f"User {user_id_str} is banned in Group {group_id or 'global'}.",
                command=plugin_name,
                session=user_id_str,
                group_id=group_id,
            )
            return False

        return True

    except Exception as e:
        logger.error(
            f"权限检查时出错: {e}",
            command=plugin_name,
            session=user_id_str,
            group_id=group_id,
            e=e,
        )
        return False


async def check_scheduler_preconditions(
    bot: Bot,
    event: Event,
    plugin_name: str = "summary_group",
    is_superuser: bool = False,
    group_id: int | None = None,
) -> bool:
    """定时任务专用的权限检查函数，返回是否可以继续执行"""
    bot_id = bot.self_id
    user_id_str = event.get_user_id()

    try:
        if not await BotConsole.get_bot_status(bot_id):
            logger.info(
                f"Bot {bot_id} is inactive, skipping.",
                command=plugin_name,
                session=user_id_str,
                group_id=group_id,
            )
            return False

        if await BotConsole.is_block_plugin(bot_id, plugin_name):
            logger.info(
                f"Plugin '{plugin_name}' is blocked for Bot {bot_id}.",
                command=plugin_name,
                session=user_id_str,
            )
            return False

        if await BanConsole.is_ban(user_id_str, None):
            logger.info(
                f"User {user_id_str} is globally banned.",
                command=plugin_name,
                session=user_id_str,
            )
            return False

        if group_id and not is_superuser:
            if await BanConsole.is_ban(user_id_str, str(group_id)):
                logger.info(
                    f"User {user_id_str} is banned in group {group_id}.",
                    command=plugin_name,
                    session=user_id_str,
                    group_id=group_id,
                )
                return False

            if not await GroupConsole.get_group_status(str(group_id)):
                logger.info(
                    f"Group {group_id} is inactive.",
                    command=plugin_name,
                    group_id=group_id,
                )
                return False

            if await GroupConsole.is_block_plugin(str(group_id), plugin_name):
                logger.info(
                    f"Plugin '{plugin_name}' is blocked in group {group_id}.",
                    command=plugin_name,
                    group_id=group_id,
                )
                return False

        return True

    except Exception as e:
        logger.error(
            f"权限检查时出错: {e}",
            command=plugin_name,
            session=user_id_str,
            group_id=group_id,
            e=e,
        )
        return False


async def ensure_group(bot: Bot, event: Event, state: T_State) -> bool:
    """确保消息来自群聊"""
    return isinstance(event, GroupMessageEvent)
