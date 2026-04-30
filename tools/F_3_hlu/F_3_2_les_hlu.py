# -*- coding: utf-8 -*-
"""
F_3_2_ЛЕС ХЛУ - Генерация Word документа ХЛУ

Генерация документа "Характеристика образуемых лесных участков" (ХЛУ)
на основе слоёв Le_3_* (результат F_3_1).

Выходной документ:
- Один Word файл со структурой по муниципальным районам
- 6 таблиц в каждом разделе + раздел ОЗУ

Примечание:
    Выполняется ПОСЛЕ F_3_1.
    Требует наличие слоёв Le_3_* и Le_1_2_3_10_АТД_МО_poly.
"""

import os
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject, Qgis

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION,
    LAYER_ATD_MO,
)
from Daman_QGIS.utils import log_info, log_warning, log_error, path_for_display

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager, ProjectManager


class F_3_2_LesHLU(BaseTool):
    """Генерация Word документа ХЛУ на основе слоёв Le_3_*"""

    def __init__(self, iface) -> None:
        """Инициализация инструмента"""
        super().__init__(iface)
        self.layer_manager: Optional['LayerManager'] = None
        self.project_manager: Optional['ProjectManager'] = None
        self.plugin_dir: Optional[str] = None

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоев"""
        self.layer_manager = layer_manager

    def set_project_manager(self, project_manager: 'ProjectManager') -> None:
        """Установка менеджера проектов"""
        self.project_manager = project_manager

    def get_name(self) -> str:
        """Получить имя инструмента для cleanup"""
        return "F_3_2_ЛЕС ХЛУ"

    def run(self) -> None:
        """Основной метод запуска инструмента"""
        log_info("F_3_2: Запуск генерации документа ХЛУ")

        # Валидация
        if not self._validate():
            return

        try:
            # Импорт процессора и экспортера
            from Daman_QGIS.managers.export.submodules import HLU_DataProcessor
            from Daman_QGIS.managers import registry

            # Создаём процессор данных
            processor = HLU_DataProcessor(self.project_manager, self.layer_manager)

            # Подготавливаем контекст
            log_info("F_3_2: Подготовка контекста для шаблона...")
            context = processor.prepare_full_context_le4(
                vid_ispolzovaniya="Строительство, реконструкция, эксплуатация линейных объектов",
                cel_predostavleniya=""
            )

            # Проверка на ошибки
            if "error" in context:
                log_error(f"F_3_2: Ошибка подготовки данных: {context['error']}")
                QMessageBox.warning(
                    None,
                    "Ошибка данных",
                    f"Не удалось подготовить данные:\n{context['error']}"
                )
                return

            # Проверяем наличие данных
            if not context.get("rayony"):
                log_warning("F_3_2: Нет данных для генерации документа")
                QMessageBox.information(
                    None,
                    "Нет данных",
                    "Нет лесных участков для генерации документа ХЛУ.\n"
                    "Убедитесь, что слои Le_3_* содержат данные."
                )
                return

            # Получаем менеджер экспорта
            word_manager = registry.get('M_33')

            # Определяем путь к шаблону
            # Единый шаблон hlu.docx для обоих режимов (L_1_12_*/L_1_13_* и Le_3_*)
            template_path = os.path.join(
                self.plugin_dir,
                "data", "templates", "word", "hlu", "hlu.docx"
            )

            if not os.path.exists(template_path):
                log_error(f"F_3_2: Шаблон hlu.docx не найден: {template_path}")
                QMessageBox.critical(
                    None,
                    "Шаблон не найден",
                    "Шаблон Word hlu.docx не найден.\n\n"
                    "Путь: data/templates/word/hlu/hlu.docx\n\n"
                    "Спецификация шаблона:\n"
                    "data/templates/word/hlu/hlu_TEMPLATE_SPEC.md"
                )
                return

            # Определяем путь для сохранения
            output_path = self._get_output_path()
            if not output_path:
                log_error("F_3_2: Не удалось определить путь для сохранения")
                return

            # Генерируем документ
            log_info(f"F_3_2: Генерация документа в {output_path}")
            word_manager.render(template_path, context, output_path)

            # Успех
            log_info(f"F_3_2: Документ ХЛУ успешно создан: {output_path}")
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                f"Документ ХЛУ создан: {os.path.basename(output_path)}",
                Qgis.Success,
                MESSAGE_SUCCESS_DURATION
            )

            # Предложение открыть документ
            reply = QMessageBox.question(
                None,
                "Документ создан",
                f"Документ ХЛУ успешно создан:\n{path_for_display(output_path)}\n\nОткрыть документ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                os.startfile(output_path)

        except ImportError as e:
            log_error(f"F_3_2: Ошибка импорта: {e}")
            QMessageBox.critical(
                None,
                "Ошибка",
                f"Не удалось загрузить модули:\n{e}"
            )
        except Exception as e:
            log_error(f"F_3_2: Ошибка генерации документа: {e}")
            QMessageBox.critical(
                None,
                "Ошибка",
                f"Не удалось создать документ ХЛУ:\n{e}"
            )

    def _validate(self) -> bool:
        """Валидация перед запуском"""

        # Проверка менеджеров
        if not self.layer_manager:
            log_error("F_3_2: LayerManager не установлен")
            QMessageBox.critical(
                None,
                "Ошибка",
                "Менеджер слоёв не инициализирован."
            )
            return False

        if not self.plugin_dir:
            log_error("F_3_2: plugin_dir не установлен")
            QMessageBox.critical(
                None,
                "Ошибка",
                "Путь к плагину не установлен."
            )
            return False

        # Проверка наличия слоя МО
        mo_layer = self.layer_manager.get_layer(LAYER_ATD_MO)
        if not mo_layer or not mo_layer.isValid():
            log_error(f"F_3_2: Слой МО не найден: {LAYER_ATD_MO}")
            QMessageBox.warning(
                None,
                "Слой не найден",
                f"Не найден слой муниципальных округов:\n{LAYER_ATD_MO}\n\n"
                "Загрузите слой через F_1_2."
            )
            return False

        # Проверка наличия слоёв Le_3_*
        le4_layers_found = []
        from Daman_QGIS.managers.export.submodules.Msm_33_1_hlu_processor import LE4_LAYERS

        for layer_name in LE4_LAYERS:
            layer = self.layer_manager.get_layer(layer_name)
            if layer and layer.isValid() and layer.featureCount() > 0:
                le4_layers_found.append(layer_name)

        if not le4_layers_found:
            log_warning("F_3_2: Не найдены слои Le_3_* с данными")
            QMessageBox.warning(
                None,
                "Нет данных",
                "Не найдены слои Le_3_* с лесными участками.\n\n"
                "Сначала выполните F_3_1 (Нарезка ЗПР по лесным выделам)."
            )
            return False

        log_info(f"F_3_2: Найдено {len(le4_layers_found)} слоёв Le_3_* с данными")
        return True

    def _get_output_path(self) -> Optional[str]:
        """Получить путь для сохранения документа"""

        # Определяем папку New release
        project_path = QgsProject.instance().fileName()
        if not project_path:
            log_error("F_3_2: Проект не сохранён, невозможно определить папку для документа")
            return None
        project_dir = os.path.dirname(project_path)
        output_dir = os.path.join(project_dir, "New release")

        # Создаём папку если её нет
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                log_info(f"F_3_2: Создана папка {output_dir}")
            except OSError as e:
                log_error(f"F_3_2: Не удалось создать папку: {e}")
                output_dir = project_dir

        # Формируем имя файла
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"HLU_{date_str}.docx"
        output_path = os.path.join(output_dir, filename)

        # Если файл существует, добавляем номер
        counter = 1
        while os.path.exists(output_path):
            filename = f"HLU_{date_str}_{counter}.docx"
            output_path = os.path.join(output_dir, filename)
            counter += 1

        return output_path
