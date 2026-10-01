"""档案管理接口：维护设备档案，覆盖办理借阅、登记归还、申请销毁等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.archive import LEDGER_STATUSES, ArchiveService

router = APIRouter(prefix="/api/archive", tags=["档案管理"])

service = ArchiveService()

LIST_FIELDS = ["档案编号", "所属设备", "档案类别", "归档日期", "借阅人", "借阅日期", "归还日期", "缺失项", "档案状态"]
STATUSES = ["在库", "借出中", "已归还", "已销毁"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按档案编号检索"),
    category: str | None = Query(default=None, description="按档案类别精确过滤"),
    status: str | None = Query(default=None, description="在库、借出中、已归还、已销毁"),
    page: int = 1,
    size: int = 200,
) -> PageResult[dict]:
    """按档案编号、档案类别与借阅状态过滤档案列表；没有数据时返回空页，不报错。

    档案数量有限，默认一页取全量，分页在前端内存里做，保证锁定行不会换页跳走。
    """
    if size > 1000:
        raise HTTPException(status_code=400, detail="每页最多 1000 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, category=category, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/categories")
def list_categories() -> dict[str, Any]:
    """类别清单：供筛选下拉定位；取不到时前端会再请求一次重新定位。"""
    return {"items": service.list_categories()}


@router.get("/stats")
def status_stats() -> dict[str, Any]:
    """分档数量：在库、借出中、已归还三张卡片。"""
    return {"items": [{"status": status, "count": count} for status, count in service.status_stats().items()]}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出档案管理清单：与列表同一套口径，缺失项列一并导出。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "archive", "statuses": LEDGER_STATUSES, "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条设备档案明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"设备档案 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条设备档案，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="设备档案已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条设备档案执行办理借阅、登记归还、申请销毁；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
