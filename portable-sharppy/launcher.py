"""Portable BTV-branded SHARPpy launcher (native Qt styling)."""
from __future__ import annotations
import os, shutil, sys
from pathlib import Path

def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent

def install_btv_data_sources() -> None:
    source = bundle_root() / "native-sharppy"
    destination = Path(os.environ.get("APPDATA", Path.home())) / ".sharppy" / "datasources"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("btv_cwa_latest.xml", "btv_cwa.csv", "btv_observed.csv"):
        src = source / name
        if not src.is_file():
            raise FileNotFoundError(f"Bundled BTV data-source file is missing: {src}")
        shutil.copy2(src, destination / name)

def configure_btv_qt():
    os.environ.setdefault("QT_API", "pyside2")
    from qtpy.QtWidgets import QApplication
    from qtpy.QtGui import QPalette, QColor, QFont
    from qtpy.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("BTV NSHARP")
    app.setApplicationDisplayName("BTV NSHARP · Mesoscale Detective")
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#080d12"))
    palette.setColor(QPalette.WindowText, QColor("#e6edf5"))
    palette.setColor(QPalette.Base, QColor("#05090d"))
    palette.setColor(QPalette.AlternateBase, QColor("#101820"))
    palette.setColor(QPalette.ToolTipBase, QColor("#101820"))
    palette.setColor(QPalette.ToolTipText, QColor("#e6edf5"))
    palette.setColor(QPalette.Text, QColor("#e6edf5"))
    palette.setColor(QPalette.Button, QColor("#13202b"))
    palette.setColor(QPalette.ButtonText, QColor("#e6edf5"))
    palette.setColor(QPalette.Highlight, QColor("#087c91"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#6b7885"))
    app.setPalette(palette)
    app.setFont(QFont("Segoe UI", 9))
    app.setStyleSheet("""
        QMainWindow, QWidget { background:#080d12; color:#e6edf5; }
        QMenuBar { background:#071018; border-bottom:1px solid #344858; }
        QMenuBar::item { padding:5px 9px; }
        QMenu { background:#101a23; border:1px solid #3d596a; }
        QMenu::item:selected { background:#126d80; }
        QToolBar { background:#071018; border-bottom:1px solid #304654; spacing:5px; }
        QToolButton, QPushButton { background:#13202b; color:#e6edf5; border:1px solid #3d596a; padding:4px 7px; }
        QToolButton:hover, QPushButton:hover { border-color:#45d5ee; background:#193140; }
        QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { background:#05090d; color:#e6edf5; border:1px solid #3d596a; padding:3px; }
        QComboBox QAbstractItemView { background:#101a23; color:#e6edf5; selection-background-color:#126d80; }
        QTabWidget::pane { border:1px solid #3d596a; }
        QTabBar::tab { background:#101a23; color:#9fb5c5; padding:5px 9px; border:1px solid #334856; }
        QTabBar::tab:selected { color:#45d5ee; background:#132733; }
        QTableView, QTableWidget, QTreeView, QListView { background:#05090d; alternate-background-color:#101820; gridline-color:#2b3b49; }
        QHeaderView::section { background:#101a23; color:#9fb5c5; border:1px solid #2b3b49; padding:3px; }
        QGroupBox { border:1px solid #3d596a; margin-top:8px; padding-top:5px; }
        QGroupBox::title { color:#45d5ee; subcontrol-origin:margin; left:7px; }
        QStatusBar { background:#071018; border-top:1px solid #344858; }
        QScrollBar:vertical { background:#080d12; width:12px; }
        QScrollBar::handle:vertical { background:#314b5d; min-height:20px; }
    """)
    return app

def smoke_test() -> int:
    # This is run against the frozen executable in CI to catch missing DLLs.
    import numpy
    import sharppy
    import runsharp.full_gui
    import sharppy.viz.SPCWindow as spc_module
    import certifi
    from PySide2 import QtCore
    # Verify the private UI hooks used by the branding layer exist in this SHARPpy build.
    assert hasattr(runsharp.full_gui.Main, "_Main__initUI"), "SHARPpy Main UI hook missing"
    assert hasattr(spc_module.SPCWindow, "_SPCWindow__initUI"), "SHARPpy SPCWindow UI hook missing"
    assert os.path.isfile(certifi.where()), "Bundled CA certificate file missing"
    print(f"Frozen import/UI-hook/certifi smoke test OK: NumPy {numpy.__version__}; Qt {QtCore.__version__}")
    return 0

def main() -> int:
    if "--smoke-test" in sys.argv:
        return smoke_test()
    install_btv_data_sources()
    app = configure_btv_qt()
    import runsharp.full_gui as full_gui
    # SHARPpy's release checker is not operationally required and can crash a
    # frozen app when TLS certificates or network access are unavailable.
    full_gui.check_latest = lambda: (True, None)
    original_init_ui = full_gui.Main._Main__initUI
    def branded_init_ui(self):
        original_init_ui(self)
        self.setWindowTitle("BTV NSHARP · Sounding Workstation")
    full_gui.Main._Main__initUI = branded_init_ui
    import importlib
    spc_module = importlib.import_module("sharppy.viz.SPCWindow")
    original_spc_ui = spc_module.SPCWindow._SPCWindow__initUI
    def branded_analysis_ui(self, **kwargs):
        original_spc_ui(self, **kwargs)
        self.setWindowTitle("BTV NSHARP  |  SOUNDING ANALYSIS")
        self.setGeometry(30, 30, 1500, 960)
        for action in self.menuBar().actions():
            if action.text().strip().lower() == "profiles":
                action.setVisible(False)
        self.statusBar().showMessage("BTV NSHARP · SHARPpy diagnostics · sounding workstation")
    spc_module.SPCWindow._SPCWindow__initUI = branded_analysis_ui
    full_gui.main()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
