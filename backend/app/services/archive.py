"""档案管理业务规则：状态流转、字段校验与筛选口径都收在这里。

台账列表与借阅窗口共用同一份数据：借阅人、借阅日期、归还日期只在这里写入，
前端不再各自推算，避免两边归还日期对不上。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "archive"
REQUIRED_FIELDS = ["档案编号", "所属设备", "档案类别"]
# 借阅分档只认三档；已销毁档案留在历史分档里单独处理。
LEDGER_STATUSES = ["在库", "借出中", "已归还"]
STATUS_ORDER = ["在库", "借出中", "已归还", "已销毁"]
# 各分档下列表展示的列，归还日期为空时由「缺失项」列点明少了哪一项。
BORROW_FIELDS = ["借阅人", "借阅日期"]
RETURN_FIELDS = ["借阅人", "借阅日期", "归还日期"]


def _is_blank(value: Any) -> bool:
    return value is None or not str(value).strip()


def _missing_fields(row: dict[str, Any]) -> list[str]:
    """按当前借阅状态判断少了哪一项；台账与借阅窗口都按这个口径提示。"""
    status = row.get("status")
    if status == "借出中":
        return [field for field in BORROW_FIELDS if _is_blank(row.get(field))]
    if status == "已归还":
        return [field for field in RETURN_FIELDS if _is_blank(row.get(field))]
    return []


def decorate(row: dict[str, Any]) -> dict[str, Any]:
    """补出展示字段：档案状态与内部状态同源，缺失项只派生不入库。"""
    view = dict(row)
    view["档案状态"] = row.get("status")
    missing = _missing_fields(row)
    view["缺失项"] = "、".join(f"缺{field}" for field in missing)
    view["has_missing"] = bool(missing)
    return view


class ArchiveService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        category: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("档案编号", ""))]
        if category:
            rows = [row for row in rows if str(row.get("档案类别", "")) == category]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [decorate(row) for row in rows[start:start + size]], total

    def list_categories(self) -> list[str]:
        """类别清单：去重并保持首次出现顺序，供筛选下拉定位。"""
        seen: set[str] = set()
        categories: list[str] = []
        for row in store.rows(MODULE):
            name = str(row.get("档案类别") or "").strip()
            if name and name not in seen:
                seen.add(name)
                categories.append(name)
        return categories

    def status_stats(self) -> dict[str, int]:
        """在库/借出中/已归还各档数量，看板卡片与列表同源。"""
        counts = {status: 0 for status in LEDGER_STATUSES}
        for row in store.rows(MODULE):
            status = str(row.get("status") or "")
            if status in counts:
                counts[status] += 1
        return counts

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return decorate(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["归档日期"] = values.get("归档日期")
        entry["借阅人"] = None
        entry["借阅日期"] = None
        entry["归还日期"] = None
        entry["status"] = "在库"
        entry["pending"] = False
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"设备档案 {entry_id} 不存在或已归档"
        status = entry.get("status")
        today = date.today().isoformat()

        if action == "办理借阅":
            if status == "借出中":
                return None, "该档案已借出，尚未归还，不能重复借阅"
            if status == "已销毁":
                return None, "已销毁档案不能再借阅"
            borrower = str(values.get("借阅人") or "").strip()
            if not borrower:
                return None, "办理借阅必须登记借阅人"
            borrow_date = str(values.get("借阅日期") or "").strip() or today
            entry["status"] = "借出中"
            entry["借阅人"] = borrower
            entry["借阅日期"] = borrow_date
            entry["归还日期"] = None
        elif action == "登记归还":
            if status != "借出中":
                return None, "只有借出中的档案可以登记归还"
            entry["status"] = "已归还"
            entry["归还日期"] = str(values.get("归还日期") or "").strip() or today
        elif action == "申请销毁":
            if status == "已销毁":
                return None, "该档案已销毁，无需重复申请"
            entry["status"] = "已销毁"
        else:
            return None, f"动作「{action}」不属于档案管理可执行范围"

        entry["pending"] = entry["status"] == "借出中"
        entry["abnormal"] = bool(_missing_fields(entry))
        return entry, f"设备档案已{action}"
