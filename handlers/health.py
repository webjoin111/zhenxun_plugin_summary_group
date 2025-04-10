# handlers/health.py
from typing import Union
import asyncio
from zhenxun.services.log import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
import traceback
from nonebot_plugin_alconna.uniseg import Target, MsgTarget

from ..store import Store
from ..utils.health import check_system_health
from ..utils.scheduler import (
    process_summary_queue,
    task_processor_started,
)


async def handle_health_check(
    bot: Bot,
    event: Union[GroupMessageEvent, PrivateMessageEvent],
    target: MsgTarget
):

    try:
        user_id = event.get_user_id()
        logger.debug(f"用户 {user_id} 触发了健康检查命令", command="健康检查", session=user_id)

        await bot.send(event, "正在进行系统健康检查，请稍候...")

        health_result = await check_system_health()

        status_message = "【总结系统健康状态】\n"

        if health_result.get("healthy", False):
            status_message += "✅ 系统状态: 正常\n"
        else:
            status_message += "⚠️ 系统状态: 异常\n"

        scheduler_status = health_result.get("scheduler", {})
        status_message += f"📅 调度器: {'运行中' if scheduler_status.get('running', False) else '已停止'}\n"
        status_message += f"⏱️ 定时任务数量: {scheduler_status.get('jobs_count', 0)}\n"

        queue_status = health_result.get("task_queue", {})
        status_message += f"📋 队列处理器: {'活跃' if queue_status.get('processor_active', False) else '停止'}\n"
        status_message += f"🔢 队列大小: {queue_status.get('queue_size', 0)}\n"

        store = Store()
        group_count = len(store.get_all_groups())
        status_message += f"💾 已配置群组数: {group_count}\n"

        warnings = health_result.get("warnings", [])
        if warnings:
            status_message += "\n⚠️ 警告信息:\n"
            for warning in warnings:
                status_message += f"- {warning}\n"

        errors = health_result.get("errors", [])
        if errors:
            status_message += "\n❌ 错误信息:\n"
            for error in errors:
                status_message += f"- {error}\n"

        repairs = health_result.get("repairs_applied", [])
        if repairs:
            status_message += "\n🔧 已应用修复:\n"
            for repair in repairs:
                status_message += f"- {repair}\n"

        await bot.send(event, status_message)

    except Exception as e:
        user_id = event.get_user_id()
        logger.error(f"执行健康检查时发生错误: {e}", command="健康检查", session=user_id, e=e)
        logger.error(traceback.format_exc(), command="健康检查", session=user_id)
        await bot.send(event, f"健康检查失败: {str(e)}")


