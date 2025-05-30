import asyncio
from typing import Any

from nonebot.adapters.onebot.v11 import Bot

from zhenxun.services.log import logger
from zhenxun.utils.platform import PlatformUtils

from .. import base_config

try:
    from zhenxun.models.chat_history import ChatHistory
except ImportError:
    ChatHistory = None
    logger.warning("无法导入 ChatHistory 模型，数据库历史记录功能不可用。")

from .exceptions import ErrorCode, MessageFetchException, MessageProcessException
from .health import with_retry


async def get_raw_group_msg_history(bot: Bot, group_id: int, count: int) -> list:
    """获取原始群聊消息历史，根据配置选择来源"""

    use_db = base_config.get("USE_DB_HISTORY", False)
    group_id_str = str(group_id)

    if use_db and ChatHistory:
        logger.debug(
            f"尝试从数据库获取群 {group_id} 的最近 {count} 条聊天记录", command="DB历史"
        )
        try:
            db_messages = (
                await ChatHistory.filter(group_id=group_id_str)
                .order_by("-create_time")
                .limit(count)
                .all()
            )

            if not db_messages:
                logger.warning(
                    f"数据库中未找到群 {group_id} 的聊天记录",
                    command="DB历史",
                    group_id=group_id,
                )
                return []

            formatted_messages = []
            for msg in reversed(db_messages):
                formatted_messages.append(
                    {
                        "message_id": msg.id,
                        "user_id": int(msg.user_id) if msg.user_id.isdigit() else 0,
                        "time": int(msg.create_time.timestamp()),
                        "message_type": "group",
                        "message": [
                            {
                                "type": "text",
                                "data": {"text": msg.plain_text or ""},
                            }
                        ],
                        "raw_message": msg.plain_text or "",
                        "sender": {
                            "user_id": int(msg.user_id) if msg.user_id.isdigit() else 0
                        },
                    }
                )
            logger.debug(
                f"从数据库成功获取并格式化 {len(formatted_messages)} 条消息 (使用 plain_text)",
                command="DB历史",
                group_id=group_id,
            )
            logger.warning(
                "使用数据库历史记录时，图片、@ 等非文本信息可能无法正确处理。",
                command="DB历史",
            )
            return formatted_messages
        except Exception as e:
            logger.error(
                f"从数据库获取群 {group_id} 历史记录失败: {e}",
                command="DB历史",
                group_id=group_id,
                e=e,
            )
            ex = MessageFetchException(
                message=f"数据库历史记录获取失败: {e!s}",
                code=ErrorCode.DB_QUERY_ERROR,
                details={"error": str(e), "group_id": group_id, "count": count},
                cause=e,
            )
            raise ex from e
    else:
        if use_db and not ChatHistory:
            logger.warning(
                "配置了使用数据库历史但 ChatHistory 模型导入失败，回退到 API 获取。"
            )

        logger.debug(
            f"通过 API 获取群 {group_id} 的最近 {count} 条聊天记录", command="API历史"
        )
        try:

            async def fetch():
                response = await bot.get_group_msg_history(
                    group_id=group_id, count=count
                )
                raw_messages = response.get("messages", [])
                logger.debug(
                    f"从群 {group_id} API 获取了 {len(raw_messages)} 条原始消息",
                    command="API历史",
                    group_id=group_id,
                )
                return raw_messages

            max_retries = base_config.get("MAX_RETRIES", 2)
            retry_delay = base_config.get("RETRY_DELAY", 1)
            return await with_retry(
                fetch,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
        except Exception as e:
            logger.error(
                f"通过 API 获取群 {group_id} 的原始消息历史失败 (with_retry后): {e}",
                command="API历史",
                group_id=group_id,
                e=e,
            )
            ex = MessageFetchException(
                message=f"API 消息历史获取失败: {e!s}",
                code=ErrorCode.MESSAGE_FETCH_FAILED,
                details={"error": str(e), "group_id": group_id, "count": count},
                cause=e,
            )
            raise ex from e


async def process_message(
    messages: list, bot: Bot, group_id: int
) -> tuple[list[dict[str, str]], dict[str, str]]:
    logger.debug(
        f"开始处理群 {group_id} 的 {len(messages)} 条原始消息",
        command="消息处理",
        group_id=group_id,
    )
    try:
        if not messages:
            return [], {}

        exclude_bot = base_config.get("EXCLUDE_BOT_MESSAGES", False)
        bot_self_id = bot.self_id

        user_ids_to_fetch: set[str] = set()
        for msg in messages:
            sender_id = msg.get("user_id")
            if sender_id:
                user_ids_to_fetch.add(str(sender_id))
            raw_segments = msg.get("message", [])
            for segment in raw_segments:
                if isinstance(segment, dict):
                    seg_type = segment.get("type")
                    seg_data = segment.get("data", {})
                    if seg_type == "at" and "qq" in seg_data:
                        user_ids_to_fetch.add(str(seg_data["qq"]))

        user_info_cache: dict[str, str] = {}
        group_id_str = str(group_id)

        if user_ids_to_fetch:
            logger.debug(
                f"需要获取 {len(user_ids_to_fetch)} 个用户的信息: {user_ids_to_fetch}",
                group_id=group_id,
            )
            tasks = []
            user_id_list = list(user_ids_to_fetch)
            for user_id_str in user_id_list:
                task = PlatformUtils.get_user(bot, user_id_str, group_id_str)
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for user_id_str, result in zip(user_id_list, results):
                fallback_name = f"用户_{user_id_str[-4:]}"
                if isinstance(result, Exception):
                    logger.warning(
                        f"并发获取用户 {user_id_str} 信息失败: {result}. 使用默认值",
                        group_id=group_id,
                        e=result,
                    )
                    user_info_cache[user_id_str] = fallback_name
                elif result:
                    user_data = result
                    sender_name = user_data.card or user_data.name or fallback_name
                    user_info_cache[user_id_str] = sender_name
                else:
                    user_info_cache[user_id_str] = fallback_name
            logger.debug(
                f"用户信息并发获取完成，缓存了 {len(user_info_cache)} 个用户信息",
                group_id=group_id,
            )

        processed_log: list[dict[str, str]] = []
        for msg in messages:
            user_id = msg.get("user_id")
            if not user_id:
                continue

            user_id_str = str(user_id)
            if exclude_bot and user_id_str == bot_self_id:
                continue

            sender_name = user_info_cache.get(user_id_str, f"用户_{user_id_str[-4:]}")

            raw_segments = msg.get("message", [])
            text_segments: list[str] = []

            for segment in raw_segments:
                if not isinstance(segment, dict):
                    continue
                seg_type = segment.get("type")
                seg_data = segment.get("data", {})
                if seg_type == "text" and "text" in seg_data:
                    text = seg_data["text"].strip()
                    if text:
                        text_segments.append(text)
                elif seg_type == "at" and "qq" in seg_data:
                    qq = str(seg_data["qq"])
                    at_name = user_info_cache.get(qq, f"用户_{qq[-4:]}")
                    text_segments.append(f"@{at_name}")

            if text_segments:
                message_content = "".join(text_segments)
                processed_log.append({"name": sender_name, "content": message_content})

        logger.debug(
            f"消息处理完成，生成 {len(processed_log)} 条处理记录 (已应用Bot排除设置: {exclude_bot})",
            group_id=group_id,
        )
        return processed_log, user_info_cache

    except Exception as e:
        logger.error(
            f"处理群 {group_id} 消息时出错: {e}",
            command="消息处理",
            e=e,
            group_id=group_id,
        )
        ex = MessageProcessException(
            message=f"消息处理失败: {e!s}",
            code=ErrorCode.MESSAGE_PROCESS_FAILED,
            details={
                "error": str(e),
                "group_id": group_id,
                "message_count": len(messages) if messages else 0,
            },
            cause=e,
        )
        raise ex from e


async def get_group_msg_history(
    bot: Bot, group_id: int, count: int, target_user_ids: set[str] | None = None
) -> tuple[list[dict[str, str]], dict[str, str]]:
    async def fetch_messages():
        try:
            response = await bot.get_group_msg_history(group_id=group_id, count=count)
            raw_messages = response.get("messages", [])

            logger.debug(
                f"从群 {group_id} 获取了 {len(raw_messages)} 条原始消息",
                command="get_group_msg_history",
                group_id=group_id,
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
                    command="get_group_msg_history",
                    group_id=group_id,
                )

            if not filtered_messages:
                logger.warning(
                    f"群 {group_id} 未返回任何有效消息{'（指定用户）' if target_user_ids else ''}",
                    command="get_group_msg_history",
                    group_id=group_id,
                )
                return [], {}

            processed_data, user_info_cache = await process_message(
                filtered_messages, bot, group_id
            )
            return processed_data, user_info_cache
        except MessageFetchException:
            raise
        except Exception as e:
            logger.error(
                f"获取或处理群 {group_id} 的消息历史失败: {e}",
                command="get_group_msg_history",
                group_id=group_id,
                e=e,
            )
            ex = MessageFetchException(
                message=f"获取或处理消息历史失败: {e!s}",
                code=ErrorCode.MESSAGE_FETCH_FAILED,
                details={"error": str(e), "group_id": group_id, "count": count},
                cause=e,
            )
            raise ex

    try:
        max_retries = base_config.get("MAX_RETRIES", 2)
        retry_delay = base_config.get("RETRY_DELAY", 1)
        return await with_retry(
            fetch_messages,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
    except MessageFetchException:
        raise
    except Exception as e:
        logger.error(
            f"消息获取过程中出现意外错误: {e}",
            command="get_group_msg_history",
            group_id=group_id,
            e=e,
        )
        ex = MessageFetchException(
            message=f"获取消息失败: {e!s}",
            code=ErrorCode.MESSAGE_FETCH_FAILED,
            details={"error": str(e), "group_id": group_id},
            cause=e,
        )
        raise ex


async def check_message_count(
    messages: list[dict[str, Any]], min_count: int | None = None
) -> bool:
    try:
        if not messages:
            return False

        if min_count is None:
            min_len = base_config.get("SUMMARY_MIN_LENGTH")
            max_len = base_config.get("SUMMARY_MAX_LENGTH")

            if min_len is None or max_len is None:
                logger.warning(
                    "无法从配置获取 SUMMARY_MIN/MAX_LENGTH，使用默认检查值 (50)"
                )
                min_count = 50
            else:
                try:
                    min_count = min(int(min_len), int(max_len))
                except (ValueError, TypeError):
                    logger.warning(
                        "配置 SUMMARY_MIN/MAX_LENGTH 值无效，使用默认检查值 (50)"
                    )
                    min_count = 50

        return len(messages) >= min_count
    except Exception as e:
        logger.error(f"检查消息数量时出错: {e}", command="check_message_count", e=e)
        return False


def check_cooldown(user_id: int | str) -> bool:
    from .. import summary_cd_limiter

    try:
        user_id_str = str(user_id)
        is_ready = summary_cd_limiter.check(user_id_str)
        if not is_ready:
            left = summary_cd_limiter.left_time(user_id_str)
            logger.debug(
                f"用户 {user_id_str} 冷却检查：否 (剩余 {left:.1f}s)",
                command="check_cooldown",
            )

        return is_ready
    except Exception as e:
        logger.error(
            f"检查冷却时间时出错: {e}", command="check_cooldown", session=user_id, e=e
        )

        return True
