from typing import Union, List
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot_plugin_alconna.uniseg import UniMessage, Target, MsgTarget
from nonebot_plugin_alconna import Match, At, Text
from nonebot.permission import SUPERUSER
from zhenxun.services.log import logger
from zhenxun.configs.config import Config
from zhenxun.models.statistics import Statistics
from .. import summary_cd_limiter
from ..utils.message import (
    get_group_msg_history,
    MessageFetchException,
    check_cooldown,
)
from ..utils.summary import (
    messages_summary,
    send_summary,
    ModelException,
)
import time


async def handle_summary(
    bot: Bot,
    event: Union[GroupMessageEvent, PrivateMessageEvent],
    message_count: int,
    style: Match[str],
    parts: Match[List[Union[At, Text]]],
    target: MsgTarget,
):
    user_id_str = event.get_user_id()
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None

    if not group_id:
        logger.warning(
            f"用户 {user_id_str} 尝试在非群聊中使用总结命令",
            command="总结",
            session=user_id_str,
        )
        await UniMessage.text("总结命令只能在群聊中使用。").send(target)
        return

    logger.debug(
        f"用户 {user_id_str} 在群 {group_id} 触发了总结命令 (冷却检查已通过)",
        command="总结",
        session=user_id_str,
        group_id=group_id,
    )

    try:
        base_config = Config.get("summary_group")

        target_user_ids: set[str] = set()
        content_parts: list[str] = []
        target_user_names: list[str] = []

        if parts.available:
            for part in parts.result:
                if isinstance(part, At):
                    if part.target:
                        target_user_ids.add(str(part.target))
                elif isinstance(part, Text):
                    stripped_text = part.text.strip()
                    if stripped_text:
                        content_parts.append(stripped_text)

        content_value = " ".join(content_parts)
        style_value = style.result if style.available else None

        logger.debug(
            f"总结参数: 消息数量={message_count}, 风格='{style_value or '默认'}', "
            f"内容过滤='{content_value or '无'}', 指定用户={target_user_ids or '无'}",
            command="总结",
            session=user_id_str,
            group_id=group_id,
        )

        feedback = (
            f"正在生成群聊总结{'（风格: ' + style_value + '）' if style_value else ''}"
        )
        feedback += f"{'（指定用户）' if target_user_ids else ''}，请稍候..."
        await UniMessage.text(feedback).send(target)

        is_superuser = await SUPERUSER(bot, event)
        if not is_superuser:

            logger.debug(f"即将为用户 {user_id_str} (非超级用户) 启动冷却...")
            summary_cd_limiter.start_cd(user_id_str)

            next_available_time = summary_cd_limiter.next_time.get(user_id_str, 0)
            current_time = time.time()
            logger.debug(
                f"用户 {user_id_str} (非超级用户) 冷却已启动。下次可用时间戳: {next_available_time:.2f}, 当前时间戳: {current_time:.2f}"
            )
        else:
            logger.debug(
                f"用户 {user_id_str} 是超级用户，不启动冷却",
                command="总结",
                session=user_id_str,
            )

        try:

            processed_messages, user_info_cache = await get_group_msg_history(
                bot,
                group_id,
                message_count,
                target_user_ids if target_user_ids else None,
            )

            if not processed_messages:
                msg = (
                    f"未能获取到{'指定用户的' if target_user_ids else ''}有效聊天记录。"
                )
                logger.warning(
                    f"群 {group_id}: {msg}", command="总结", group_id=group_id
                )
                await UniMessage.text(msg).send(target)
                return

            logger.debug(
                f"从群 {group_id} 获取了 {len(processed_messages)} 条有效消息{'（已过滤）' if target_user_ids else ''}",
                command="总结",
                group_id=group_id,
            )

            if target_user_ids and user_info_cache:
                target_user_names = [
                    user_info_cache.get(uid, f"用户{uid[-4:]}")
                    for uid in target_user_ids
                ]

        except MessageFetchException as e:
            logger.error(
                f"获取群 {group_id} 消息历史失败: {e}",
                command="总结",
                group_id=group_id,
                e=e,
            )
            await UniMessage.text(f"获取消息历史失败: {str(e)}").send(target)
            return
        except Exception as e:
            logger.error(
                f"获取群 {group_id} 消息时发生未知错误: {e}",
                command="总结",
                group_id=group_id,
                e=e,
            )
            await UniMessage.text("获取消息失败，请稍后再试。").send(target)
            return

        try:

            logger.debug(
                f"开始为群 {group_id} 生成总结，处理 {len(processed_messages)} 条消息",
                command="总结",
                group_id=group_id,
            )
            summary = await messages_summary(
                processed_messages,
                content_value,
                target_user_names if target_user_names else None,
                style_value,
            )
            logger.debug(
                f"群 {group_id} 总结生成成功，长度: {len(summary)} 字符",
                command="总结",
                group_id=group_id,
            )
        except ModelException as e:
            logger.error(
                f"生成群 {group_id} 的总结失败: {e}",
                command="总结",
                group_id=group_id,
                e=e,
            )
            await UniMessage.text(f"生成总结失败: {str(e)}").send(target)
            return
        except Exception as e:
            logger.error(
                f"生成群 {group_id} 总结时发生未知错误: {e}",
                command="总结",
                group_id=group_id,
                e=e,
            )
            await UniMessage.text("生成总结失败，请稍后再试。").send(target)
            return

        success = await send_summary(bot, target, summary)

        if success:
            logger.debug(
                f"成功完成群 {group_id} 的总结命令，准备记录统计",
                command="总结",
                group_id=group_id,
            )
            try:
                await Statistics.create(
                    user_id=str(user_id_str),
                    group_id=str(group_id),
                    plugin_name="summary_group",
                    bot_id=str(bot.self_id),
                    message_count=message_count,
                    style=style_value,
                    target_users=list(target_user_ids),
                    content_filter=content_value,
                )
                logger.debug(
                    f"记录插件调用统计成功: user={user_id_str}, group={group_id}",
                    command="总结",
                )
            except Exception as stat_e:
                logger.error(
                    f"记录插件调用统计失败: {stat_e}", command="总结", e=stat_e
                )
            logger.debug(
                f"成功完成群 {group_id} 的总结命令", command="总结", group_id=group_id
            )
        else:
            logger.error(
                f"向群 {group_id} 发送总结失败", command="总结", group_id=group_id
            )

    except Exception as e:
        logger.error(
            f"处理总结命令时发生异常: {e}",
            command="总结",
            session=user_id_str,
            group_id=group_id,
            exc_info=True,
        )
        try:
            await UniMessage.text(f"处理命令时出错: {str(e)}").send(target)
        except Exception:
            logger.error(
                "发送最终错误消息失败",
                command="总结",
                session=user_id_str,
                group_id=group_id,
            )
