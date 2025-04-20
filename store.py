import asyncio
import copy
import json
from pathlib import Path
import time
from typing import Any, Optional, TypedDict

from nonebot import logger

from zhenxun.configs.path_config import DATA_PATH


class ScheduleData(TypedDict):
    hour: int
    minute: int
    least_message_count: int
    style: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class GroupSettingData(TypedDict, total=False):
    default_model_name: Optional[str]
    default_style: Optional[str]
    updated_at: Optional[str]


class Store:
    def __init__(self, file_path: str | Path | None = None):
        plugin_data_dir = DATA_PATH / "summary_group"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在

        # --- 定时任务设置文件路径 ---
        if file_path:
            self.schedule_file_path = Path(file_path)
        else:
            default_schedule_filename = "summary_settings.json"
            self.schedule_file_path = plugin_data_dir / default_schedule_filename

        # --- 新增分群设置文件路径 ---
        self.group_settings_file_path = plugin_data_dir / "group_specific_settings.json"

        self._lock = asyncio.Lock()  # 共用一个锁，简化处理

        # --- 加载数据 ---
        self.schedule_data: dict[str, ScheduleData] = self._load_json_data(self.schedule_file_path)
        self.group_settings_data: dict[str, GroupSettingData] = self._load_json_data(self.group_settings_file_path)

    def _load_json_data(self, path: Path) -> dict:
        """通用加载 JSON 文件数据"""
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    content = f.read()
                    if not content:
                        logger.warning(f"存储文件为空: {path}")
                        return {}
                    data = json.loads(content)
                    if isinstance(data, dict):
                        return data
                    else:
                        logger.error(f"存储文件顶层结构不是字典: {path}")
                        # 可以选择备份错误文件
                        self._backup_corrupted_file(path)
                        return {}
            return {}
        except json.JSONDecodeError as e:
            logger.error(
                f"加载存储数据失败: JSON 解析错误于 {path} - {e}",
            )
            self._backup_corrupted_file(path)
            return {}
        except Exception as e:
            logger.error(f"加载存储数据时发生未知错误 ({path}): {e}", e=e)
            return {}

    def _backup_corrupted_file(self, path: Path):
        """备份损坏的 JSON 文件"""
        try:
            corrupted_path = path.with_suffix(f".json.corrupted_{int(time.time())}")
            path.rename(corrupted_path)
            logger.warning(f"损坏的配置文件已备份到: {corrupted_path}")
        except OSError as backup_e:
            logger.error(f"备份损坏的配置文件失败 ({path}): {backup_e}", e=backup_e)

    def _save_json_data(self, data: dict, path: Path) -> bool:
        """通用保存数据到 JSON 文件，使用原子写操作"""
        temp_path = path.with_suffix(".json.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as f:
                if not isinstance(data, dict):
                    logger.error(f"尝试保存非字典类型的数据到 {path}")
                    return False
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 原子替换
            temp_path.replace(path)
            return True
        except TypeError as e:
            logger.error(f"保存存储数据失败 ({path}): 数据无法序列化为 JSON - {e}", e=e)
            if temp_path.exists():
                temp_path.unlink() # 清理临时文件
            return False
        except Exception as e:
            logger.error(f"保存存储数据失败 ({path}): {e}", e=e)
            if temp_path.exists():
                temp_path.unlink()
            return False

    # --- 定时任务相关方法 (保持不变，操作 schedule_data) ---
    def set(self, group_id: int, data: dict) -> bool: # 注意：此方法仅用于定时任务设置
        group_id_str = str(group_id)
        # ... (原有的验证逻辑，确保 ScheduleData 的字段) ...
        try:
            # 验证 ScheduleData 的必需字段
            required_fields = {"hour": int, "minute": int, "least_message_count": int}
            optional_fields = {"style": (str, type(None))}
            validated_data = {}

            if not isinstance(data, dict):
                 logger.warning(f"[定时任务] 尝试为群 {group_id} 设置非字典类型的数据")
                 return False

            for field, field_type in required_fields.items():
                if field not in data:
                    logger.warning(f"[定时任务] 为群 {group_id} 设置的数据缺少必填字段 '{field}'")
                elif not isinstance(data[field], field_type):
                    logger.warning(f"[定时任务] 为群 {group_id} 设置的数据字段 '{field}' 类型错误")
                else:
                    validated_data[field] = data[field]

            for field, allowed_types in optional_fields.items():
                if field in data:
                    if isinstance(data[field], allowed_types):
                         validated_data[field] = data[field]
                    elif data[field] is None and type(None) in allowed_types: # 显式处理 None
                         validated_data[field] = None
                    else:
                         logger.warning(f"[定时任务] 为群 {group_id} 设置的数据字段 '{field}' 类型错误")

            if not all(key in validated_data for key in required_fields):
                logger.error(f"[定时任务] 群 {group_id} 缺少必要的配置字段，无法保存")
                return False

            from datetime import datetime
            now_iso = datetime.now().isoformat()
            if group_id_str not in self.schedule_data:
                 if "created_at" not in validated_data:
                     validated_data["created_at"] = now_iso
            validated_data["updated_at"] = now_iso

            self.schedule_data[group_id_str] = validated_data # type: ignore
            return self._save_json_data(self.schedule_data, self.schedule_file_path)
        except Exception as e:
            logger.error(f"[定时任务] 设置群 {group_id} 配置失败: {e}", e=e)
            return False

    def get(self, group_id: int) -> Optional[ScheduleData]:
        """获取指定群组的定时任务设置"""
        return self.schedule_data.get(str(group_id))

    def remove(self, group_id: int) -> bool:
        """移除指定群组的定时任务设置"""
        try:
            group_id_str = str(group_id)
            if group_id_str in self.schedule_data:
                del self.schedule_data[group_id_str]
                return self._save_json_data(self.schedule_data, self.schedule_file_path)
            return True # 不存在也算成功移除
        except Exception as e:
            logger.error(f"移除群 {group_id} 定时任务配置失败: {e}", e=e)
            return False

    def remove_all(self) -> bool:
        """移除所有群组的定时任务设置"""
        try:
            self.schedule_data.clear()
            return self._save_json_data(self.schedule_data, self.schedule_file_path)
        except Exception as e:
            logger.error(f"移除所有群组定时任务配置失败: {e}", e=e)
            return False

    def get_all_groups(self) -> list:
        """获取所有设置了定时任务的群组ID列表"""
        return list(self.schedule_data.keys())

    def cleanup_invalid_groups(self) -> int: # 只清理定时任务的无效群组
        """清理定时任务设置中的无效群组ID"""
        invalid_groups = [key for key in self.schedule_data if not key.isdigit()]
        if not invalid_groups:
            return 0

        cleaned_count = len(invalid_groups)
        for group_id in invalid_groups:
            del self.schedule_data[group_id]

        if self._save_json_data(self.schedule_data, self.schedule_file_path):
            logger.debug(f"自动清理了 {cleaned_count} 个无效的定时任务群配置")
        else:
            logger.error("清理无效定时任务群配置后保存失败")
        return cleaned_count

    # --- 新增分群配置相关方法 (操作 group_settings_data) ---
    def get_group_setting(self, group_id: str, key: str, default: Any = None) -> Any:
        """获取指定群组的特定设置项"""
        group_data = self.group_settings_data.get(group_id)
        if group_data and key in group_data:
            return group_data[key] # type: ignore
        return default

    def set_group_setting(self, group_id: str, key: str, value: Any) -> bool:
        """设置指定群组的特定设置项"""
        if not isinstance(group_id, str) or not group_id.isdigit():
             logger.warning(f"尝试为无效的 group_id '{group_id}' 设置分群配置")
             return False
        if key not in GroupSettingData.__annotations__: # 检查 key 是否有效
             logger.warning(f"尝试设置无效的分群配置项 '{key}' for group {group_id}")
             return False

        if group_id not in self.group_settings_data:
            self.group_settings_data[group_id] = {}

        from datetime import datetime
        now_iso = datetime.now().isoformat()
        self.group_settings_data[group_id][key] = value # type: ignore
        self.group_settings_data[group_id]["updated_at"] = now_iso # 更新时间戳

        return self._save_json_data(self.group_settings_data, self.group_settings_file_path)

    def remove_group_setting(self, group_id: str, key: str) -> bool:
        """移除指定群组的特定设置项"""
        if group_id in self.group_settings_data and key in self.group_settings_data[group_id]:
            del self.group_settings_data[group_id][key] # type: ignore
            # 如果移除后该群组没有其他设置了，可以选择移除整个群组条目
            if not self.group_settings_data[group_id] or (len(self.group_settings_data[group_id]) == 1 and "updated_at" in self.group_settings_data[group_id]):
                 del self.group_settings_data[group_id]
            else:
                 # 否则只更新时间戳
                 from datetime import datetime
                 now_iso = datetime.now().isoformat()
                 self.group_settings_data[group_id]["updated_at"] = now_iso

            return self._save_json_data(self.group_settings_data, self.group_settings_file_path)
        return True # 不存在也算成功移除

    def get_all_group_settings(self, group_id: str) -> Optional[GroupSettingData]:
         """获取指定群组的所有设置"""
         return self.group_settings_data.get(group_id)

    # --- 事务方法 (可以考虑是否需要对两个文件都加锁) ---
    async def transaction(self, operation_func):
        async with self._lock:
            # 需要同时备份 schedule_data 和 group_settings_data
            schedule_backup = copy.deepcopy(self.schedule_data)
            group_settings_backup = copy.deepcopy(self.group_settings_data)
            try:
                result = await operation_func() # 假设操作函数是异步的
                # 需要同时保存两个文件
                save1_ok = self._save_json_data(self.schedule_data, self.schedule_file_path)
                save2_ok = self._save_json_data(self.group_settings_data, self.group_settings_file_path)
                if not (save1_ok and save2_ok):
                    logger.error("事务操作中保存数据失败，回滚更改")
                    self.schedule_data = schedule_backup
                    self.group_settings_data = group_settings_backup
                    # 可能需要尝试恢复文件
                    return False
                return result # 返回操作结果
            except Exception as e:
                logger.error(f"事务操作失败，回滚更改: {e}", e=e)
                self.schedule_data = schedule_backup
                self.group_settings_data = group_settings_backup
                return False # 或者 re-raise e
