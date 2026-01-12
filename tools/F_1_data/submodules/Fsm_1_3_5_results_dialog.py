# -*- coding: utf-8 -*-
"""
Диалог отображения результатов выборки для бюджета
"""

import os
from datetime import datetime
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit,
    QGroupBox, QMessageBox
)
from qgis.core import QgsMessageLog, Qgis


class BudgetSelectionResultsDialog(QDialog):
    """Диалог с результатами выборки"""
    
    def __init__(self, parent, results, temp_folder):
        """Инициализация диалога
        
        Args:
            parent: Родительское окно
            results: Словарь с результатами анализа
            temp_folder: Папка для сохранения результатов
        """
        super().__init__(parent)
        self.results = results
        self.temp_folder = temp_folder
        
        self.setWindowTitle("Выборка для бюджета - Результаты")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        
        self.init_ui()
    
    def init_ui(self):
        """Создание интерфейса"""
        
        layout = QVBoxLayout()
        
        # Заголовок
        title_label = QLabel("Результаты выборки для бюджета")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # Группа с результатами
        results_group = QGroupBox("Результаты анализа")
        results_layout = QVBoxLayout()
        
        # 1. Кадастровые кварталы
        cadastral_label = QLabel(
            f"1. Кадастровые кварталы: {self.results['cadastral_quarters']}"
        )
        cadastral_label.setStyleSheet("padding: 5px;")
        results_layout.addWidget(cadastral_label)
        
        # 2. Земельные участки
        land_label = QLabel(
            f"2. Земельные участки: {self.results['land_plots']}"
        )
        land_label.setStyleSheet("padding: 5px;")
        results_layout.addWidget(land_label)

        # 2.1. в том числе ЗУ в лесном фонде (показываем всегда, даже если 0)
        forest_fund_count = self.results.get('land_plots_forest_fund', 0)
        forest_fund_label = QLabel(
            f"   в том числе ЗУ в лесном фонде: {forest_fund_count}"
        )
        # Зелёный цвет если есть ЗУ в лесном фонде, серый если 0
        if forest_fund_count > 0:
            forest_fund_label.setStyleSheet("padding: 5px; padding-left: 20px; color: #2E7D32;")
        else:
            forest_fund_label.setStyleSheet("padding: 5px; padding-left: 20px; color: gray;")
        results_layout.addWidget(forest_fund_label)

        # 3. Объекты капитального строительства
        capital_label = QLabel(
            f"3. Объекты капитального строительства: {self.results['capital_objects']}"
        )
        capital_label.setStyleSheet("padding: 5px;")
        results_layout.addWidget(capital_label)
        
        # 4. Населенные пункты
        settlements_label = QLabel("4. Населенные пункты:")
        settlements_label.setStyleSheet("padding: 5px;")
        results_layout.addWidget(settlements_label)
        
        # Список населенных пунктов
        if self.results['settlements']:
            settlements_text = QTextEdit()
            settlements_text.setReadOnly(True)
            settlements_text.setMaximumHeight(100)

            # Показываем максимум 5, остальное - ссылка на txt
            settlements_list = self.results['settlements']
            display_text = ""

            for i, settlement in enumerate(settlements_list[:5]):
                display_text += f"   - {settlement}\n"

            if len(settlements_list) > 5:
                display_text += f"   ... и еще {len(settlements_list) - 5} (Подробнее в txt)"

            settlements_text.setPlainText(display_text)
            results_layout.addWidget(settlements_text)
        else:
            no_settlements_label = QLabel("   - Нет данных")
            no_settlements_label.setStyleSheet("padding-left: 20px; color: gray;")
            results_layout.addWidget(no_settlements_label)

        # 5. Муниципальные образования
        municipal_label = QLabel("5. Муниципальные образования:")
        municipal_label.setStyleSheet("padding: 5px;")
        results_layout.addWidget(municipal_label)

        # Список муниципальных образований
        if self.results.get('municipal_districts'):
            municipal_text = QTextEdit()
            municipal_text.setReadOnly(True)
            municipal_text.setMaximumHeight(100)

            # Показываем максимум 5, остальное - ссылка на txt
            municipal_list = self.results['municipal_districts']
            display_text = ""

            for i, district in enumerate(municipal_list[:5]):
                display_text += f"   - {district}\n"

            if len(municipal_list) > 5:
                display_text += f"   ... и еще {len(municipal_list) - 5} (Подробнее в txt)"

            municipal_text.setPlainText(display_text)
            results_layout.addWidget(municipal_text)
        else:
            no_municipal_label = QLabel("   - Нет данных")
            no_municipal_label.setStyleSheet("padding-left: 20px; color: gray;")
            results_layout.addWidget(no_municipal_label)

        # 6. ООПТ (особо охраняемые природные территории)
        oopt_header_layout = QHBoxLayout()
        oopt_label = QLabel("6. ООПТ:")
        oopt_label.setStyleSheet("padding: 5px;")
        oopt_header_layout.addWidget(oopt_label)

        # Серая приписка (ООПТ=ЛЕС)
        oopt_hint_label = QLabel("(ООПТ=ЛЕС)")
        oopt_hint_label.setStyleSheet("padding: 5px; color: gray;")
        oopt_header_layout.addWidget(oopt_hint_label)
        oopt_header_layout.addStretch()
        results_layout.addLayout(oopt_header_layout)

        # Список ООПТ
        if self.results.get('oopt'):
            oopt_text = QTextEdit()
            oopt_text.setReadOnly(True)
            oopt_text.setMaximumHeight(100)

            # Показываем максимум 5, остальное - ссылка на txt
            oopt_list = self.results['oopt']
            display_text = ""

            for i, oopt_name in enumerate(oopt_list[:5]):
                display_text += f"   - {oopt_name}\n"

            if len(oopt_list) > 5:
                display_text += f"   ... и еще {len(oopt_list) - 5} (Подробнее в txt)"

            oopt_text.setPlainText(display_text)
            results_layout.addWidget(oopt_text)
        else:
            no_oopt_label = QLabel("   - Нет данных")
            no_oopt_label.setStyleSheet("padding-left: 20px; color: gray;")
            results_layout.addWidget(no_oopt_label)

        # 7. Лесные кварталы
        forest_label = QLabel(
            f"7. Лесные кварталы: {self.results['forest_quarters']}"
        )
        forest_label.setStyleSheet("padding: 5px;")
        results_layout.addWidget(forest_label)

        # 8. Пересечения линий АД и ЖД
        intersections_label = QLabel("8. Пересечения линий:")
        intersections_label.setStyleSheet("padding: 5px; font-weight: bold;")
        results_layout.addWidget(intersections_label)

        road_road = self.results.get('road_road', 0)
        road_railway = self.results.get('road_railway', 0)
        railway_railway = self.results.get('railway_railway', 0)

        intersections_text = QLabel(
            f"   • АД и АД: {road_road}\n"
            f"   • АД и ЖД: {road_railway}\n"
            f"   • ЖД и ЖД: {railway_railway}"
        )
        intersections_text.setStyleSheet("padding-left: 20px;")
        results_layout.addWidget(intersections_text)

        results_group.setLayout(results_layout)
        layout.addWidget(results_group)
        
        # Растягивающийся элемент
        layout.addStretch()
        
        # Кнопки
        buttons_layout = QHBoxLayout()

        # Кнопка экспорта перечней
        export_btn = QPushButton("Экспорт перечней")
        export_btn.clicked.connect(self.export_cadnum_lists)
        buttons_layout.addWidget(export_btn)

        # Кнопка открытия папки
        open_folder_btn = QPushButton("Открыть папку с результатами")
        open_folder_btn.clicked.connect(self.open_results_folder)
        buttons_layout.addWidget(open_folder_btn)

        # Кнопка закрытия
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        buttons_layout.addWidget(close_btn)

        layout.addLayout(buttons_layout)

        self.setLayout(layout)
    def export_cadnum_lists(self):
        """Экспорт перечней кадастровых номеров"""
        from .Fsm_1_3_8_cadnum_list_export import CadnumListExporter

        # Создаем экспортер
        exporter = CadnumListExporter(None)

        # Выполняем экспорт
        success, filepath = exporter.export_cadnum_lists(self.temp_folder)

        if success:
            QMessageBox.information(
                self,
                "Экспорт перечней",
                f"Перечень кадастровых номеров успешно создан:\n{filepath}"
            )
        else:
            QMessageBox.critical(
                self,
                "Ошибка экспорта",
                "Не удалось создать перечень кадастровых номеров.\n"
                "Проверьте логи для подробностей."
            )

    def open_results_folder(self):
        """Открытие папки с результатами"""
        if os.path.exists(self.temp_folder):
            # Открываем папку в проводнике Windows
            # Используем os.startfile для Windows - это не вызывает ResourceWarning
            folder_path = os.path.normpath(self.temp_folder)
            os.startfile(folder_path)
        else:
            QMessageBox.warning(
                self,
                "Предупреждение",
                f"Папка не найдена: {self.temp_folder}"
            )
