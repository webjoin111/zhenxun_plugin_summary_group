# handlers/summary.py
from typing import Union, List
from nonebot import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from nonebot_plugin_alconna import Match, At, Text
from nonebot_plugin_alconna.uniseg import UniMessage, Target, MsgTarget
from zhenxun.services.log import logger
from zhenxun.configs.config import Config
from zhenxun.models.statistics import Statistics

from ..utils.message import (
    get_group_msg_history,
    MessageFetchException,
)
from ..utils.summary import (
    messages_summary,
    send_summary,
    ModelException,
)


async def handle_summary(
    bot: Bot,
    event: Union[GroupMessageEvent, PrivateMessageEvent],
    message_count: int,
    style: Match[str],
    parts: Match[List[Union[At, Text]]],
    target: MsgTarget,
):
    """处理总结命令

    Args:
        bot: Bot 实例
        event: 消息事件
        message_count: 消息数量
        style: 总结风格
        parts: 命令参数（@用户和文本内容）
        target: 消息目标
    """
    user_id = event.get_user_id()
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None

    if not group_id:
        logger.warning(
            f"用户 {user_id} 尝试在非群聊中使用总结命令",
            command="总结",
            session=user_id,
        )
        await UniMessage.text("总结命令只能在群聊中使用。").send(target)
        return

    logger.debug(
        f"用户 {user_id} 在群 {group_id} 触发了总结命令",
        command="总结",
        session=user_id,
        group_id=group_id,
    )

    try:
        base_config = Config.get("summary_group")

        # --- 处理 parts: 分离 At 和 Text ---
        target_user_ids: set[str] = set()
        content_parts: list[str] = []
        target_user_names: list[str] = []  # 用于 prompt

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
            session=user_id,
            group_id=group_id,
        )

        # 发送反馈消息
        feedback = (
            f"正在生成群聊总结{'（风格: ' + style_value + '）' if style_value else ''}"
        )
        feedback += f"{'（指定用户）' if target_user_ids else ''}，请稍候..."
        await UniMessage.text(feedback).send(target)

        try:
            # 获取消息历史
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
            # 生成总结
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

        # 发送总结
        success = await send_summary(bot, target, summary)

        # 记录统计信息
        if success:
            logger.debug(
                f"成功完成群 {group_id} 的总结命令，准备记录统计",
                command="总结",
                group_id=group_id,
            )
            try:
                await Statistics.create(
                    user_id=str(user_id),
                    group_id=str(group_id),
                    plugin_name="summary_group",
                    bot_id=str(bot.self_id),
                )
                logger.debug(
                    f"记录插件调用统计成功: user={user_id}, group={group_id}",
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
            session=user_id,
            group_id=group_id,
            e=e,
        )
        try:
            await UniMessage.text(f"处理命令时出错: {str(e)}").send(target)
        except Exception:
            logger.error(
                "发送最终错误消息失败",
                command="总结",
                session=user_id,
                group_id=group_id,
            )
