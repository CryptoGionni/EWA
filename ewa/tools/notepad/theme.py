"""QSS del Blocco note: tema chiaro (Win10) e tema scuro (modalità Dark)."""

LIGHT = dict(
    editor_bg="#FFFFFF", editor_fg="#000000", bar_bg="#FFFFFF", bar_fg="#000000",
    bar_hover="#E5F3FF", bar_press="#CCE8FF", menu_bg="#F2F2F2", menu_border="#CCCCCC",
    menu_hover="#91C9F7", menu_fg="#000000", menu_disabled="#8E8E8E", sep="#D7D7D7",
    status_bg="#F0F0F0", status_sep="#D8D8D8", selection="#0078D7", selection_fg="#FFFFFF",
    dlg_bg="#F0F0F0", dlg_fg="#000000", field_bg="#FFFFFF", field_border="#7A7A7A",
    btn_bg="#E1E1E1", btn_border="#ADADAD", btn_hover_bg="#E5F1FB", btn_hover_border="#0078D7",
    sb_track="#F0F0F0", sb_handle="#CDCDCD", sb_handle_hover="#A6A6A6",
)
DARK = dict(
    editor_bg="#1E1E1E", editor_fg="#D4D4D4", bar_bg="#2D2D30", bar_fg="#D4D4D4",
    bar_hover="#3E3E42", bar_press="#505055", menu_bg="#252526", menu_border="#454545",
    menu_hover="#094771", menu_fg="#D4D4D4", menu_disabled="#6E6E6E", sep="#454545",
    status_bg="#252526", status_sep="#454545", selection="#264F78", selection_fg="#FFFFFF",
    dlg_bg="#2D2D30", dlg_fg="#D4D4D4", field_bg="#1E1E1E", field_border="#555555",
    btn_bg="#3C3C3C", btn_border="#555555", btn_hover_bg="#4A4A4F", btn_hover_border="#007ACC",
    sb_track="#1E1E1E", sb_handle="#424242", sb_handle_hover="#686868",
)
MARV_COLOR = "#9CDCFE"


def build_qss(dark: bool) -> str:
    c = DARK if dark else LIGHT
    status_fg = "#D4D4D4" if dark else "#000000"
    return f"""
    QMainWindow {{ background: {c['editor_bg']}; }}
    QPlainTextEdit#Editor {{ background: {c['editor_bg']}; color: {c['editor_fg']}; border: none;
        selection-background-color: {c['selection']}; selection-color: {c['selection_fg']}; }}
    QMenuBar {{ background: {c['bar_bg']}; color: {c['bar_fg']}; padding: 0; spacing: 0; }}
    QMenuBar::item {{ background: transparent; padding: 4px 8px; margin: 0; }}
    QMenuBar::item:selected {{ background: {c['bar_hover']}; }}
    QMenuBar::item:pressed {{ background: {c['bar_press']}; }}
    QMenu {{ background: {c['menu_bg']}; color: {c['menu_fg']}; border: 1px solid {c['menu_border']};
        padding: 2px 0; }}
    QMenu::item {{ padding: 4px 28px 4px 30px; background: transparent; }}
    QMenu::item:selected {{ background: {c['menu_hover']}; color: {c['menu_fg']}; }}
    QMenu::item:disabled {{ color: {c['menu_disabled']}; background: transparent; }}
    QMenu::separator {{ height: 1px; background: {c['sep']}; margin: 3px 1px 3px 28px; }}
    QMenu::indicator {{ left: 8px; width: 14px; height: 14px; }}
    QStatusBar {{ background: {c['status_bg']}; color: {status_fg}; min-height: 22px; }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QLabel {{ color: {status_fg}; padding: 0 8px; border-left: 1px solid {c['status_sep']}; }}
    QScrollBar:vertical {{ background: {c['sb_track']}; width: 17px; margin: 0; }}
    QScrollBar:horizontal {{ background: {c['sb_track']}; height: 17px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {c['sb_handle']}; min-height: 24px; margin: 0 3px; }}
    QScrollBar::handle:horizontal {{ background: {c['sb_handle']}; min-width: 24px; margin: 3px 0; }}
    QScrollBar::handle:hover {{ background: {c['sb_handle_hover']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QDialog, QMessageBox {{ background: {c['dlg_bg']}; color: {c['dlg_fg']}; }}
    QDialog QLabel, QMessageBox QLabel {{ color: {c['dlg_fg']}; background: transparent; }}
    QCheckBox, QRadioButton, QGroupBox {{ color: {c['dlg_fg']}; }}
    QLineEdit {{ background: {c['field_bg']}; color: {c['dlg_fg']}; border: 1px solid {c['field_border']};
        padding: 2px 3px; selection-background-color: {c['selection']}; selection-color: #FFFFFF; }}
    QLineEdit:focus {{ border: 1px solid #0078D7; }}
    QGroupBox {{ border: 1px solid {c['btn_border']}; margin-top: 8px; padding: 6px 4px 2px 4px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 2px; }}
    QDialog QPushButton, QMessageBox QPushButton {{ background: {c['btn_bg']};
        color: {c['dlg_fg']}; border: 1px solid {c['btn_border']}; padding: 3px 12px; min-width: 70px; }}
    QDialog QPushButton:hover, QMessageBox QPushButton:hover {{ background: {c['btn_hover_bg']};
        border: 1px solid {c['btn_hover_border']}; }}
    QDialog QPushButton:default, QMessageBox QPushButton:default {{ border: 1px solid #0078D7; }}
    QDialog QPushButton:disabled {{ color: {c['menu_disabled']}; }}
    """
