import time

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import At, CommandResult, Match, Text
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage

from zhenxun.models.ban_console import BanConsole
from zhenxun.models.bot_console import BotConsole
from zhenxun.models.group_console import GroupConsole
from zhenxun.models.statistics import Statistics
from zhenxun.services.log import logger

from .. import summary_cd_limiter
from ..utils.message import (
    MessageFetchException,
    MessageProcessException,
    get_raw_group_msg_history,
    process_message,
)
from ..utils.summary import (
    ModelException,
    messages_summary,
    send_summary,
)


async def handle_summary(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    message_count: int,
    style: Match[str],
    parts: Match[list[At | Text]],
    target: MsgTarget,
):
    user_id_str = event.get_user_id()
    originating_group_id = (
        event.group_id if isinstance(event, GroupMessageEvent) else None
    )
    bot_id = bot.self_id
    plugin_name = "summary_group"
    is_superuser = await SUPERUSER(bot, event)

    target_group_id_to_fetch = None
    arp = result.result
    target_group_id_match = arp.query("g.target_group_id") if arp else None
    target_group_id_from_option = None
    if target_group_id_match and is_superuser:
        target_group_id_from_option = int(target_group_id_match)
        target_group_id_to_fetch = target_group_id_from_option
        logger.info(
            f"超级用户 {user_id_str} 请求总结群聊 {target_group_id_to_fetch} (来源: {originating_group_id or '私聊'})",
            command="总结",
            session=user_id_str,
            group_id=originating_group_id,
        )
    else:
        target_group_id_to_fetch = originating_group_id

    if target_group_id_to_fetch is None:
        logger.warning(
            f"用户 {user_id_str} 尝试在非群聊环境使用总结命令，且未提供 -g 参数",
            command="总结",
            session=user_id_str,
        )
        await UniMessage.text(
            "请在群聊中使用此命令，或使用 -g <群号> 参数指定目标群聊。 (仅限超级用户)"
        ).send(target)
        return

    try:
        if not await BotConsole.get_bot_status(bot_id):
            logger.info(
                f"Bot {bot_id} is inactive, skipping command.",
                command="总结",
                session=user_id_str,
                group_id=originating_group_id,
            )
            return

        if await BotConsole.is_block_plugin(bot_id, plugin_name):
            logger.info(
                f"Plugin '{plugin_name}' is blocked for Bot {bot_id}.",
                command="总结",
                session=user_id_str,
            )
            return

        if originating_group_id:
            if await GroupConsole.is_block_plugin(originating_group_id, plugin_name):
                logger.info(
                    f"Plugin '{plugin_name}' is blocked for Group {originating_group_id}.",
                    command="总结",
                    session=user_id_str,
                    group_id=originating_group_id,
                )
                await UniMessage.text("群聊总结功能在本群已被禁用。").send(target)
                return
            if await BanConsole.is_ban(None, originating_group_id):
                logger.info(
                    f"Group {originating_group_id} is banned.",
                    command="总结",
                    group_id=originating_group_id,
                )
                return
        if await BanConsole.is_ban(user_id_str, originating_group_id):
            logger.info(
                f"User {user_id_str} is banned in Group {originating_group_id or 'global'}.",
                command="总结",
                session=user_id_str,
                group_id=originating_group_id,
            )
            return

    except Exception as e:
        logger.error(
            f"执行命令前检查出错: {e}",
            command="总结",
            session=user_id_str,
            group_id=originating_group_id,
            e=e,
        )
        await UniMessage.text("执行命令前检查出错，请联系管理员。").send(target)
        return

    logger.debug(
        f"用户 {user_id_str} 在 {originating_group_id or '私聊'} 触发总结命令，目标群: {target_group_id_to_fetch}",
        command="总结",
        session=user_id_str,
        group_id=originating_group_id,
    )

    try:
        target_user_ids: set[str] = set()
        content_parts: list[str] = []
        target_user_names: list[str] = []

        style_value = style.result if style.available else None

        if parts.available:
            logger.debug(f"Parts available: {parts.result}", command="总结")

            for part in parts.result:
                if isinstance(part, At) and part.target:
                    target_user_ids.add(str(part.target))
                    logger.debug(f"Added target user: {part.target}", command="总结")

            for part in parts.result:
                if isinstance(part, Text):
                    stripped_text = part.text.strip()
                    if stripped_text:
                        content_parts.append(stripped_text)
                        logger.debug(
                            f"Added content part: {stripped_text}", command="总结"
                        )

        arp = result.result
        if arp and "$extra" in arp.main_args:
            extra_args = arp.main_args.get("$extra", [])
            if extra_args:
                logger.debug(f"Found extra args: {extra_args}", command="总结")

                for arg in extra_args:
                    if isinstance(arg, At) and arg.target:
                        target_user_ids.add(str(arg.target))
                        logger.debug(
                            f"Added target user from $extra: {arg.target}",
                            command="总结",
                        )

                for arg in extra_args:
                    if isinstance(arg, Text):
                        stripped_text = arg.text.strip()
                        if stripped_text:
                            content_parts.append(stripped_text)
                            logger.debug(
                                f"Added content part from $extra: {stripped_text}",
                                command="总结",
                            )

        content_value = " ".join(content_parts)

        if target_user_ids:
            logger.debug(
                f"最终收集到 {len(target_user_ids)} 个目标用户: {target_user_ids}",
                command="总结",
            )
        if content_value:
            logger.debug(f"最终收集到内容过滤: '{content_value}'", command="总结")

        if target_user_ids:
            logger.debug(
                f"最终收集到 {len(target_user_ids)} 个目标用户: {target_user_ids}",
                command="总结",
            )
        if content_value:
            logger.debug(f"最终收集到内容过滤: '{content_value}'", command="总结")

        logger.debug(
            f"总结参数: 目标群={target_group_id_to_fetch}, 消息数量={message_count}, 风格='{style_value or '默认'}', "
            f"内容过滤='{content_value or '无'}', 指定用户={target_user_ids or '无'}",
            command="总结",
            session=user_id_str,
            group_id=originating_group_id,
        )

        feedback_target_group_part = (
            f"群聊 {target_group_id_to_fetch} 的"
            if target_group_id_from_option
            else "群聊"
        )
        feedback = f"正在生成{feedback_target_group_part}总结{'（风格: ' + style_value + '）' if style_value else ''}"
        feedback += f"{'（指定用户）' if target_user_ids else ''}，请稍候..."
        await UniMessage.text(feedback).send(target)

        if not is_superuser:
            logger.debug(f"即将为用户 {user_id_str} (非超级用户) 启动冷却...")
            summary_cd_limiter.start_cd(user_id_str)

            next_available_time = summary_cd_limiter.next_time.get(user_id_str, 0)
            current_time = time.time()
            logger.debug(
                f"用户 {user_id_str} (非超级用户) 冷却已启动。"
                f"下次可用时间戳: {next_available_time:.2f}, 当前时间戳: {current_time:.2f}"
            )
        else:
            logger.debug(
                f"用户 {user_id_str} 是超级用户，不启动冷却",
                command="总结",
                session=user_id_str,
            )

        try:
            logger.debug(
                f"开始获取群 {target_group_id_to_fetch} 的原始消息: count={message_count}",
                command="总结",
                group_id=target_group_id_to_fetch,
            )
            raw_messages = await get_raw_group_msg_history(
                bot, target_group_id_to_fetch, message_count
            )
            if not raw_messages:
                logger.warning(
                    f"未能获取到群 {target_group_id_to_fetch} 的聊天记录",
                    command="总结",
                    group_id=target_group_id_to_fetch,
                )
                await UniMessage.text(
                    f"未能获取到群聊 {target_group_id_to_fetch} 的聊天记录。"
                ).send(target)
                return
            logger.debug(
                f"成功获取 {len(raw_messages)} 条原始消息",
                command="总结",
                group_id=target_group_id_to_fetch,
            )

            filtered_messages = raw_messages
            if target_user_ids:
                filtered_messages = [
                    msg
                    for msg in raw_messages
                    if str(msg.get("user_id")) in target_user_ids
                ]
                logger.debug(
                    f"过滤后剩余 {len(filtered_messages)} 条消息 (来自用户: {target_user_ids})",
                    command="总结",
                    group_id=target_group_id_to_fetch,
                )
                if not filtered_messages:
                    msg = f"在群聊 {target_group_id_to_fetch} 中未能获取到指定用户的有效聊天记录。"
                    logger.warning(
                        f"群 {target_group_id_to_fetch}: {msg}",
                        command="总结",
                        group_id=target_group_id_to_fetch,
                    )
                    await UniMessage.text(msg).send(target)
                    return

            logger.debug(
                f"开始处理群 {target_group_id_to_fetch} 的消息...",
                command="总结",
                group_id=target_group_id_to_fetch,
            )

            processed_messages, user_info_cache = await process_message(
                filtered_messages, bot, target_group_id_to_fetch
            )
            if not processed_messages:
                logger.warning(
                    f"处理消息后群 {target_group_id_to_fetch} 没有有效内容",
                    command="总结",
                    group_id=target_group_id_to_fetch,
                )
                await UniMessage.text("未能找到有效消息进行处理。").send(target)
                return
            logger.debug(
                f"成功处理消息，得到 {len(processed_messages)} 条记录",
                command="总结",
                group_id=target_group_id_to_fetch,
            )

            if target_user_ids:
                target_user_names = [
                    user_info_cache.get(uid, f"用户{uid[-4:]}")
                    for uid in target_user_ids
                ]
                logger.debug(
                    f"将对用户 {target_user_names} 进行过滤总结", command="总结"
                )

        except MessageFetchException as e:
            logger.error(
                f"获取群 {target_group_id_to_fetch} 消息历史失败: {e}",
                command="总结",
                group_id=target_group_id_to_fetch,
                e=e,
            )
            await UniMessage.text(
                f"获取群聊 {target_group_id_to_fetch} 消息历史失败: {e!s}"
            ).send(target)
            return
        except MessageProcessException as e:
            logger.error(
                f"处理群 {target_group_id_to_fetch} 消息失败: {e}",
                command="总结",
                group_id=target_group_id_to_fetch,
                e=e,
            )
            await UniMessage.text(
                f"处理群聊 {target_group_id_to_fetch} 消息失败: {e!s}"
            ).send(target)
            return
        except Exception as e:
            logger.error(
                f"获取或处理群 {target_group_id_to_fetch} 消息时发生未知错误: {e}",
                command="总结",
                group_id=target_group_id_to_fetch,
                e=e,
            )
            await UniMessage.text("获取或处理消息失败，请稍后再试。").send(target)
            return

        try:
            logger.debug(
                f"开始为群 {target_group_id_to_fetch} 生成总结，处理 {len(processed_messages)} 条消息",
                command="总结",
                group_id=target_group_id_to_fetch,
            )
            summary_content_target = MsgTarget(str(target_group_id_to_fetch))

            summary = await messages_summary(
                target=summary_content_target,
                messages=processed_messages,
                content=content_value,
                target_user_names=target_user_names if target_user_names else None,
                style=style_value,
            )
            logger.debug(
                f"群 {target_group_id_to_fetch} 总结生成成功，长度: {len(summary)} 字符",
                command="总结",
                group_id=target_group_id_to_fetch,
            )
        except ModelException as e:
            logger.error(
                f"生成群 {target_group_id_to_fetch} 的总结失败: {e}",
                command="总结",
                group_id=target_group_id_to_fetch,
                e=e,
            )
            return
        except Exception as e:
            logger.error(
                f"生成群 {target_group_id_to_fetch} 总结时发生未知错误: {e}",
                command="总结",
                group_id=target_group_id_to_fetch,
                e=e,
            )
            return

        success = await send_summary(bot, target, summary)

        if success:
            logger.debug(
                f"成功完成群 {target_group_id_to_fetch} 的总结命令 "
                f"(请求来源: {originating_group_id or '私聊'})，准备记录统计",
                command="总结",
                group_id=originating_group_id,
            )
            try:
                await Statistics.create(
                    user_id=str(user_id_str),
                    group_id=(
                        str(originating_group_id) if originating_group_id else None
                    ),
                    plugin_name="summary_group",
                    bot_id=str(bot.self_id),
                    message_count=message_count,
                    style=style_value,
                    target_users=list(target_user_ids),
                    content_filter=content_value,
                )
                logger.debug(
                    f"记录插件调用统计成功: user={user_id_str}, "
                    f"group={originating_group_id or '私聊'}, "
                    f"summarized_group={target_group_id_to_fetch}",
                    command="总结",
                )
            except Exception as stat_e:
                logger.error(
                    f"记录插件调用统计失败: {stat_e}", command="总结", e=stat_e
                )
            logger.debug(
                f"成功完成群 {target_group_id_to_fetch} 的总结命令",
                command="总结",
                group_id=target_group_id_to_fetch,
            )
        else:
            logger.error(
                f"向 {target} 发送群 {target_group_id_to_fetch} 的总结失败",
                command="总结",
                group_id=target_group_id_to_fetch,
            )

    except Exception as e:
        logger.error(
            f"处理总结命令时发生异常: {e}",
            command="总结",
            session=user_id_str,
            group_id=originating_group_id,
            exc_info=True,
        )
