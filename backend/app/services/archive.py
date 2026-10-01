"""档案管理业务规则：借阅状态分档、字段校验、缺项提示与筛选口径都收在这里。

台账与借阅窗口只能有一个数据口径：对外输出时「档案状态」一律以内部 status
为准，并按状态计算缺失项，避免同一份档案在不同窗口看到两样的归还日期。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "archive"
CREATE_FIELDS = ["档案编号", "所属设备", "档案类别"]
LIST_FIELDS = ["档案编号", "所属设备", "档案类别", "归档日期", "借阅人", "借阅日期", "归还日期", "档案状态"]

STATUS_IN_STOCK = "在库"
STATUS_BORROWED = "借出中"
STATUS_RETURNED = "已归还"
STATUS_DESTROYED = "已销毁"
STATUS_ORDER = [STATUS_IN_STOCK, STATUS_BORROWED, STATUS_RETURNED, STATUS_DESTROYED]

# 各借阅状态下必须填齐的字段；空着的会进「缺失项」一栏写明。
# 在库/已销毁不涉及借阅信息，空值是正常的，不报缺项。
MISSING_RULES: dict[str, list[str]] = {
    STATUS_BORROWED: ["借阅人", "借阅日期"],
    STATUS_RETURNED: ["借阅人", "借阅日期", "归还日期"],
}


def _today() -> str:
    return date.today().isoformat()


def _blank(value: Any) -> bool:
    return value is None or not str(value).strip()


class ArchiveService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        category: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            keyword = keyword.strip()
            rows = [row for row in rows if keyword in str(row.get("档案编号", ""))]
        if status:
            rows = [row for row in rows if str(row.get("status") or "") == status]
        if category:
            rows = [row for row in rows if str(row.get("档案类别") or "").strip() == category.strip()]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._serialize(row) for row in rows[start:start + size]], total

    def list_categories(self) -> list[str]:
        """类别下拉清单：去重、去空，按名称排序；一条档案都没有时返回空列表。"""
        categories = {
            str(row.get("档案类别") or "").strip()
            for row in store.rows(MODULE)
            if not _blank(row.get("档案类别"))
        }
        return sorted(categories)

    def status_stats(self) -> dict[str, int]:
        """各借阅状态分档计数，供前端页签与统计卡片共用。"""
        counts = {status: 0 for status in STATUS_ORDER}
        for row in store.rows(MODULE):
            status = str(row.get("status") or STATUS_IN_STOCK)
            counts[status] = counts.get(status, 0) + 1
        return counts

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._serialize(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in CREATE_FIELDS if _blank(values.get(field))]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in CREATE_FIELDS:
            entry[field] = values.get(field)
        entry["归档日期"] = str(values.get("归档日期") or "").strip() or _today()
        # 新登记档案在库，借阅三字段保持为空，杜绝占位日期残留。
        entry["借阅人"] = None
        entry["借阅日期"] = None
        entry["归还日期"] = None
        entry["status"] = STATUS_IN_STOCK
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"设备档案 {entry_id} 不存在或已归档"

        status = str(entry.get("status") or STATUS_IN_STOCK)
        if action == "办理借阅":
            if status == STATUS_BORROWED:
                return None, "该档案已借出，需先登记归还后才能再次借阅"
            if status == STATUS_DESTROYED:
                return None, "已销毁的档案不能再办理借阅"
            borrower = str(values.get("借阅人") or "").strip()
            if not borrower:
                return None, "办理借阅必须填写借阅人"
            entry["借阅人"] = borrower
            entry["借阅日期"] = str(values.get("借阅日期") or "").strip() or _today()
            # 重新借阅必须清空旧的归还日期，否则借出窗口会带出上一轮的日期。
            entry["归还日期"] = None
            entry["status"] = STATUS_BORROWED
            entry["pending"] = True
            entry["abnormal"] = False
        elif action == "登记归还":
            if status != STATUS_BORROWED:
                return None, "只有借出中的档案才能登记归还"
            returned_on = str(values.get("归还日期") or "").strip() or _today()
            entry["归还日期"] = returned_on
            # 归还后进入「已归还」档，自动挪出借阅窗口，而不是回到在库。
            entry["status"] = STATUS_RETURNED
            entry["pending"] = False
            entry["abnormal"] = False
        elif action == "申请销毁":
            if status not in (STATUS_IN_STOCK, STATUS_RETURNED):
                return None, "仅在库或已归还的档案可以申请销毁，借出中的档案需先追回"
            entry["status"] = STATUS_DESTROYED
            entry["pending"] = False
            entry["abnormal"] = False
        else:
            return None, f"动作「{action}」不属于档案管理可执行范围"

        return self._serialize(entry), f"设备档案已{action}"

    def _serialize(self, row: dict[str, Any]) -> dict[str, Any]:
        """统一输出口径：档案状态同步内部 status，并按状态算出缺了哪一项。"""
        item = dict(row)
        status = str(row.get("status") or STATUS_IN_STOCK)
        item["档案状态"] = status
        item["缺失项"] = [
            field
            for field in MISSING_RULES.get(status, [])
            if _blank(row.get(field))
        ]
        return item
