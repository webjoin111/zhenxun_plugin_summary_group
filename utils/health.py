# utils/health.py
import asyncio
from typing import Callable, Any
from zhenxun.services.log import logger
from nonebot import require

from nonebot_plugin_apscheduler import scheduler

from ..store import Store


async def with_retry(func: Callable, max_retries: int = 3, retry_delay: int = 2) -> Any:
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt < max_retries - 1:
                delay = retry_delay * (2**attempt)
                logger.warning(
                    f"操作失败 ({attempt+1}/{max_retries})，将在 {delay} 秒后重试: {e}",
                    command="with_retry", e=e
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"操作失败，已达到最大重试次数 ({max_retries}): {e}", command="with_retry", e=e)
                raise


async def check_system_health():
    import asyncio
    from .scheduler import task_processor_started, summary_queue, process_summary_queue

    health_status = {
        "scheduler": {
            "running": scheduler.running,
            "jobs_count": len(scheduler.get_jobs()),
        },
        "task_queue": {
            "processor_active": task_processor_started,
            "queue_size": summary_queue.qsize() if summary_queue else None,
        },
        "repairs_applied": [],
        "warnings": [],
    }

    if not scheduler.running:
        health_status["warnings"].append("调度器未运行")

        try:
            scheduler.start()
            health_status["repairs_applied"].append("已启动调度器")
        except Exception as e:
            health_status["errors"] = [f"启动调度器失败: {str(e)}"]

    all_tasks = asyncio.all_tasks()
    processor_tasks = [
        t for t in all_tasks if t.get_name() == "summary_queue_processor"
    ]

    health_status["task_queue"]["processor_count"] = len(processor_tasks)

    if not processor_tasks:
        health_status["warnings"].append("未找到队列处理器任务")

        try:
            queue_task = asyncio.create_task(process_summary_queue())
            queue_task.set_name("summary_queue_processor")
            health_status["repairs_applied"].append("已重启队列处理器")
        except Exception as e:
            health_status["errors"] = health_status.get("errors", []) + [
                f"重启队列处理器失败: {str(e)}"
            ]
    else:

        for task in processor_tasks:
            if task.done():
                health_status["warnings"].append("队列处理器任务已完成")

                if task.exception():
                    health_status["warnings"].append(
                        f"队列处理器异常: {task.exception()}"
                    )

                try:
                    queue_task = asyncio.create_task(process_summary_queue())
                    queue_task.set_name("summary_queue_processor")
                    health_status["repairs_applied"].append("已重启队列处理器")
                except Exception as e:
                    health_status["errors"] = health_status.get("errors", []) + [
                        f"重启队列处理器失败: {str(e)}"
                    ]

    store = Store()
    group_ids = store.get_all_groups()
    scheduled_job_ids = [
        job.id for job in scheduler.get_jobs() if job.id.startswith("summary_group_")
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
        health_status["warnings"].append(f"发现 {len(missing_jobs)} 个未调度的任务")

    if orphaned_jobs:
        health_status["warnings"].append(f"发现 {len(orphaned_jobs)} 个孤立的调度任务")

        removed_count = 0
        for job_id in orphaned_jobs:
            try:
                scheduler.remove_job(job_id)
                removed_count += 1
            except Exception:
                pass

        if removed_count > 0:
            health_status["repairs_applied"].append(
                f"已移除 {removed_count} 个孤立的调度任务"
            )

    health_status["healthy"] = (
        not health_status.get("errors")
        and not health_status.get("warnings")
        and scheduler.running
        and task_processor_started
    )

    logger.debug(f"系统健康检查结果: {health_status}", command="check_system_health")
    return health_status
