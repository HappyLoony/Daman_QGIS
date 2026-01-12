# -*- coding: utf-8 -*-
"""
Диалог прогресса для инструмента 0_5_Графика к запросу
"""

import os
import subprocess
import sys
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QProgressBar, 
    QLabel, QPushButton, QDialogButtonBox
)


class GraphicsProgressDialog(QDialog):
    """Минималистичный диалог отображения прогресса"""
    
    def __init__(self, parent=None):
        """Инициализация диалога прогресса"""
        super().__init__(parent)
        self.setWindowTitle("Создание графики к запросу")
        self.setModal(True)
        self.setFixedSize(400, 150)
        
        # Путь к результату (заполняется при успехе)
        self.result_folder = None
        
        # Создаем layout
        layout = QVBoxLayout()
        
        # Метка состояния
        self.status_label = QLabel("Инициализация...")
        layout.addWidget(self.status_label)
        
        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # Кнопка открытия папки (скрыта изначально)
        self.open_folder_button = QPushButton("Открыть папку с результатом")
        self.open_folder_button.clicked.connect(self.open_result_folder)
        self.open_folder_button.setVisible(False)
        layout.addWidget(self.open_folder_button)
        
        # Кнопки диалога
        self.button_box = QDialogButtonBox()
        self.close_button = self.button_box.addButton(
            QDialogButtonBox.Close
        )
        self.close_button.setEnabled(False)  # Отключена до завершения
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
        self.setLayout(layout)
    
    def update_progress(self, value, status_text):
        """Обновление прогресса и текста состояния
        
        Args:
            value: Значение прогресса (0-100)
            status_text: Текст состояния
        """
        self.progress_bar.setValue(value)
        self.status_label.setText(status_text)
        
        # Если достигли 100% - показываем успех
        if value >= 100:
            self.status_label.setText("✓ Успех!")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            if self.result_folder:
                self.open_folder_button.setVisible(True)
            self.close_button.setEnabled(True)
    
    def set_result_folder(self, folder_path):
        """Установка пути к папке с результатами
        
        Args:
            folder_path: Путь к папке с результатами
        """
        self.result_folder = folder_path
    
    def open_result_folder(self):
        """Открытие папки с результатами в проводнике"""
        if self.result_folder and os.path.exists(self.result_folder):
            if sys.platform == 'win32':
                os.startfile(self.result_folder)
            elif sys.platform == 'darwin':
                subprocess.run(['open', self.result_folder])
            else:
                subprocess.run(['xdg-open', self.result_folder])
    
    def enable_close(self):
        """Включение кнопки закрытия (при ошибке)"""
        self.close_button.setEnabled(True)
