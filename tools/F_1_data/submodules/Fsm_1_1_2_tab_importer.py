# -*- coding: utf-8 -*-
"""
Импортер для файлов TAB (MapInfo Native Format).
Использует OGR провайдер QGIS для чтения данных.
"""

import os
from typing import Optional, List, Dict, Any
from qgis.core import (
    QgsVectorLayer, QgsMessageLog, Qgis,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
)
import processing

from ..core.base_importer import BaseImporter
from Daman_QGIS.database.schemas import ImportSettings
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error

class Fsm_1_1_2_TabImporter(BaseImporter):
    """
    Импортер TAB файлов MapInfo.
    Реализует все абстрактные методы базового класса: import_file, supports_format
    """

    def __init__(self, iface=None):
        """Инициализация импортера"""
        super().__init__(iface)
        self.settings: Optional[ImportSettings] = None

    def log_message(self, message: str, level: Qgis.MessageLevel = Qgis.Info):
        """Логирование сообщений"""
        if level == Qgis.Info:
            log_info(message)
        elif level == Qgis.Warning:
            log_warning(message)
        elif level == Qgis.Critical:
            log_error(message)
        else:
            log_info(message)

    def apply_encoding(self, layer: QgsVectorLayer, encoding: str = "cp1251"):
        """Применение кодировки к атрибутам слоя"""
        # Метод для применения кодировки
        layer.setProviderEncoding(encoding)

    def supports_format(self, file_extension: str) -> bool:
        """Проверка поддержки формата"""
        return file_extension.lower() in self.get_supported_formats()
    
    def get_supported_formats(self) -> List[str]:
        """
        Получение списка поддерживаемых форматов
        
        Returns:
            Список расширений
        """
        return ['.tab']
    
    def can_import(self, file_path: str) -> bool:
        """
        Проверка возможности импорта файла
        
        Args:
            file_path: Путь к файлу
            
        Returns:
            True если можно импортировать
        """
        if not os.path.exists(file_path):
            return False
        
        # Проверяем расширение
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.get_supported_formats():
            return False
        
        # Проверяем наличие сопутствующих файлов
        base_path = os.path.splitext(file_path)[0]
        
        # TAB формат обычно включает несколько файлов
        # .DAT - данные атрибутов
        # .MAP - геометрия
        # .ID - индекс
        # .IND - индекс атрибутов (опционально)
        
        required_files = [
            base_path + '.dat',  # или .DAT
            base_path + '.map'   # или .MAP
        ]
        
        for req_file in required_files:
            # Проверяем оба регистра
            if not (os.path.exists(req_file) or os.path.exists(req_file.upper())):
                self.log_message(
                    f"Не найден обязательный файл: {req_file}",
                    Qgis.Warning
                )
                # TAB может работать и с неполным набором
        
        return True
    
    def import_file(self, file_path: str, **custom_params) -> Dict[str, Any]:
        """
        Импорт TAB файла (переопределяет абстрактный метод базового класса)

        Args:
            file_path: Путь к TAB файлу
            **custom_params: Дополнительные параметры (может содержать 'settings', 'layer_name')

        Returns:
            Словарь с результатами импорта
        """
        # Создаем или обновляем settings с именем целевого слоя
        settings = custom_params.get('settings')
        if not settings:
            settings = ImportSettings(
                source_format='TAB',
                target_layer_name=custom_params.get('layer_name', os.path.basename(file_path))
            )
        elif custom_params.get('layer_name'):
            # Обновляем имя слоя если передано через custom_params
            settings.target_layer_name = custom_params.get('layer_name')

        layer = self._import_file_internal(file_path, settings)

        if layer:
            return {
                'success': True,
                'layers': [layer],
                'message': f'Успешно импортирован файл {os.path.basename(file_path)}',
                'errors': []
            }
        else:
            return {
                'success': False,
                'layers': [],
                'message': f'Не удалось импортировать файл {os.path.basename(file_path)}',
                'errors': ['Import failed']
            }
    def _import_file_internal(self,
                   file_path: str,
                   settings: Optional[ImportSettings] = None) -> Optional[QgsVectorLayer]:
        """
        Внутренний метод импорта TAB файла

        Args:
            file_path: Путь к TAB файлу
            settings: Настройки импорта

        Returns:
            Импортированный слой или None
        """
        self.settings = settings or ImportSettings(
            source_format='TAB',
            target_layer_name=os.path.basename(file_path)
        )

        # Логируем начало импорта
        self.log_message(f"Начало импорта: {os.path.basename(file_path)}")

        # Определяем имя слоя
        layer_name = self.settings.target_layer_name if self.settings else None
        if not layer_name:
            layer_name = os.path.splitext(os.path.basename(file_path))[0]

        # 20% прогресса

        # Создаем слой через OGR
        # OGR автоматически обработает все сопутствующие файлы TAB
        layer = QgsVectorLayer(file_path, layer_name, "ogr")

        if not layer.isValid():
            raise RuntimeError(f"Не удалось загрузить слой из файла: {file_path}")

        # 50% прогресса
        self.log_message(f"Слой загружен: {layer.featureCount()} объектов")

        # TAB файлы обычно в кодировке cp1251 для русских данных
        encoding = self.settings.encoding if self.settings else 'cp1251'
        if not encoding:
            encoding = 'cp1251'
        self.apply_encoding(layer, encoding)

        # 70% прогресса

        # 90% прогресса

        # Применяем маппинг атрибутов если задан
        if self.settings and self.settings.attributes_mapping:
            self._apply_attributes_mapping(layer)

        # TAB файлы часто без СК (Nonearth) - устанавливаем СК проекта
        if not layer.crs().isValid() or layer.crs().authid() == '':
            project_crs = self.get_project_crs()
            if project_crs and project_crs.isValid():
                layer.setCrs(project_crs)
                self.log_message(f"Fsm_1_1_2: Установлена СК из проекта: {project_crs.authid()}")

        # Логируем информацию о слое
        self.log_message(
            f"Импортирован слой '{layer_name}': "
            f"{layer.featureCount()} объектов, "
            f"тип геометрии: {layer.wkbType()}, "
            f"СК: {layer.crs().authid()}, "
            f"атрибутов: {len(layer.fields())}",
            Qgis.Info
        )

        # F_1_1: превентивная валидация и авто-исправление невалидной геометрии
        # (hole-outside-shell и др.) ДО материализации в GPKG (вариант B).
        # Валидатор строит MultiPolygon memory-слой → save_to_gpkg рождает
        # gpkg-слой сразу MultiPolygon (одна запись, без orphan-ghost).
        layer = self._validate_and_fix_geometry(layer, layer_name)

        self.result_layer = layer

        # Сохраняем в GPKG через LayerProcessor
        from ..core import LayerProcessor
        processor = LayerProcessor(self.project_manager, self.layer_manager)
        saved_layer = processor.save_to_gpkg(layer, layer_name)
        if saved_layer:
            layer = saved_layer
            self.result_layer = layer
            self.log_message(f"Слой '{layer_name}' сохранён в GPKG")

        # Добавляем слой в проект через LayerManager (автоматическое применение стилей)
        # Если слой уже добавлен в GPKG, удаляем временный перед добавлением
        if layer.id() in QgsProject.instance().mapLayers():
            QgsProject.instance().removeMapLayer(layer.id())

        if self.layer_manager:
            self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
            self.log_message(f"Слой '{layer.name()}' добавлен в проект через LayerManager")
        else:
            QgsProject.instance().addMapLayer(layer)
            self.log_message(f"Слой '{layer.name()}' добавлен в проект напрямую (LayerManager не доступен)")

        # Создаём буферные слои если импортировали L_1_1_1_Границы_работ
        if layer.name() == 'L_1_1_1_Границы_работ':
            self._create_buffer_layers(layer)

        return layer

    def _validate_and_fix_geometry(self, layer: QgsVectorLayer, layer_name: str) -> QgsVectorLayer:
        """Валидация и авто-исправление геометрии импортированного TAB-слоя (F_1_1).

        Делегирует в Fsm_1_1_15_GeometryValidator (per-feature-selective fix
        невалидных, promotion валидных в MultiPolygon). Сводку показывает
        пользователю (messageBar) + отправляет в телеметрию (M_32). Не блокирует
        импорт при наличии исправлений — блокирует только при сбое построения
        (fail-closed, exception пробрасывается наверх).

        Args:
            layer: In-memory OGR-слой (до save_to_gpkg).
            layer_name: Имя слоя (для сообщений).

        Returns:
            Исправленный MultiPolygon memory-слой либо исходный слой as-is
            (если полигональной невалидности нет).
        """
        try:
            from .Fsm_1_1_15_geometry_validator import Fsm_1_1_15_GeometryValidator

            fixed_layer, stats = Fsm_1_1_15_GeometryValidator.validate_and_fix_layer(layer)

            invalid = stats.get('invalid', 0)
            zm_skipped = stats.get('zm_skipped', 0)
            if invalid > 0 or zm_skipped > 0:
                fixed = stats.get('fixed', 0)
                unfixable = stats.get('unfixable', 0)
                area_delta = stats.get('area_delta', 0.0)

                summary = (
                    f"Слой '{layer_name}': исправлено {fixed} из {invalid} "
                    f"невалидных геометрий (дельта площади {area_delta:.2f} м²)"
                )
                if unfixable > 0:
                    summary += f"; не исправлено: {unfixable} (перенесены как есть)"
                if zm_skipped > 0:
                    summary += f"; Z/M-геометрий пропущено: {zm_skipped} (перенесены как есть)"

                log_warning(f"Fsm_1_1_2: {summary}")

                # messageBar (не блокирует импорт)
                if self.iface is not None:
                    self.iface.messageBar().pushMessage(
                        "Исправлена геометрия",
                        summary,
                        level=Qgis.Warning if (unfixable > 0 or zm_skipped > 0) else Qgis.Info,
                        duration=8,
                    )

                # M_32 telemetry (best-effort, не ломает импорт)
                try:
                    from Daman_QGIS.managers import registry
                    telemetry = registry.get('M_32')
                    if telemetry is not None:
                        telemetry.track_event('geometry_fix_on_import', {
                            'func': 'F_1_1',
                            'format': 'TAB',
                            'checked': stats.get('checked', 0),
                            'invalid': invalid,
                            'fixed': fixed,
                            'unfixable': unfixable,
                            'zm_skipped': zm_skipped,
                        })
                except Exception:
                    pass

            return fixed_layer

        except Exception as e:
            # fail-closed: сбой валидатора блокирует импорт (геометрия-фикс
            # не должен молча пропустить невалидную геометрию).
            self.log_message(
                f"Fsm_1_1_2: сбой валидации/исправления геометрии слоя "
                f"'{layer_name}': {e}",
                Qgis.Critical,
            )
            raise

    def _apply_attributes_mapping(self, layer: QgsVectorLayer):
        """
        Применение маппинга атрибутов

        Args:
            layer: Слой для обработки
        """
        # Переименование полей согласно маппингу
        if not self.settings or not self.settings.attributes_mapping:
            return

        mapping = self.settings.attributes_mapping

        layer.startEditing()

        for old_name, new_name in mapping.items():
            field_idx = layer.fields().indexOf(old_name)
            if field_idx >= 0:
                layer.renameAttribute(field_idx, new_name)

        layer.commitChanges()

        self.log_message(f"Применен маппинг для {len(mapping)} атрибутов")

    def _create_buffer_layers(self, source_layer: QgsVectorLayer) -> None:
        """
        Создание буферных слоёв L_1_1_2/3/4 для L_1_1_1_Границы_работ.
        Делегирует в LayerProcessor.create_buffer_layers.
        """
        from ..core import LayerProcessor
        processor = LayerProcessor(self.project_manager, self.layer_manager)
        processor.create_buffer_layers(source_layer, self.log_message)
