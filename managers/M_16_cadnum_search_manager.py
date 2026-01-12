# -*- coding: utf-8 -*-
"""
CadnumSearchManager - Поиск объектов по кадастровому номеру

Обеспечивает:
- Поиск по КН через контекстное меню карты (ПКМ)
- Валидацию формата кадастровых номеров
- Поддержку полей 'cad_num' и 'cad_number'
- Экспорт найденных объектов
- Масштабирование и подсветку результатов
"""

import os
import re
from typing import List, Dict, Tuple, Optional, Set
from qgis.PyQt.QtWidgets import (
    QAction, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QCompleter, QApplication
)
from qgis.PyQt.QtGui import QIcon, QColor, QTextCharFormat, QTextCursor, QFont
from qgis.PyQt.QtCore import Qt, QTimer, QStringListModel
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsRectangle,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsExpression, QgsVectorFileWriter, QgsCoordinateTransformContext
)
from qgis.gui import QgsHighlight
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers.submodules.Msm_16_1_nspd_fetcher import Msm_16_1_NspdFetcher, NspdSearchResult


class CadnumSearchManager:
    """Менеджер поиска объектов по кадастровому номеру"""

    # Имена полей кадастрового номера (поддерживаемые варианты)
    FIELD_CADNUM = 'cad_num'
    FIELD_CADNUMBER = 'cad_number'

    # Регулярное выражение для валидации кадастрового номера
    # Формат: XX:XX:XXXX(XXX):X+
    # Регион: 1-2 цифры, Район: 1-2 цифры, Квартал: 4-7 цифр, Участок: 1+ цифр
    CADNUM_PATTERN = re.compile(
        r'^\d{1,2}:\d{1,2}:\d{4,7}:\d+$'
    )

    def __init__(self, iface):
        """
        Инициализация поиска

        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.action: Optional[QAction] = None
        self.dialog = None

    def init_gui(self):
        """Инициализация GUI - добавление действия в контекстное меню карты"""
        # Создаем действие для контекстного меню
        self.action = QAction("Поиск по кадастровому номеру...", self.iface.mainWindow())
        if self.action:
            self.action.setToolTip("Поиск объектов по кадастровым номерам во всех слоях проекта")

        # Подключаем к контекстному меню карты
        self.iface.mapCanvas().contextMenuAboutToShow.connect(self.add_to_context_menu)

    def unload(self):
        """Удаление GUI при выгрузке плагина"""
        try:
            self.iface.mapCanvas().contextMenuAboutToShow.disconnect(self.add_to_context_menu)
        except (TypeError, RuntimeError) as e:
            # TypeError: сигнал не был подключён
            # RuntimeError: объект уже удалён
            log_warning(f"M_16: Не удалось отключить сигнал contextMenuAboutToShow: {e}")

        if self.dialog and self.dialog.isVisible():
            self.dialog.close()

        log_info("CadnumSearchManager: Инструмент поиска выгружен")

    def add_to_context_menu(self, menu):
        """
        Добавление действия в контекстное меню карты

        Args:
            menu: Контекстное меню карты
        """
        if self.action is None:
            return

        # Добавляем действие в корень контекстного меню
        menu.addAction(self.action)
        self.action.triggered.connect(self.show_search_dialog)

    def show_search_dialog(self):
        """Показать диалог поиска"""
        if self.dialog is None:
            self.dialog = CadnumSearchDialog(self.iface)

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    @staticmethod
    def validate_cadnum(cadnum: str) -> bool:
        """
        Валидация формата кадастрового номера

        Формат: XX:XX:XXXX-XXXXXXX:X+
        Регион (1-2): Район (1-2): Квартал (4-7): Участок (1+)

        Примеры валидных номеров:
        - 77:01:0001:1 (минимальный квартал 4 цифры)
        - 77:01:12345:1 (квартал 5 цифр)
        - 77:01:1234567:123456789012 (максимальный квартал 7 цифр)
        - 50:23:0001234:56789012345678 (участок >12 цифр)

        Args:
            cadnum: Кадастровый номер для проверки

        Returns:
            bool: True если формат корректен, False иначе
        """
        cadnum = cadnum.strip()
        return bool(CadnumSearchManager.CADNUM_PATTERN.match(cadnum))

    @staticmethod
    def parse_input(text: str) -> List[str]:
        """
        Парсинг ввода пользователя - разделение по разделителям

        Поддерживаемые разделители: новая строка, запятая, точка с запятой, пробел

        Args:
            text: Текст для парсинга

        Returns:
            List[str]: Список кадастровых номеров
        """
        # Разделяем по различным разделителям
        cadnums = re.split(r'[,;\s\n\r\t]+', text)

        # Убираем пустые строки и пробелы
        cadnums = [c.strip() for c in cadnums if c.strip()]

        return cadnums

    @staticmethod
    def get_cadnum_field_name(layer: QgsVectorLayer) -> Optional[str]:
        """
        Определить имя поля кадастрового номера в слое

        Проверяет наличие полей 'cad_num' или 'cad_number' в слое

        Args:
            layer: Слой для проверки

        Returns:
            str: Имя поля ('cad_num' или 'cad_number') или None если не найдено
        """
        if layer.fields().indexFromName(CadnumSearchManager.FIELD_CADNUM) >= 0:
            return CadnumSearchManager.FIELD_CADNUM
        elif layer.fields().indexFromName(CadnumSearchManager.FIELD_CADNUMBER) >= 0:
            return CadnumSearchManager.FIELD_CADNUMBER
        return None

    @staticmethod
    def get_layers_with_cadnum() -> List[QgsVectorLayer]:
        """
        Получить все векторные слои проекта с полем кадастрового номера

        Ищет слои с полями 'cad_num' или 'cad_number'

        Returns:
            List[QgsVectorLayer]: Список слоев с полем кадастрового номера
        """
        layers = []

        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                # Проверяем наличие поля кадастрового номера (оба варианта)
                if CadnumSearchManager.get_cadnum_field_name(layer) is not None:
                    layers.append(layer)

        log_info(f"CadnumSearchManager: Найдено {len(layers)} слоев с полем кадастрового номера")
        return layers

    @staticmethod
    def search_in_layer(layer: QgsVectorLayer, cadnums: List[str]) -> Tuple[List[QgsFeature], List[str]]:
        """
        Поиск объектов в слое по списку кадастровых номеров

        Args:
            layer: Слой для поиска
            cadnums: Список кадастровых номеров

        Returns:
            Tuple[List[QgsFeature], List[str]]: (Найденные объекты, Найденные номера)
        """
        found_features = []
        found_cadnums = []

        # Определяем имя поля кадастрового номера в слое
        field_name = CadnumSearchManager.get_cadnum_field_name(layer)
        if not field_name:
            log_warning(f"CadnumSearchManager: Слой {layer.name()} не содержит поля кадастрового номера")
            return found_features, found_cadnums

        # Создаем SQL выражение для поиска
        # Используем QgsExpression.quotedValue() для безопасного экранирования
        formatted_values = ', '.join([QgsExpression.quotedValue(c) for c in cadnums])
        expression = f'"{field_name}" IN ({formatted_values})'

        try:
            # Выполняем поиск
            layer.selectByExpression(expression, QgsVectorLayer.SetSelection)

            # Получаем найденные объекты
            for feature in layer.selectedFeatures():
                found_features.append(feature)
                cad_num = feature.attribute(field_name)
                if cad_num:
                    found_cadnums.append(str(cad_num))

            log_info(f"CadnumSearchManager: В слое {layer.name()} найдено {len(found_features)} объектов")

        except Exception as e:
            log_error(f"CadnumSearchManager: Ошибка поиска в слое {layer.name()}: {str(e)}")

        return found_features, found_cadnums

    @staticmethod
    def get_autocomplete_suggestions(partial_cadnum: str, max_suggestions: int = 5) -> List[str]:
        """
        Получить предложения автодополнения для частичного кадастрового номера

        Показывает предложения только если найдено меньше max_suggestions вариантов

        Args:
            partial_cadnum: Частичный кадастровый номер (например, "77:01:")
            max_suggestions: Максимальное количество предложений для показа

        Returns:
            List[str]: Список предложений (пустой если слишком много вариантов)
        """
        if not partial_cadnum or len(partial_cadnum) < 3:
            return []

        suggestions = set()
        layers = CadnumSearchManager.get_layers_with_cadnum()

        for layer in layers:
            # Определяем имя поля кадастрового номера в слое
            field_name = CadnumSearchManager.get_cadnum_field_name(layer)
            if not field_name:
                continue

            try:
                for feature in layer.getFeatures():
                    cad_num = feature.attribute(field_name)
                    if cad_num and str(cad_num).startswith(partial_cadnum):
                        suggestions.add(str(cad_num))

                        # Если нашли больше max_suggestions - прерываем
                        if len(suggestions) >= max_suggestions:
                            log_info(f"CadnumSearchManager: Найдено {len(suggestions)}+ вариантов автодополнения - не показываем")
                            return []
            except Exception as e:
                log_warning(f"CadnumSearchManager: Ошибка автодополнения в слое {layer.name()}: {str(e)}")

        result = sorted(list(suggestions))
        log_info(f"CadnumSearchManager: Автодополнение: найдено {len(result)} вариантов")
        return result

    @staticmethod
    def calculate_combined_extent(features_by_layer: Dict[QgsVectorLayer, List[QgsFeature]],
                                   target_crs: Optional[QgsCoordinateReferenceSystem] = None) -> Optional[QgsRectangle]:
        """
        Вычислить объединенный extent для всех найденных объектов из разных слоев
        с учетом трансформации в целевую систему координат

        Args:
            features_by_layer: Словарь {слой: [объекты]}
            target_crs: Целевая система координат (если None - используется CRS карты)

        Returns:
            QgsRectangle: Объединенный extent или None
        """
        combined_extent = QgsRectangle()
        combined_extent.setMinimal()

        has_features = False

        # Если целевая CRS не указана, берем CRS первого слоя
        if target_crs is None and features_by_layer:
            first_layer = list(features_by_layer.keys())[0]
            target_crs = first_layer.crs()

        for layer, features in features_by_layer.items():
            layer_crs = layer.crs()

            log_info(f"CadnumSearchManager: Обработка слоя {layer.name()}, CRS: {layer_crs.authid()}, объектов: {len(features)}")

            # Создаем трансформатор координат если CRS отличается
            needs_transform = target_crs and layer_crs != target_crs
            transform = None
            if needs_transform:
                transform = QgsCoordinateTransform(layer_crs, target_crs, QgsProject.instance())
                log_info(f"CadnumSearchManager: Требуется трансформация из {layer_crs.authid()} в {target_crs.authid()}")

            for feature in features:
                if feature.hasGeometry():
                    bbox = feature.geometry().boundingBox()
                    original_bbox = bbox.toString(2)

                    # Трансформируем bbox если нужно
                    if transform:
                        try:
                            bbox = transform.transformBoundingBox(bbox)
                            log_info(f"CadnumSearchManager: Трансформация extent: {original_bbox} → {bbox.toString(2)}")
                        except Exception as e:
                            log_warning(f"CadnumSearchManager: Ошибка трансформации extent: {str(e)}")
                            continue

                    if not has_features:
                        combined_extent = bbox
                        has_features = True
                        log_info(f"CadnumSearchManager: Начальный extent: {bbox.toString(2)}")
                    else:
                        combined_extent.combineExtentWith(bbox)

        if has_features:
            log_info(f"CadnumSearchManager: Итоговый extent: {combined_extent.toString(2)}, Центр: ({combined_extent.center().x():.2f}, {combined_extent.center().y():.2f})")

        return combined_extent if has_features else None


class CadnumSearchDialog(QDialog):
    """Диалог для поиска объектов по кадастровым номерам"""

    def __init__(self, iface, parent=None):
        """
        Инициализация диалога

        Args:
            iface: Интерфейс QGIS
            parent: Родительское окно
        """
        super().__init__(parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()

        # Результаты поиска
        self.search_results = {}  # {layer: [features]}
        self.found_cadnums = set()  # Множество найденных номеров
        self.not_found_cadnums = []  # Список не найденных номеров
        self.invalid_cadnums = []  # Список невалидных номеров

        # Highlights для мигания
        self.highlights = []
        
        # НСПД загрузчик
        self.nspd_fetcher = Msm_16_1_NspdFetcher()

        # Completer для автодополнения
        self.completer = None

        # Таймер для дебаунсинга подсветки (избегаем лагов при вводе)
        self.highlight_timer = QTimer()
        self.highlight_timer.setSingleShot(True)
        self.highlight_timer.setInterval(500)  # 500 мс задержка
        self.highlight_timer.timeout.connect(self.highlight_invalid_cadnums)

        self.init_ui()

        log_info("CadnumSearchDialog: Диалог поиска создан")

    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle("Поиск по кадастровому номеру")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)

        layout = QVBoxLayout()

        # === Секция ввода ===
        input_label = QLabel("Введите кадастровые номера:")
        input_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        layout.addWidget(input_label)

        hint_label = QLabel("(Разделители: новая строка, запятая, точка с запятой, пробел)")
        hint_label.setStyleSheet("color: gray; font-size: 9pt;")
        layout.addWidget(hint_label)

        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText(
            "Пример:\n"
            "77:01:0001001:1234\n"
            "77:01:0001001:5678\n"
            "77:01:0001002:9012"
        )
        self.input_text.setMinimumHeight(120)
        self.input_text.textChanged.connect(self.on_text_changed)
        layout.addWidget(self.input_text)

        # Информация о формате
        format_label = QLabel("Формат: Регион(1-2):Район(1-2):Квартал(4-7):Участок(1+)")
        format_label.setStyleSheet("color: #555; font-size: 9pt; font-style: italic;")
        layout.addWidget(format_label)

        # === Таблица результатов ===
        results_label = QLabel("Результаты поиска:")
        results_label.setStyleSheet("font-weight: bold; font-size: 11pt; margin-top: 10px;")
        layout.addWidget(results_label)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["Кадастровый номер", "Слой", "Статус"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.results_table)

        # === Статистика ===
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #333; font-size: 10pt; margin: 5px 0;")
        layout.addWidget(self.stats_label)

        # === Кнопки управления ===
        buttons_layout = QHBoxLayout()

        self.search_button = QPushButton("Найти")
        self.search_button.setStyleSheet("font-weight: bold; padding: 8px 20px;")
        self.search_button.clicked.connect(self.perform_search)
        buttons_layout.addWidget(self.search_button)

        self.clear_button = QPushButton("Очистить")
        self.clear_button.clicked.connect(self.clear_results)
        buttons_layout.addWidget(self.clear_button)

        self.export_button = QPushButton("Экспортировать найденные")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_results)
        buttons_layout.addWidget(self.export_button)
        
        self.nspd_button = QPushButton("Загрузить из НСПД")
        self.nspd_button.setToolTip("Загрузить геометрию не найденных объектов из НСПД по кадастровому номеру")
        self.nspd_button.setEnabled(False)
        self.nspd_button.clicked.connect(self.fetch_from_nspd)
        buttons_layout.addWidget(self.nspd_button)

        buttons_layout.addStretch()

        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.close)
        buttons_layout.addWidget(self.close_button)

        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def on_text_changed(self):
        """Обработчик изменения текста - только валидация без автодополнения"""
        # ОТКЛЮЧЕНО: Автодополнение вызывает зависание при большом количестве объектов
        # Валидация с задержкой 500мс (дебаунсинг) - избегаем лагов при быстром вводе
        self.highlight_timer.stop()
        self.highlight_timer.start()

    def insert_completion(self, completion):
        """
        Вставка выбранного варианта автодополнения

        Args:
            completion: Выбранный вариант
        """
        cursor = self.input_text.textCursor()
        cursor.select(QTextCursor.LineUnderCursor)
        cursor.removeSelectedText()
        cursor.insertText(completion)

    def highlight_invalid_cadnums(self):
        """Подсветка невалидных кадастровых номеров красным цветом"""
        text = self.input_text.toPlainText()
        cadnums = CadnumSearchManager.parse_input(text)

        # Формат для невалидных номеров
        invalid_format = QTextCharFormat()
        invalid_format.setForeground(QColor(220, 50, 50))
        invalid_format.setFontWeight(QFont.Bold)
        invalid_format.setBackground(QColor(255, 200, 200, 50))  # Светло-красный фон

        # Список выделений для применения
        extra_selections = []

        # Подсвечиваем невалидные
        for cadnum in cadnums:
            if not CadnumSearchManager.validate_cadnum(cadnum):
                # Ищем все вхождения этого номера в тексте
                cursor = QTextCursor(self.input_text.document())
                cursor.setPosition(0)

                while True:
                    cursor = self.input_text.document().find(cadnum, cursor)
                    if cursor.isNull():
                        break

                    # Создаем ExtraSelection для этого вхождения
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = cursor
                    selection.format = invalid_format
                    extra_selections.append(selection)

        # Применяем все выделения БЕЗ изменения позиции курсора пользователя
        self.input_text.setExtraSelections(extra_selections)

    def perform_search(self):
        """Выполнить поиск по введенным номерам"""
        text = self.input_text.toPlainText().strip()

        if not text:
            QMessageBox.warning(self, "Предупреждение", "Введите хотя бы один кадастровый номер")
            return

        # Парсим ввод
        cadnums = CadnumSearchManager.parse_input(text)

        if not cadnums:
            QMessageBox.warning(self, "Предупреждение", "Не удалось распознать кадастровые номера")
            return

        # Валидация
        valid_cadnums = []
        self.invalid_cadnums = []

        for cadnum in cadnums:
            if CadnumSearchManager.validate_cadnum(cadnum):
                valid_cadnums.append(cadnum)
            else:
                self.invalid_cadnums.append(cadnum)

        if self.invalid_cadnums:
            msg = f"Найдено {len(self.invalid_cadnums)} невалидных номеров:\n"
            msg += "\n".join(self.invalid_cadnums[:5])
            if len(self.invalid_cadnums) > 5:
                msg += f"\n... и еще {len(self.invalid_cadnums) - 5}"
            msg += "\n\nПродолжить поиск валидных номеров?"

            reply = QMessageBox.question(self, "Невалидные номера", msg,
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return

        if not valid_cadnums:
            QMessageBox.warning(self, "Ошибка", "Не найдено ни одного валидного кадастрового номера")
            return

        # Выполняем поиск
        self.search_results.clear()
        self.found_cadnums.clear()
        self.not_found_cadnums = []

        layers = CadnumSearchManager.get_layers_with_cadnum()

        if not layers:
            QMessageBox.warning(self, "Предупреждение",
                              "В проекте нет слоев с полем кадастрового номера ('cad_num' или 'cad_number')")
            return

        log_info(f"CadnumSearchDialog: Поиск {len(valid_cadnums)} номеров в {len(layers)} слоях")

        # Поиск в каждом слое
        for layer in layers:
            features, found = CadnumSearchManager.search_in_layer(layer, valid_cadnums)
            if features:
                self.search_results[layer] = features
                self.found_cadnums.update(found)

        # Определяем не найденные
        self.not_found_cadnums = [c for c in valid_cadnums if c not in self.found_cadnums]

        # Отображаем результаты
        self.display_results(valid_cadnums)

        # Если что-то найдено - выделяем, масштабируем и мигаем
        if self.search_results:
            self.zoom_to_results()
            self.flash_results()
            self.export_button.setEnabled(True)
        
        # Активируем кнопку НСПД если есть не найденные
        self.nspd_button.setEnabled(len(self.not_found_cadnums) > 0)
        
        if not self.search_results and not self.not_found_cadnums:
            QMessageBox.information(self, "Результат",
                                   f"Ничего не найдено из {len(valid_cadnums)} номеров")

    def display_results(self, searched_cadnums: List[str]):
        """
        Отображение результатов поиска в таблице

        Args:
            searched_cadnums: Список искомых номеров
        """
        self.results_table.setRowCount(0)

        row = 0

        # Добавляем найденные
        for layer, features in self.search_results.items():
            layer_name = layer.name()

            # Определяем имя поля кадастрового номера в слое
            field_name = CadnumSearchManager.get_cadnum_field_name(layer)
            if not field_name:
                continue

            for feature in features:
                cadnum = str(feature.attribute(field_name))

                self.results_table.insertRow(row)

                # Кадастровый номер
                item_cadnum = QTableWidgetItem(cadnum)
                self.results_table.setItem(row, 0, item_cadnum)

                # Слой
                item_layer = QTableWidgetItem(layer_name)
                self.results_table.setItem(row, 1, item_layer)

                # Статус
                item_status = QTableWidgetItem("✓ Найден")
                item_status.setForeground(QColor(0, 150, 0))
                self.results_table.setItem(row, 2, item_status)

                row += 1

        # Добавляем не найденные
        for cadnum in self.not_found_cadnums:
            self.results_table.insertRow(row)

            # Кадастровый номер
            item_cadnum = QTableWidgetItem(cadnum)
            item_cadnum.setForeground(QColor(200, 50, 50))
            self.results_table.setItem(row, 0, item_cadnum)

            # Слой
            item_layer = QTableWidgetItem("-")
            self.results_table.setItem(row, 1, item_layer)

            # Статус
            item_status = QTableWidgetItem("✗ Не найден")
            item_status.setForeground(QColor(200, 50, 50))
            self.results_table.setItem(row, 2, item_status)

            row += 1

        # Обновляем статистику
        total_searched = len(searched_cadnums)
        total_found = len(self.found_cadnums)
        total_not_found = len(self.not_found_cadnums)
        layers_count = len(self.search_results)

        stats = f"Найдено: {total_found} из {total_searched}"
        if layers_count > 0:
            stats += f" (в {layers_count} слоях)"
        if total_not_found > 0:
            stats += f" | Не найдено: {total_not_found}"
        if self.invalid_cadnums:
            stats += f" | Невалидных: {len(self.invalid_cadnums)}"

        self.stats_label.setText(stats)

        log_info(f"CadnumSearchDialog: {stats}")

    def zoom_to_results(self):
        """Масштабирование к найденным объектам"""
        # Получаем CRS карты для корректной трансформации
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        extent = CadnumSearchManager.calculate_combined_extent(self.search_results, canvas_crs)

        if extent:
            # Добавляем небольшой буфер (5%)
            extent.scale(1.05)
            self.canvas.setExtent(extent)
            self.canvas.refresh()

            log_info(f"CadnumSearchDialog: Масштабирование к найденным объектам (CRS: {canvas_crs.authid()})")

    def flash_results(self):
        """Мигание найденных объектов (10 секунд)"""
        # Удаляем предыдущие highlights
        self.clear_highlights()

        # Создаем новые highlights для каждого найденного объекта
        for layer, features in self.search_results.items():
            for feature in features:
                if feature.hasGeometry():
                    highlight = QgsHighlight(self.canvas, feature.geometry(), layer)
                    highlight.setColor(QColor(255, 0, 0, 100))
                    highlight.setWidth(4)
                    highlight.setFillColor(QColor(255, 0, 0, 50))
                    highlight.show()
                    self.highlights.append(highlight)

        # Удаляем highlights через 10 секунд
        QTimer.singleShot(10000, self.clear_highlights)

        log_info(f"CadnumSearchDialog: Мигание {len(self.highlights)} объектов (10 секунд)")

    def clear_highlights(self):
        """Удаление highlights (мигания)"""
        for highlight in self.highlights:
            highlight.hide()
        self.highlights.clear()

    def export_results(self):
        """Экспорт найденных объектов"""
        if not self.search_results:
            QMessageBox.warning(self, "Предупреждение", "Нет результатов для экспорта")
            return

        # Диалог выбора файла
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Сохранить найденные объекты",
            "",
            "GeoPackage (*.gpkg);;Shapefile (*.shp);;GeoJSON (*.geojson)"
        )

        if not file_path:
            return

        # Определяем драйвер по расширению
        if file_path.endswith('.gpkg'):
            driver_name = 'GPKG'
        elif file_path.endswith('.shp'):
            driver_name = 'ESRI Shapefile'
        elif file_path.endswith('.geojson'):
            driver_name = 'GeoJSON'
        else:
            # По умолчанию GPKG
            file_path += '.gpkg'
            driver_name = 'GPKG'

        try:
            # Экспортируем каждый слой отдельно
            exported_count = 0

            for layer, features in self.search_results.items():
                # Создаем временный слой с выделенными объектами
                layer.selectByIds([f.id() for f in features])

                # Определяем имя слоя для экспорта
                if len(self.search_results) > 1:
                    # Если несколько слоев - добавляем суффикс
                    if driver_name == 'GPKG':
                        layer_name = layer.name()
                    else:
                        # Для Shapefile создаем отдельные файлы
                        base_name = os.path.splitext(file_path)[0]
                        file_path_layer = f"{base_name}_{layer.name()}{os.path.splitext(file_path)[1]}"
                else:
                    layer_name = os.path.splitext(os.path.basename(file_path))[0]
                    file_path_layer = file_path

                # Опции экспорта
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = driver_name
                options.fileEncoding = 'UTF-8'
                options.onlySelectedFeatures = True

                if driver_name == 'GPKG' and len(self.search_results) > 1:
                    options.layerName = layer_name
                    if exported_count > 0:
                        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
                    file_path_layer = file_path

                # Экспортируем
                error = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer,
                    file_path_layer if driver_name != 'GPKG' or exported_count == 0 else file_path,
                    QgsCoordinateTransformContext(),
                    options
                )

                if error[0] == QgsVectorFileWriter.NoError:
                    exported_count += len(features)
                    log_info(f"CadnumSearchDialog: Экспортировано {len(features)} объектов из {layer.name()}")
                else:
                    log_error(f"CadnumSearchDialog: Ошибка экспорта {layer.name()}: {error[1]}")

                # Снимаем выделение
                layer.removeSelection()

            QMessageBox.information(
                self,
                "Экспорт завершен",
                f"Экспортировано {exported_count} объектов в:\n{file_path}"
            )

        except Exception as e:
            log_error(f"CadnumSearchDialog: Ошибка экспорта: {str(e)}")
            QMessageBox.critical(self, "Ошибка экспорта", f"Не удалось экспортировать:\n{str(e)}")

    def clear_results(self):
        """Очистка результатов и сброс интерфейса"""
        self.input_text.clear()
        self.results_table.setRowCount(0)
        self.stats_label.setText("")
        self.search_results.clear()
        self.found_cadnums.clear()
        self.not_found_cadnums.clear()
        self.invalid_cadnums.clear()
        self.clear_highlights()
        self.export_button.setEnabled(False)
        self.nspd_button.setEnabled(False)

        # Снимаем выделение со всех слоев
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                layer.removeSelection()

        log_info("CadnumSearchDialog: Результаты очищены")

    def fetch_from_nspd(self):
        """Загрузка геометрии не найденных объектов из НСПД"""
        if not self.not_found_cadnums:
            QMessageBox.information(self, "Информация", "Нет не найденных кадастровых номеров")
            return
        
        # Подтверждение
        count = len(self.not_found_cadnums)
        reply = QMessageBox.question(
            self, "Загрузка из НСПД",
            f"Загрузить геометрию для {count} объектов из НСПД?\n\n"
            "Объекты будут добавлены в соответствующие слои WFS.\n"
            "Требуется подключение к интернету.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        log_info(f"CadnumSearchDialog: Загрузка {count} КН из НСПД")
        
        # Блокируем кнопку на время загрузки
        self.nspd_button.setEnabled(False)
        self.nspd_button.setText("Загрузка...")
        QApplication.processEvents()
        
        # Статистика загрузки
        loaded = []
        errors = []
        
        try:
            for cadnum in self.not_found_cadnums[:]:
                result = self.nspd_fetcher.fetch_by_cadnum(cadnum)
                
                if result.error:
                    errors.append((cadnum, result.error))
                    continue
                
                # Добавляем в слой
                success, message = self.nspd_fetcher.add_to_layer(result)
                
                if success:
                    loaded.append((cadnum, result.target_layer_name))
                    # Убираем из списка не найденных
                    self.not_found_cadnums.remove(cadnum)
                    self.found_cadnums.add(cadnum)
                else:
                    errors.append((cadnum, message))
        
        finally:
            # Восстанавливаем кнопку
            self.nspd_button.setText("Загрузить из НСПД")
            self.nspd_button.setEnabled(len(self.not_found_cadnums) > 0)
        
        # Обновляем таблицу результатов
        self._update_results_after_nspd(loaded, errors)
        
        # Показываем итог
        if loaded:
            msg = f"Загружено: {len(loaded)} объектов"
            if errors:
                msg += f"\nОшибок: {len(errors)}"
            QMessageBox.information(self, "Загрузка из НСПД", msg)
            
            # Обновляем карту
            self.canvas.refresh()
        else:
            error_details = "\n".join([f"{cn}: {err}" for cn, err in errors[:5]])
            if len(errors) > 5:
                error_details += f"\n... и еще {len(errors) - 5}"
            QMessageBox.warning(
                self, "Загрузка из НСПД",
                f"Не удалось загрузить объекты:\n\n{error_details}"
            )

    def _update_results_after_nspd(self, loaded: List[tuple], errors: List[tuple]):
        """Обновить таблицу после загрузки из НСПД"""
        # Обновляем статусы в таблице
        for row in range(self.results_table.rowCount()):
            cadnum_item = self.results_table.item(row, 0)
            if not cadnum_item:
                continue
            
            cadnum = cadnum_item.text()
            
            # Проверяем загруженные
            for loaded_cadnum, layer_name in loaded:
                if cadnum == loaded_cadnum:
                    # Обновляем слой
                    layer_item = QTableWidgetItem(layer_name)
                    self.results_table.setItem(row, 1, layer_item)
                    
                    # Обновляем статус
                    status_item = QTableWidgetItem("✓ Загружен из НСПД")
                    status_item.setForeground(QColor(0, 100, 200))
                    self.results_table.setItem(row, 2, status_item)
                    
                    # Убираем красный цвет с КН
                    cadnum_item.setForeground(QColor(0, 100, 200))
                    break
            
            # Проверяем ошибки
            for error_cadnum, error_msg in errors:
                if cadnum == error_cadnum:
                    status_item = QTableWidgetItem(f"✗ {error_msg[:30]}")
                    status_item.setForeground(QColor(200, 100, 0))
                    status_item.setToolTip(error_msg)
                    self.results_table.setItem(row, 2, status_item)
                    break
        
        # Обновляем статистику
        total_found = len(self.found_cadnums)
        total_not_found = len(self.not_found_cadnums)
        nspd_loaded = len(loaded)
        
        stats = f"Найдено: {total_found}"
        if nspd_loaded > 0:
            stats += f" (из них {nspd_loaded} из НСПД)"
        if total_not_found > 0:
            stats += f" | Не найдено: {total_not_found}"
        if self.invalid_cadnums:
            stats += f" | Невалидных: {len(self.invalid_cadnums)}"
        
        self.stats_label.setText(stats)

    def closeEvent(self, event):
        """Обработчик закрытия диалога"""
        self.clear_highlights()
        super().closeEvent(event)
