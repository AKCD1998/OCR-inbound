"""Thin PySide6/QTableView spike using the shared 120-row workload.

Exits 3 with a measurable dependency result when PySide6 is unavailable; it does not install Qt.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main() -> int:
    fixture = json.loads((Path(__file__).parents[1] / "shared_fixture.json").read_text(encoding="utf-8"))
    started = time.perf_counter()
    try:
        from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
        from PySide6.QtWidgets import QApplication, QTableView
    except ImportError as exc:
        print(json.dumps({"stack": "PySide6", "status": "dependency_unavailable", "line_count": fixture["line_count"], "error": type(exc).__name__}))
        return 3

    class Model(QAbstractTableModel):
        def rowCount(self, parent=QModelIndex()):  # noqa: N802
            return fixture["line_count"]

        def columnCount(self, parent=QModelIndex()):  # noqa: N802
            return 8

        def data(self, index, role=Qt.DisplayRole):  # noqa: N802
            if role != Qt.DisplayRole:
                return None
            values = [index.row() + 1, f"630{index.row()+1:04d}", fixture["line_template"]["description"], "BOX", "12", "35.50", "426.00", "ต้องตรวจ"]
            return str(values[index.column()])

    app = QApplication(sys.argv)
    table = QTableView()
    table.setModel(Model())
    table.resize(1200, 720)
    table.show()
    app.processEvents()
    print(json.dumps({"stack": "PySide6", "status": "rendered", "line_count": fixture["line_count"], "startup_ms": round((time.perf_counter() - started) * 1000, 2)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
