"""路由：配置 CRUD。

简化策略：UI 端可以直接 GET / PUT 整个 raw dict。
另外提供细粒度的 task / trigger / action CRUD 作为便捷端点（内部仍走整体 apply）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from anotiflow.core.config_store import ConfigStore


def make_router(config_store: ConfigStore) -> APIRouter:
    r = APIRouter(prefix="/api", tags=["config"])

    @r.get("/config")
    def get_config() -> dict[str, Any]:
        return config_store.current()

    @r.put("/config")
    def put_config(payload: dict = Body(...)) -> dict[str, Any]:
        try:
            config_store.apply(payload, source="ui")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return config_store.current()

    # ---- 细粒度便捷端点 ----
    @r.post("/tasks")
    def create_task(task: dict = Body(...)) -> dict[str, Any]:
        if not task.get("name"):
            raise HTTPException(status_code=400, detail="task.name required")
        cur = config_store.current()
        tasks = cur.setdefault("tasks", [])
        if any(t.get("name") == task["name"] for t in tasks):
            raise HTTPException(status_code=409, detail=f"task {task['name']!r} already exists")
        tasks.append(task)
        try:
            config_store.apply(cur, source="ui")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return config_store.current()

    @r.patch("/tasks/{name}")
    def patch_task(name: str, patch: dict = Body(...)) -> dict[str, Any]:
        cur = config_store.current()
        tasks = cur.get("tasks", []) or []
        for i, t in enumerate(tasks):
            if t.get("name") == name:
                merged = {**t, **patch}
                tasks[i] = merged
                break
        else:
            raise HTTPException(status_code=404, detail=f"task {name!r} not found")
        try:
            config_store.apply(cur, source="ui")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return config_store.current()

    @r.delete("/tasks/{name}")
    def delete_task(name: str) -> dict[str, Any]:
        cur = config_store.current()
        tasks = cur.get("tasks", []) or []
        new_tasks = [t for t in tasks if t.get("name") != name]
        if len(new_tasks) == len(tasks):
            raise HTTPException(status_code=404, detail=f"task {name!r} not found")
        cur["tasks"] = new_tasks
        try:
            config_store.apply(cur, source="ui")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return config_store.current()

    # ---- 分组级批量操作 ----
    # group_name == "default" 等价于"未设置 group 字段的任务"。
    @r.get("/groups")
    def list_groups() -> list[dict[str, Any]]:
        """返回所有出现过的分组及其任务摘要。"""
        cur = config_store.current()
        tasks = cur.get("tasks", []) or []
        agg: dict[str, list[dict]] = {}
        for t in tasks:
            g = t.get("group") or "default"
            agg.setdefault(g, []).append({
                "name": t.get("name"),
                "enabled": t.get("enabled", True) is not False,
            })
        return [
            {
                "name": g,
                "tasks": members,
                "count": len(members),
                "enabled_count": sum(1 for m in members if m["enabled"]),
            }
            for g, members in agg.items()
        ]

    @r.patch("/groups/{group_name}")
    def patch_group(group_name: str, patch: dict = Body(...)) -> dict[str, Any]:
        """对一组任务批量打补丁（典型用法 {"enabled": true|false}）。
        group_name == "default" 匹配未显式设置 group 字段的任务。
        """
        cur = config_store.current()
        tasks = cur.get("tasks", []) or []
        matched: list[str] = []
        for t in tasks:
            g = t.get("group") or "default"
            if g != group_name:
                continue
            for k, v in patch.items():
                t[k] = v
            matched.append(t.get("name", ""))
        if not matched:
            raise HTTPException(status_code=404, detail=f"group {group_name!r} matched no tasks")
        try:
            config_store.apply(cur, source="ui")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"matched": matched, "config": config_store.current()}

    return r
