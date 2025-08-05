from nonebot.adapters.onebot.v11 import Bot
from pydantic import BaseModel, Field

from zhenxun.services.llm import LLMException
from zhenxun.services.log import logger
from zhenxun.services.scheduler import ScheduleContext, scheduler_manager

from .. import base_config
from .core import SummaryException
from .summary_generation import messages_summary, send_summary


class SummaryTaskParams(BaseModel):
    """定时总结任务的参数模型"""

    least_message_count: int = Field(
        default_factory=lambda: base_config.get("SUMMARY_MAX_LENGTH", 1000),
        description="总结所需的最少消息数",
    )
    style: str | None = Field(default=None, description="总结的风格")
    model: str | None = Field(default=None, description="使用的AI模型")


@scheduler_manager.register(
    plugin_name="summary_group",
    params_model=SummaryTaskParams,
)
async def scheduled_summary_task(
    bot: Bot,
    context: ScheduleContext,
    params: SummaryTaskParams,
) -> None:
    """
    这是由 scheduler_manager 调度的、支持依赖注入的任务函数。
    它处理单个群组的总结任务。
    """
    group_id = context.group_id
    if not group_id:
        logger.warning(
            f"定时总结任务 (ID: {context.schedule_id}) 缺少 group_id，跳过执行。"
        )
        return

    task_id = f"summary_task_{group_id}"
    logger.info(f"开始执行定时总结任务 [{task_id}]", group_id=group_id)

    try:
        least_message_count = params.least_message_count
        style = params.style
        model = params.model

        from .message_processing import get_group_messages

        min_len_required = base_config.get("SUMMARY_MIN_LENGTH", 50)
        if least_message_count < min_len_required:
            logger.warning(
                f"[{task_id}] 群 {group_id} 定时任务的最少消息数 ({least_message_count}) 低于系统要求 ({min_len_required})，跳过本次执行。"
            )
            return

        processed_messages, user_info_cache = await get_group_messages(
            bot,
            int(group_id),
            least_message_count,
            use_db=base_config.get("USE_DB_HISTORY", False),
        )

        if not processed_messages or len(processed_messages) < min_len_required:
            logger.info(
                f"[{task_id}] 群 {group_id} 消息数量不足 ({len(processed_messages)}/{min_len_required})，不生成总结。"
            )
            return

        from nonebot_plugin_alconna.uniseg import Target

        msg_target = Target.group(group_id=int(group_id))

        summary = await messages_summary(
            target=msg_target,
            messages=processed_messages,
            style=style,
            model_name=model,
        )

        await send_summary(bot, msg_target, summary, user_info_cache)

    except (SummaryException, LLMException) as e:
        logger.error(f"[{task_id}] 执行定时总结失败: {e}", group_id=group_id, e=e)
    except Exception as e:
        logger.error(
            f"[{task_id}] 执行定时总结时发生未知错误: {e}", group_id=group_id, e=e
        )