async def handle_system_repair(
    bot: Bot,
    event: Union[GroupMessageEvent, PrivateMessageEvent],
    target: MsgTarget
):
    from nonebot_plugin_apscheduler import scheduler

    user_id = event.get_user_id()
    logger.debug(f"用户 {user_id} 触发了系统修复命令", command="系统修复", session=user_id)

    await bot.send(event, "正在执行系统修复操作，请稍候...")

    try:

        repairs_applied = []
        errors = []

        try:

            all_tasks = asyncio.all_tasks()
            processor_tasks = [
                t for t in all_tasks if t.get_name() == "summary_queue_processor"
            ]

            for task in processor_tasks:
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

            queue_task = asyncio.create_task(process_summary_queue())
            queue_task.set_name("summary_queue_processor")
            global task_processor_started
            task_processor_started = True

            repairs_applied.append("队列处理器已重启")
            logger.debug("队列处理器已成功重启", command="系统修复", session=user_id)
        except Exception as e:
            errors.append(f"重启队列处理器失败: {str(e)}")
            logger.error(f"重启队列处理器时出错: {e}", command="系统修复", session=user_id, e=e)

        try:
            if not scheduler.running:
                scheduler.start()
                repairs_applied.append("调度器已启动")
        except Exception as e:
            errors.append(f"启动调度器失败: {str(e)}")
            logger.error(f"启动调度器时出错: {e}", command="系统修复", session=user_id, e=e)

        try:
            store = Store()
            cleaned_count = store.cleanup_invalid_groups()
            if cleaned_count > 0:
                repairs_applied.append(f"已清理 {cleaned_count} 个无效群组配置")
                logger.debug(f"已清理 {cleaned_count} 个无效群组配置", command="系统修复", session=user_id)
        except Exception as e:
            errors.append(f"清理存储数据失败: {str(e)}")
            logger.error(f"清理存储数据时出错: {e}", command="系统修复", session=user_id, e=e)

        try:

            group_ids = store.get_all_groups()

            scheduled_jobs = scheduler.get_jobs()
            scheduled_job_ids = [
                job.id for job in scheduled_jobs if job.id.startswith("summary_group_")
            ]

            missing_jobs = []
            for group_id in group_ids:
                job_id = f"summary_group_{group_id}"
                if job_id not in scheduled_job_ids:
                    missing_jobs.append(group_id)

            orphaned_jobs = []
            for job_id in scheduled_job_ids:
                group_id = job_id.replace("summary_group_", "")
                if group_id not in group_ids:
                    orphaned_jobs.append(job_id)

            if missing_jobs:
                recreated_count = 0
                for group_id_str in missing_jobs:
                    try:
                        from ..utils.scheduler import update_single_group_schedule

                        group_id = int(group_id_str)
                        data = store.get(group_id)
                        if data:
                            success, _ = await update_single_group_schedule(
                                group_id, data
                            )
                            if success:
                                recreated_count += 1
                    except Exception as e:
                        logger.error(f"重建群 {group_id_str} 的定时任务失败: {e}", command="系统修复", session=user_id, e=e)

                if recreated_count > 0:
                    repairs_applied.append(f"已重建 {recreated_count} 个缺失的定时任务")
                    logger.debug(f"已重建 {recreated_count} 个缺失的定时任务", command="系统修复", session=user_id)

            if orphaned_jobs:
                removed_count = 0
                for job_id in orphaned_jobs:
                    try:
                        scheduler.remove_job(job_id)
                        removed_count += 1
                    except Exception as e:
                        logger.error(f"移除孤立任务 {job_id} 失败: {e}", command="系统修复", session=user_id, e=e)

                if removed_count > 0:
                    repairs_applied.append(f"已移除 {removed_count} 个孤立的定时任务")
                    logger.debug(f"已移除 {removed_count} 个孤立的定时任务", command="系统修复", session=user_id)
        except Exception as e:
            errors.append(f"修复任务调度问题失败: {str(e)}")
            logger.error(f"修复任务调度问题时出错: {e}", command="系统修复", session=user_id, e=e)

        try:
            health_result = await check_system_health()
            if health_result.get("repairs_applied"):
                repairs_applied.extend(health_result["repairs_applied"])
        except Exception as e:
            errors.append(f"执行健康检查失败: {str(e)}")
            logger.error(f"执行健康检查时出错: {e}", command="系统修复", session=user_id, e=e)

        if repairs_applied or errors:
            response = "【系统修复报告】\n"

            if repairs_applied:
                response += "\n✅ 已完成的修复操作:\n"
                for repair in repairs_applied:
                    response += f"- {repair}\n"

            if errors:
                response += "\n❌ 修复过程中的错误:\n"
                for error in errors:
                    response += f"- {error}\n"

            if not errors:
                response += "\n系统修复已完成，请重新检查系统状态。"
            else:
                response += "\n系统修复部分完成，仍有错误未解决。"
        else:
            response = "系统状态良好，无需修复。"

        await bot.send(event, response)

    except Exception as e:
        user_id = event.get_user_id()
        logger.error(f"执行系统修复时发生错误: {e}", command="系统修复", session=user_id, e=e)
        logger.error(traceback.format_exc(), command="系统修复", session=user_id)
        await bot.send(event, f"执行系统修复失败: {str(e)}")
