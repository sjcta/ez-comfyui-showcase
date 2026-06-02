from __future__ import annotations

from typing import Any


STANDARD_FIELDS = ("画面主题", "构图镜头", "空间关系", "主体描述", "光色材质")
EXPERT_FIELDS = ("基本概述", "主体类型", "构图镜头", "主体细节", "物体空间", "光影色彩风格")
EXPERT_TEAM_FIELDS = (
    "基本概述",
    "主体类型",
    "专家观点",
    "画面比例与主体占比",
    "主体细节",
    "人物外貌",
    "关节角度",
    "构图光色",
    "镜头倾斜角度",
    "物体背景",
)


def compact_two_level_dict(value: dict[str, Any]) -> dict[str, Any]:
    """Keep only dict/list/string leaves and avoid deep schema nesting in UI payloads."""
    result: dict[str, Any] = {}
    for key, item in value.items():
        if item in ("", None, [], {}):
            continue
        if isinstance(item, dict):
            flattened: list[str] = []
            for child_key, child_value in item.items():
                if child_value in ("", None, [], {}):
                    continue
                if isinstance(child_value, dict):
                    joined = "；".join(str(v) for v in child_value.values() if str(v).strip())
                    if joined:
                        flattened.append(f"{child_key}：{joined}")
                elif isinstance(child_value, list):
                    joined = "；".join(str(v) for v in child_value if str(v).strip())
                    if joined:
                        flattened.append(f"{child_key}：{joined}")
                else:
                    flattened.append(f"{child_key}：{child_value}")
            if flattened:
                result[str(key)] = "；".join(flattened)
        else:
            result[str(key)] = item
    return result
