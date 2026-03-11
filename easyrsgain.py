#!/usr/bin/env python3
import sys
import os
import re
from PyQt6.QtWidgets import (QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QHBoxLayout, QPushButton, QWidget, QSpinBox,
                             QHeaderView, QFileDialog, QProgressBar, QMessageBox, QLabel,
                             QComboBox, QTabWidget, QLineEdit, QFormLayout, QGroupBox)
from PyQt6.QtCore import Qt, QProcess
from PyQt6.QtGui import QIcon, QPixmap

# --- SOPORTE DE METADATOS ---
try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3, APIC
    from mutagen.flac import Picture
    from mutagen.mp4 import MP4Cover
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

class EasyRSGain2026(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EasyRSGain 2026 - Edición Definitiva")
        self.resize(1150, 780)

        # --- CORRECCIÓN DE ICONO (SISTEMA + LOCAL) ---
        # Definimos las rutas posibles para evitar el NameError
        icon_path_sys = "/usr/share/pixmaps/easyrsgain.png"
        icon_path_local = os.path.join(os.path.dirname(__file__), "1000230878.png")

        if os.path.exists(icon_path_sys):
            self.setWindowIcon(QIcon(icon_path_sys))
        elif os.path.exists(icon_path_local):
            self.setWindowIcon(QIcon(icon_path_local))
        elif os.path.exists("1000230878.png"):
            self.setWindowIcon(QIcon("1000230878.png"))

        self.queue = []
        self.current_row = -1
        self.file_paths = {}
        self.current_cover_data = None

        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self.handle_output)
        self.process.readyReadStandardError.connect(self.handle_output)
        self.process.finished.connect(self.process_finished_callback)

        self.initUI()

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #2b2b2b; color: #dcdcdc; font-family: 'Segoe UI', sans-serif; }
            QTabWidget::pane { border: 1px solid #444; top: -1px; }
            QTabBar::tab { background: #3c3f41; padding: 10px 20px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QTabBar::tab:selected { background: #2c3e50; color: #81d4fa; border: 1px solid #444; border-bottom-color: #2c3e50; }
            QTableWidget { background-color: #1e1e1e; color: #dcdcdc; gridline-color: #333333; border: none; }
            QHeaderView::section { background-color: #333333; color: #81d4fa; padding: 5px; border: 1px solid #111; }
            QPushButton { background-color: #3c3f41; color: white; border: 1px solid #555; padding: 8px; border-radius: 3px; }
            QPushButton:hover { background-color: #4b4e50; }
            QLineEdit { background-color: #1e1e1e; color: white; border: 1px solid #555; padding: 5px; }
            QGroupBox { border: 1px solid #555; border-radius: 5px; margin-top: 10px; padding-top: 15px; color: #81d4fa; font-weight: bold; }
            #CoverLabel { background-color: #151515; border: 2px dashed #444; border-radius: 5px; }
        """)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Pestaña 1
        self.tab_gain = QWidget()
        self.setup_gain_tab()
        self.tabs.addTab(self.tab_gain, "Normalización LUFS")

        # Pestaña 2
        self.tab_tags = QWidget()
        self.setup_tags_tab()
        self.tabs.addTab(self.tab_tags, "Editor Maestro de Álbumes")

    def setup_gain_tab(self):
        layout = QVBoxLayout(self.tab_gain)
        top = QHBoxLayout()
        top.addWidget(QLabel("Objetivo:"))
        self.target_vol = QSpinBox()
        self.target_vol.setRange(-30, -5); self.target_vol.setValue(-18); self.target_vol.setSuffix(" LUFS")
        top.addWidget(self.target_vol)
        top.addSpacing(20)
        top.addWidget(QLabel("Modo:"))
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["Track (Archivo)", "Album (Carpeta)"])
        top.addWidget(self.mode_selector)
        top.addStretch()
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Archivo", "Volumen Actual", "Ajuste", "Estado", "Progreso"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        btns = QHBoxLayout()
        btn_add = QPushButton("➕ Añadir Música"); btn_add.clicked.connect(self.add_files)
        btn_clear = QPushButton("🗑️ Limpiar Todo"); btn_clear.clicked.connect(self.clear_all)
        btns.addWidget(btn_add); btns.addWidget(btn_clear)
        layout.addLayout(btns)

        actions = QHBoxLayout()
        btn_scan = QPushButton("🔍 ANALIZAR SELECCIONADOS")
        btn_scan.setFixedHeight(45); btn_scan.setStyleSheet("background-color: #2c3e50; color: #81d4fa;")
        btn_scan.clicked.connect(lambda: self.start_batch("scan"))
        btn_apply = QPushButton("🚀 NORMALIZAR SELECCIONADOS")
        btn_apply.setFixedHeight(45); btn_apply.setStyleSheet("background-color: #0d47a1; font-weight: bold;")
        btn_apply.clicked.connect(lambda: self.start_batch("apply"))
        actions.addWidget(btn_scan); actions.addWidget(btn_apply)
        layout.addLayout(actions)

    def setup_tags_tab(self):
        layout = QHBoxLayout(self.tab_tags)

        # Lista izquierda
        self.tag_list = QTableWidget(0, 1)
        self.tag_list.setHorizontalHeaderLabels(["Listado de Archivos"])
        self.tag_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tag_list.itemSelectionChanged.connect(self.load_tags_to_editor)
        layout.addWidget(self.tag_list, 1)

        # Editor derecha
        editor_layout = QVBoxLayout()

        # Grupo Portada
        group_cover = QGroupBox("Carátula del Álbum")
        cover_h = QHBoxLayout(group_cover)
        self.cover_label = QLabel("Sin Portada")
        self.cover_label.setObjectName("CoverLabel")
        self.cover_label.setFixedSize(180, 180)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_h.addWidget(self.cover_label)

        c_btns = QVBoxLayout()
        btn_load_c = QPushButton("🖼️ Elegir Imagen"); btn_load_c.clicked.connect(self.choose_cover)
        btn_mass_c = QPushButton("⚡ Pegar en TODO"); btn_mass_c.clicked.connect(self.mass_cover_save)
        c_btns.addWidget(btn_load_c); c_btns.addWidget(btn_mass_c); c_btns.addStretch()
        cover_h.addLayout(c_btns)
        editor_layout.addWidget(group_cover)

        # Grupo Tags
        group_info = QGroupBox("Datos Comunes")
        form = QFormLayout(group_info)
        self.edit_artist = QLineEdit(); self.edit_album = QLineEdit(); self.edit_year = QLineEdit()
        form.addRow("Artista:", self.edit_artist)
        form.addRow("Álbum:", self.edit_album)
        form.addRow("Año:", self.edit_year)
        editor_layout.addWidget(group_info)

        btn_mass_tag = QPushButton("🔥 APLICAR DATOS A TODO EL LISTADO")
        btn_mass_tag.setFixedHeight(50); btn_mass_tag.setStyleSheet("background-color: #b71c1c; font-weight: bold;")
        btn_mass_tag.clicked.connect(self.mass_tag_save)
        editor_layout.addWidget(btn_mass_tag)

        layout.addLayout(editor_layout, 1)

    # --- LÓGICA GENERAL ---
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Seleccionar Música", "", "Audio (*.mp3 *.flac *.m4a)")
        for f_path in sorted(files):
            row = self.table.rowCount()
            self.table.insertRow(row); self.file_paths[row] = f_path
            self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(f_path)))
            self.table.setItem(row, 3, QTableWidgetItem("Listo"))
            prog = QProgressBar(); prog.setValue(0); prog.setTextVisible(False); prog.setFixedHeight(10)
            self.table.setCellWidget(row, 4, prog)

            tag_row = self.tag_list.rowCount(); self.tag_list.insertRow(tag_row)
            item = QTableWidgetItem(os.path.basename(f_path)); item.setData(Qt.ItemDataRole.UserRole, f_path)
            self.tag_list.setItem(tag_row, 0, item)

    def clear_all(self):
        self.table.setRowCount(0); self.tag_list.setRowCount(0); self.file_paths = {}

    def load_tags_to_editor(self):
        selected = self.tag_list.selectedItems()
        if not selected: return
        path = selected[0].data(Qt.ItemDataRole.UserRole)
        try:
            audio = MutagenFile(path, easy=True)
            self.edit_artist.setText(audio.get('artist', [''])[0])
            self.edit_album.setText(audio.get('album', [''])[0])
            self.edit_year.setText(audio.get('date', [''])[0])
        except: pass

    def choose_cover(self):
        file, _ = QFileDialog.getOpenFileName(self, "Elegir Portada", "", "Imágenes (*.jpg *.png)")
        if file:
            with open(file, 'rb') as f: self.current_cover_data = f.read()
            pix = QPixmap(); pix.loadFromData(self.current_cover_data)
            self.cover_label.setPixmap(pix.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio))

    def mass_tag_save(self):
        for i in range(self.tag_list.rowCount()):
            path = self.tag_list.item(i, 0).data(Qt.ItemDataRole.UserRole)
            try:
                a = MutagenFile(path, easy=True)
                a['artist'] = self.edit_artist.text(); a['album'] = self.edit_album.text(); a['date'] = self.edit_year.text()
                a.save()
            except: pass
        QMessageBox.information(self, "Éxito", "Tags actualizados en todo el álbum.")

    def mass_cover_save(self):
        if not self.current_cover_data: return
        for i in range(self.tag_list.rowCount()):
            path = self.tag_list.item(i, 0).data(Qt.ItemDataRole.UserRole)
            try:
                a = MutagenFile(path)
                if path.lower().endswith('.mp3'):
                    a.tags.delall("APIC")
                    a.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=self.current_cover_data))
                elif path.lower().endswith('.flac'):
                    a.clear_pictures()
                    p = Picture(); p.data = self.current_cover_data; p.type = 3; p.mime = "image/jpeg"
                    a.add_picture(p)
                a.save()
            except: pass
        QMessageBox.information(self, "Éxito", "Portada aplicada a todo el listado.")

    def start_batch(self, mode):
        if self.current_row != -1: return
        self.current_mode = mode
        self.queue = list(range(self.table.rowCount()))
        self.process_next_in_queue()

    def process_next_in_queue(self):
        if not self.queue:
            self.current_row = -1; QMessageBox.information(self, "EasyRSGain", "Proceso finalizado."); return
        self.current_row = self.queue.pop(0)
        p = self.file_paths.get(self.current_row)
        args = ["custom", "-p", "-l", str(self.target_vol.value()), p] if self.current_mode == "scan" else ["easy", "-m", "track", "-l", str(self.target_vol.value()), p]
        self.table.setItem(self.current_row, 3, QTableWidgetItem("Procesando..."))
        self.process.start("rsgain", args)

    def handle_output(self):
        out = self.process.readAllStandardOutput().data().decode(errors='replace')
        nums = re.findall(r"[-+]?\d+\.\d+", out)
        if nums:
            self.table.setItem(self.current_row, 1, QTableWidgetItem(f"{nums[0]} LUFS"))
            if len(nums) >= 2: self.table.setItem(self.current_row, 2, QTableWidgetItem(f"{nums[1]} dB"))

    def process_finished_callback(self):
        if self.current_row != -1:
            self.table.setItem(self.current_row, 3, QTableWidgetItem("✅ Hecho"))
            self.table.cellWidget(self.current_row, 4).setValue(100)
        self.process_next_in_queue()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = EasyRSGain2026(); window.show()
    sys.exit(app.exec())
