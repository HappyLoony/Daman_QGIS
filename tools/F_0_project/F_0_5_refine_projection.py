# -*- coding: utf-8 -*-
"""
F_0_5_RefineProjection - Уточнение проекции через смещение x_0/y_0
Создает новую USER CRS с откалиброванными параметрами смещения
"""

from typing import Optional, Tuple, Set

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
import os
from datetime import datetime

from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsPointXY,
    QgsGeometry,
    QgsFeature,
    QgsVectorLayer,
    QgsCoordinateTransform,
    QgsApplication,
    Qgis
)
from qgis.gui import QgsMapTool, QgsMapToolEmitPoint, QgsSnapIndicator

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION
from Daman_QGIS.utils import log_info, log_error, log_warning, log_success


class F_0_5_RefineProjection(BaseTool):
    """
    Инструмент для уточнения проекции через определение смещения
    между опорными точками
    """
    
    def __init__(self, iface):
        """Инициализация инструмента"""
        super().__init__(iface)
        self.dialog = None
        self.map_tool = None
        
    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "F_0_5_Уточнение проекции"

    @property
    def icon(self) -> QIcon:
        """Иконка инструмента"""
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return QIcon(os.path.join(plugin_dir, "resources", "icons", "icon.svg"))
    
    def run(self) -> None:
        """Запуск инструмента"""
        # Проверка открытого проекта
        if not self.check_project_opened():
            return
            
        # Проверка CRS проекта на наличие параметров x_0 и y_0
        project_crs = QgsProject.instance().crs()
        if not self.validate_crs_params(project_crs):
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Проекция не содержит параметры +x_0 и +y_0. Уточнение невозможно.",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            log_error("F_0_5: Проекция не содержит +x_0 и +y_0")
            return
            
        # Создание и показ диалога
        self.create_dialog()

    def validate_crs_params(self, crs: QgsCoordinateReferenceSystem) -> bool:
        """Проверка наличия параметров x_0 и y_0 в CRS"""
        proj_string = crs.toProj()
        return "+x_0" in proj_string and "+y_0" in proj_string
        
    def create_dialog(self) -> None:
        """Создание диалога уточнения проекции"""
        from .submodules.Fsm_0_5_refine_dialog import RefineProjectionDialog
        
        # Создаем диалог
        self.dialog = RefineProjectionDialog(self.iface, self)
        
        # Позиционируем диалог сбоку
        self.position_dialog_aside()
        
        # Показываем диалог
        self.dialog.show()
        
        # Активируем инструмент захвата точек
        self.activate_map_tool()
        
    def position_dialog_aside(self) -> None:
        """Позиционирование диалога сбоку от главного окна"""
        if not self.dialog:
            return
            
        main_window = self.iface.mainWindow()
        main_geometry = main_window.geometry()
        
        # Размещаем диалог справа от главного окна
        dialog_x = main_geometry.x() + main_geometry.width() - self.dialog.width() - 50
        dialog_y = main_geometry.y() + 100
        
        self.dialog.move(dialog_x, dialog_y)
        
    def activate_map_tool(self) -> None:
        """Активация инструмента захвата точек"""
        if self.map_tool:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)
            
        self.map_tool = ProjectionRefineTool(self.iface.mapCanvas(), self)
        self.iface.mapCanvas().setMapTool(self.map_tool)
        
    def deactivate_map_tool(self) -> None:
        """Деактивация инструмента захвата точек"""
        if self.map_tool:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)
            self.map_tool = None
        
        # Восстанавливаем стандартный инструмент панорамирования
        self.iface.actionPan().trigger()
            
    def remove_preview_layer(self) -> None:
        """Заглушка для совместимости с диалогом"""
        pass
    def apply_projection_offset(
        self,
        delta_x: float,
        delta_y: float,
        object_layer_crs: Optional[QgsCoordinateReferenceSystem] = None,
        object_layer: Optional[QgsVectorLayer] = None
    ) -> bool:
        """Применение смещения и создание новой CRS (обычный режим)

        НОВЫЙ WORKFLOW (2024-12):
        - Смещение применяется к CRS слоя объекта (не Project CRS!)
        - Project CRS во время калибровки = EPSG:3857

        Args:
            delta_x: Смещение по X (метры)
            delta_y: Смещение по Y (метры)
            object_layer_crs: CRS слоя объекта (МСК) для модификации
            object_layer: Слой объекта для применения новой CRS
        """
        try:
            log_info("F_0_5: ПРИМЕНЕНИЕ СМЕЩЕНИЯ К ПРОЕКЦИИ (WKT2)")

            # Используем CRS слоя объекта (не Project CRS!)
            if object_layer_crs and object_layer_crs.isValid():
                current_crs = object_layer_crs
                log_info(f"F_0_5: Используется CRS слоя объекта: {current_crs.authid()}")
            else:
                current_crs = QgsProject.instance().crs()
                log_warning("F_0_5: object_layer_crs не указан, используется Project CRS")

            # Получаем WKT2 (ISO 19162:2019) - современный lossless формат
            wkt2_string = current_crs.toWkt(Qgis.CrsWktVariant.Wkt2_2019)

            log_info(f"F_0_5: Исходная WKT2 (первые 200 символов):")
            log_info(f"  {wkt2_string[:200]}...")

            # Обновляем параметры False easting/northing в WKT2
            updated_wkt2 = self.update_wkt2_params(wkt2_string, delta_x, delta_y)

            log_info(f"F_0_5: Применяемое смещение: dX={delta_x:+.4f}, dY={delta_y:+.4f}")

            # Создаём новую CRS из WKT2
            new_crs = QgsCoordinateReferenceSystem.fromWkt(updated_wkt2)
            if not new_crs.isValid():
                # Fallback на PROJ если WKT2 не сработал
                log_warning("F_0_5: WKT2 не сработал, пробуем PROJ fallback")
                proj_string = current_crs.toProj()
                updated_proj = self.update_proj4_params(proj_string, delta_x, delta_y)
                new_crs = QgsCoordinateReferenceSystem()
                if not new_crs.createFromProj(updated_proj):
                    raise RuntimeError("Не удалось создать CRS ни из WKT2, ни из PROJ")

            # Генерируем имя для новой CRS
            crs_name = self.generate_crs_name(current_crs)

            # Сохраняем как USER CRS через Registry API (QGIS 3.18+, WKT формат)
            registry = QgsApplication.coordinateReferenceSystemRegistry()
            srsid = registry.addUserCrs(new_crs, crs_name, Qgis.CrsDefinitionFormat.Wkt)

            if srsid == -1:
                raise RuntimeError("Не удалось сохранить пользовательскую CRS")

            # Очищаем кэш CRS
            QgsCoordinateReferenceSystem.invalidateCache()

            # Получаем сохранённую CRS по USER ID
            saved_crs = QgsCoordinateReferenceSystem(f"USER:{srsid}")

            log_info(f"F_0_5: Сохранена USER CRS (WKT): {crs_name} (USER:{srsid})")

            # Применяем setCrs() к слоям с калибруемой CRS.
            # Это переопределяет CRS БЕЗ пересчёта координат -
            # именно то, что нужно для калибровки: координаты правильные,
            # просто CRS была указана неверно.
            self.apply_crs_to_all_layers(saved_crs, old_crs=current_crs)

            # Сообщение об успехе
            self.iface.messageBar().pushMessage(
                "Успех",
                f"Создана и применена новая проекция: {crs_name}",
                level=Qgis.Success,
                duration=MESSAGE_INFO_DURATION
            )

            log_info(f"F_0_5: Создана новая CRS: {crs_name}")
            log_info(f"F_0_5: Смещение: ΔX={delta_x:.4f}, ΔY={delta_y:.4f}")

            return True

        except Exception as e:
            log_error(f"F_0_5: Ошибка применения смещения: {e}")
            self.iface.messageBar().pushMessage(
                "Ошибка",
                f"Не удалось создать проекцию: {str(e)}",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            return False

    def apply_custom_projection(
        self,
        params: dict,
        object_layer: Optional[QgsVectorLayer] = None,
        object_layer_crs: Optional[QgsCoordinateReferenceSystem] = None
    ) -> bool:
        """Применение кастомной проекции (межзональный режим)

        НОВЫЙ WORKFLOW (2024-12):
        1. Создаём уточнённую CRS
        2. Применяем к слою объекта (если указан)
        3. Устанавливаем как Project CRS

        Args:
            params: Словарь с параметрами:
                - lon_0: центральный меридиан
                - lat_0: широта начала отсчёта
                - k_0: масштабный коэффициент
                - x_0: false easting
                - y_0: false northing
                - ellps_param: параметр эллипсоида (+ellps=...)
                - towgs84_param: параметры трансформации (+towgs84=...)
            object_layer: Слой объекта для применения уточнённой CRS (опционально)
            object_layer_crs: CRS слоя объекта (для переопределения CRS слоёв)

        Returns:
            bool: True при успехе
        """
        try:
            log_info("F_0_5: Создание кастомной проекции (WKT2)")

            # Формируем PROJ строку (источник истины для параметров)
            proj_string = (
                f"+proj=tmerc "
                f"+lat_0={params['lat_0']:.6f} "
                f"+lon_0={params['lon_0']:.6f} "
                f"+k_0={params['k_0']:.8f} "
                f"+x_0={params['x_0']:.4f} "
                f"+y_0={params['y_0']:.4f} "
            )
            if params.get('ellps_param'):
                proj_string += f"{params['ellps_param']} "
            if params.get('towgs84_param'):
                proj_string += f"{params['towgs84_param']} "
            proj_string += "+units=m +no_defs"

            log_info(f"F_0_5: PROJ строка: {proj_string}")

            # Создаём CRS из PROJ
            temp_crs = QgsCoordinateReferenceSystem()
            if not temp_crs.createFromProj(proj_string):
                raise RuntimeError(f"Не удалось создать CRS из PROJ: {proj_string}")

            # Конвертируем в WKT2 (ISO 19162:2019) - lossless формат
            # QGIS/PROJ автоматически создаёт BOUNDCRS если есть +towgs84
            wkt2_string = temp_crs.toWkt(Qgis.CrsWktVariant.Wkt2_2019)

            log_info(f"F_0_5: WKT2 тип: {'BOUNDCRS' if 'BOUNDCRS' in wkt2_string else 'PROJCRS'}")
            log_info(f"F_0_5: WKT2 (первые 300 символов): {wkt2_string[:300]}...")

            # Создаём финальную CRS из WKT2
            new_crs = QgsCoordinateReferenceSystem.fromWkt(wkt2_string)

            if not new_crs.isValid():
                # Fallback: используем CRS созданную из PROJ напрямую
                log_warning("F_0_5: WKT2 fromWkt() не сработал, используем PROJ CRS")
                new_crs = temp_crs

            # Генерируем имя для кастомной CRS
            crs_name = self.generate_custom_crs_name()

            # Сохраняем как USER CRS через Registry API (QGIS 3.18+, WKT формат)
            registry = QgsApplication.coordinateReferenceSystemRegistry()
            srsid = registry.addUserCrs(new_crs, crs_name, Qgis.CrsDefinitionFormat.Wkt)

            if srsid == -1:
                raise RuntimeError("Не удалось сохранить пользовательскую CRS")

            # Очищаем кэш CRS
            QgsCoordinateReferenceSystem.invalidateCache()

            # Получаем сохранённую CRS по USER ID
            saved_crs = QgsCoordinateReferenceSystem(f"USER:{srsid}")

            # Применяем setCrs() к слоям с калибруемой CRS.
            # Это переопределяет CRS БЕЗ пересчёта координат -
            # именно то, что нужно для калибровки: координаты правильные,
            # просто CRS была указана неверно.
            self.apply_crs_to_all_layers(saved_crs, old_crs=object_layer_crs)

            # Сообщение об успехе
            self.iface.messageBar().pushMessage(
                "Успех",
                f"Создана кастомная проекция: {crs_name}",
                level=Qgis.Success,
                duration=MESSAGE_INFO_DURATION
            )

            log_success(f"F_0_5: Создана кастомная проекция: {crs_name}")
            log_info(f"F_0_5: lon_0={params['lon_0']:.6f}°, k_0={params['k_0']:.8f}")
            log_info(f"F_0_5: x_0={params['x_0']:.2f} м, y_0={params['y_0']:.2f} м")

            return True

        except Exception as e:
            log_error(f"F_0_5: Ошибка создания кастомной проекции: {e}")
            self.iface.messageBar().pushMessage(
                "Ошибка",
                f"Не удалось создать кастомную проекцию: {str(e)}",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            return False

    def generate_custom_crs_name(self) -> str:
        """
        Генерация имени для кастомной CRS
        Формат: Кастом_{РабочееНазвание}_{ИсходнаяПроекция}
        """
        # Получаем базовое имя как в обычном режиме
        current_crs = QgsProject.instance().crs()
        base_name = self.generate_crs_name(current_crs)
        
        # Добавляем префикс "Кастом_"
        return f"Кастом_{base_name}"
            
    def update_proj4_params(self, proj4_string: str, delta_x: float, delta_y: float) -> str:
        """Обновление параметров x_0 и y_0 в строке Proj4"""
        params = proj4_string.split()
        updated_params = []

        x0_found = False
        y0_found = False
        current_x0 = 0.0
        current_y0 = 0.0

        for param in params:
            if param.startswith("+x_0="):
                try:
                    current_x0 = float(param.split("=")[1])
                    new_x0 = current_x0 + delta_x
                    updated_params.append(f"+x_0={new_x0:.4f}")
                    x0_found = True
                    log_info(f"F_0_5: x_0: {current_x0:.4f} + ({delta_x:+.4f}) = {new_x0:.4f}")
                except (ValueError, IndexError) as e:
                    log_warning(f"F_0_5: Ошибка парсинга параметра +x_0: {param}, {e}")
                    updated_params.append(param)
            elif param.startswith("+y_0="):
                try:
                    current_y0 = float(param.split("=")[1])
                    new_y0 = current_y0 + delta_y
                    updated_params.append(f"+y_0={new_y0:.4f}")
                    y0_found = True
                    log_info(f"F_0_5: y_0: {current_y0:.4f} + ({delta_y:+.4f}) = {new_y0:.4f}")
                except (ValueError, IndexError) as e:
                    log_warning(f"F_0_5: Ошибка парсинга параметра +y_0: {param}, {e}")
                    updated_params.append(param)
            else:
                updated_params.append(param)

        # Если параметры не найдены, добавляем их
        if not x0_found:
            updated_params.append(f"+x_0={delta_x:.4f}")
            log_info(f"F_0_5: x_0 не найден, добавляем: {delta_x:.4f}")
        if not y0_found:
            updated_params.append(f"+y_0={delta_y:.4f}")
            log_info(f"F_0_5: y_0 не найден, добавляем: {delta_y:.4f}")

        return " ".join(updated_params)

    def update_wkt2_params(
        self,
        wkt2_string: str,
        delta_x: float,
        delta_y: float
    ) -> str:
        """Обновление параметров False easting/northing в WKT2 строке.

        WKT2 (ISO 19162:2019) использует формат:
        PARAMETER["False easting", 500000, LENGTHUNIT["metre", 1]]
        PARAMETER["False northing", 0, LENGTHUNIT["metre", 1]]

        Args:
            wkt2_string: WKT2 строка CRS
            delta_x: Смещение по X (False easting)
            delta_y: Смещение по Y (False northing)

        Returns:
            Обновлённая WKT2 строка
        """
        import re

        result = wkt2_string

        # Паттерн для False easting с учётом разных вариантов форматирования
        # Ищем: PARAMETER["False easting", <число>, ...]
        fe_pattern = r'(PARAMETER\s*\[\s*"False easting"\s*,\s*)(-?[\d.]+)(\s*,)'

        def replace_fe(match):
            prefix = match.group(1)
            current_value = float(match.group(2))
            suffix = match.group(3)
            new_value = current_value + delta_x
            log_info(f"F_0_5 [WKT2]: False easting: {current_value:.4f} + ({delta_x:+.4f}) = {new_value:.4f}")
            return f"{prefix}{new_value:.4f}{suffix}"

        result = re.sub(fe_pattern, replace_fe, result, flags=re.IGNORECASE)

        # Паттерн для False northing
        fn_pattern = r'(PARAMETER\s*\[\s*"False northing"\s*,\s*)(-?[\d.]+)(\s*,)'

        def replace_fn(match):
            prefix = match.group(1)
            current_value = float(match.group(2))
            suffix = match.group(3)
            new_value = current_value + delta_y
            log_info(f"F_0_5 [WKT2]: False northing: {current_value:.4f} + ({delta_y:+.4f}) = {new_value:.4f}")
            return f"{prefix}{new_value:.4f}{suffix}"

        result = re.sub(fn_pattern, replace_fn, result, flags=re.IGNORECASE)

        return result

    def build_wkt2_from_params(self, params: dict) -> str:
        """Построение WKT2 строки из параметров проекции.

        Создаёт PROJ строку, конвертирует в CRS через QGIS, и возвращает WKT2.
        Это гарантирует корректную структуру WKT2 (включая BOUNDCRS для towgs84).

        QGIS/PROJ автоматически создаёт правильную структуру:
        - Простой PROJCRS если нет towgs84
        - BOUNDCRS[SOURCECRS[PROJCRS[...]], TARGETCRS[WGS84], ABRIDGEDTRANSFORMATION[...]]
          если есть towgs84 параметры

        Args:
            params: Словарь с параметрами:
                - lon_0: центральный меридиан
                - lat_0: широта начала отсчёта
                - k_0: масштабный коэффициент
                - x_0: false easting
                - y_0: false northing
                - ellps_param: параметр эллипсоида (опционально)
                - towgs84_param: параметры трансформации (опционально)

        Returns:
            WKT2 строка для CRS (ISO 19162:2019)

        Raises:
            RuntimeError: если не удалось создать CRS
        """
        # Формируем PROJ строку
        proj_string = (
            f"+proj=tmerc "
            f"+lat_0={params['lat_0']:.6f} "
            f"+lon_0={params['lon_0']:.6f} "
            f"+k_0={params['k_0']:.8f} "
            f"+x_0={params['x_0']:.4f} "
            f"+y_0={params['y_0']:.4f} "
        )

        if params.get('ellps_param'):
            proj_string += f"{params['ellps_param']} "
        if params.get('towgs84_param'):
            proj_string += f"{params['towgs84_param']} "

        proj_string += "+units=m +no_defs"

        # Создаём временную CRS из PROJ
        temp_crs = QgsCoordinateReferenceSystem()
        if not temp_crs.createFromProj(proj_string):
            raise RuntimeError(f"Не удалось создать CRS из PROJ: {proj_string}")

        # QGIS/PROJ автоматически создаёт правильную WKT2 структуру:
        # - BOUNDCRS с ABRIDGEDTRANSFORMATION если есть +towgs84
        # - Простой PROJCRS если нет towgs84
        wkt2 = temp_crs.toWkt(Qgis.CrsWktVariant.Wkt2_2019)

        log_info(f"F_0_5: PROJ -> WKT2 конвертация выполнена")
        log_info(f"F_0_5: WKT2 тип: {'BOUNDCRS' if 'BOUNDCRS' in wkt2 else 'PROJCRS'}")

        return wkt2

    def generate_crs_name(self, base_crs: QgsCoordinateReferenceSystem) -> str:
        """
        Генерация имени для новой CRS в формате: {рабочее_имя}_{исходная_проекция}
        Пример: Эльбрус_МСК-07 Кабардино-Балкарская Республика
        При дубликатах: Эльбрус_(1)_МСК-07 Кабардино-Балкарская Республика
        """
        # Получаем метаданные проекта
        project = QgsProject.instance()

        # Читаем рабочее название из GeoPackage
        working_name = "Проект"  # Значение по умолчанию

        project_path = project.absolutePath()
        if project_path:
            from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
            structure_manager = get_project_structure_manager()
            structure_manager.project_root = project_path
            gpkg_path = structure_manager.get_gpkg_path(create=False)

            if gpkg_path and os.path.exists(gpkg_path):
                from Daman_QGIS.database.project_db import ProjectDB
                try:
                    db = ProjectDB(gpkg_path)
                    metadata = db.get_metadata('1_0_working_name')
                    if metadata and metadata.get('value'):
                        working_name = metadata['value']
                except Exception as e:
                    log_warning(f"F_0_5: Не удалось прочитать рабочее название из метаданных: {e}")

        # Получаем название исходной проекции
        base_projection_name = base_crs.description()
        if not base_projection_name:
            base_projection_name = base_crs.authid()

        # Формируем базовое имя: {рабочее_имя}_{исходная_проекция}
        base_name = f"{working_name}_{base_projection_name}"

        # Проверяем дубликаты и добавляем нумерацию при необходимости
        final_name = base_name
        counter = 1

        # Получаем список всех пользовательских CRS
        db_path = QgsApplication.qgisUserDatabaseFilePath()
        if os.path.exists(db_path):
            import sqlite3
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Ищем все CRS с похожим названием
            cursor.execute("SELECT description FROM tbl_srs WHERE description LIKE ?", (f"{working_name}_%{base_projection_name}%",))
            existing_names = [row[0] for row in cursor.fetchall()]
            conn.close()

            # Проверяем дубликаты и добавляем нумерацию в формате: Эльбрус_(1)_...
            while final_name in existing_names:
                final_name = f"{working_name}_({counter})_{base_projection_name}"
                counter += 1

        return final_name
        
    def _get_excluded_layer_names(self) -> Set[str]:
        """
        Получить список имён слоёв, которые не должны менять CRS

        Динамически загружает из Base_layers.json слои с creating_function="F_1_2_Загрузка Web карт".
        Эти слои хранятся в EPSG:3857 и не должны менять CRS при уточнении проекции.

        Returns:
            Set[str]: Множество имён слоёв для исключения
        """
        try:
            import os
            from Daman_QGIS.managers.submodules.Msm_4_6_layer_reference_manager import LayerReferenceManager

            # Получаем путь к папке reference
            from Daman_QGIS.constants import DATA_REFERENCE_PATH

            layer_ref_manager = LayerReferenceManager(DATA_REFERENCE_PATH)
            excluded_names = layer_ref_manager.get_layer_names_by_creating_function(
                "F_1_2_Загрузка Web карт"
            )

            log_info(f"F_0_5: Загружено {len(excluded_names)} слоёв-исключений из Base_layers.json")
            return set(excluded_names)

        except Exception as e:
            log_warning(f"F_0_5: Не удалось загрузить список исключений: {e}")
            # Fallback - пустой список, все слои будут обработаны
            return set()

    def _crs_matches(
        self,
        crs1: QgsCoordinateReferenceSystem,
        crs2: QgsCoordinateReferenceSystem
    ) -> bool:
        """Сравнение двух CRS.

        Использует встроенный оператор == класса QgsCoordinateReferenceSystem,
        который внутри использует OGR isSame() для надёжного сравнения.
        См: https://qgis.org/pyqgis/3.40/core/QgsCoordinateReferenceSystem.html
        """
        if not crs1.isValid() or not crs2.isValid():
            return False

        # QGIS == оператор использует OGR isSame() внутри
        return crs1 == crs2

    def apply_crs_to_all_layers(
        self,
        new_crs: QgsCoordinateReferenceSystem,
        old_crs: Optional[QgsCoordinateReferenceSystem] = None
    ) -> None:
        """Применение новой CRS к проекту и слоям.

        ЛОГИКА КАЛИБРОВКИ:
        Калибровка исправляет НЕПРАВИЛЬНО УКАЗАННУЮ CRS слоя.
        Координаты в слое УЖЕ правильные, просто CRS была определена неверно.
        Поэтому setCrs() - это ПРАВИЛЬНОЕ действие: мы говорим QGIS
        "эти координаты на самом деле в новой CRS, а не в старой".

        Args:
            new_crs: Новая (откалиброванная) CRS
            old_crs: Старая CRS слоёв которые нужно переопределить (опционально)
        """
        try:
            # Устанавливаем CRS для проекта
            QgsProject.instance().setCrs(new_crs)
            log_info(f"F_0_5: Project CRS установлена: {new_crs.authid()}")

            # Переопределяем CRS для слоёв с калибруемой CRS
            # Это НЕ трансформирует координаты - только меняет метаданные CRS
            if old_crs and old_crs.isValid():
                excluded_layers = self._get_excluded_layer_names()
                updated_count = 0
                updated_names = []

                for layer in QgsProject.instance().mapLayers().values():
                    if not isinstance(layer, QgsVectorLayer):
                        continue
                    if layer.name() in excluded_layers:
                        continue

                    layer_crs = layer.crs()
                    if not layer_crs.isValid():
                        continue

                    # Сравниваем CRS через QGIS API (учитывает все параметры)
                    if self._crs_matches(layer_crs, old_crs):
                        layer.setCrs(new_crs)
                        updated_count += 1
                        updated_names.append(layer.name())

                if updated_count > 0:
                    log_info(f"F_0_5: Переопределена CRS для {updated_count} слоёв: {', '.join(updated_names[:5])}"
                             + (f"... и ещё {updated_count - 5}" if updated_count > 5 else ""))

                    # Принудительно обновляем каждый изменённый слой
                    for layer in QgsProject.instance().mapLayers().values():
                        if layer.name() in updated_names:
                            layer.triggerRepaint()

            # Обновляем canvas
            self.iface.mapCanvas().refresh()

            # Обновляем метаданные проекта
            self.update_project_metadata(new_crs)

            # Сохраняем проект
            QgsProject.instance().write()

        except Exception as e:
            log_warning(f"F_0_5: Ошибка применения CRS: {str(e)}")
            
    def update_project_metadata(self, new_crs: QgsCoordinateReferenceSystem) -> None:
        """Обновление метаданных проекта с новой CRS в GeoPackage"""
        from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager

        project = QgsProject.instance()
        project_path = project.absolutePath()

        if not project_path:
            log_warning("F_0_5: Проект не сохранён, метаданные CRS не обновлены")
            return

        # Используем ProjectStructureManager для получения пути к GeoPackage
        structure_manager = get_project_structure_manager()
        structure_manager.project_root = project_path
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        if not gpkg_path or not os.path.exists(gpkg_path):
            log_warning(f"F_0_5: GeoPackage не найден (новая структура: .project/database/project.gpkg)")
            return

        try:
            from Daman_QGIS.database.project_db import ProjectDB
            from Daman_QGIS.core.crs_utils import extract_crs_short_name

            db = ProjectDB(gpkg_path)

            # Обновляем EPSG код если есть
            if new_crs.authid():
                db.set_metadata('1_4_crs_epsg', new_crs.authid(), 'EPSG код системы координат')

            # Обновляем WKT2 (ISO 19162:2019 - современный стандарт, lossless)
            wkt2 = new_crs.toWkt(Qgis.CrsWktVariant.Wkt2_2019)
            db.set_metadata('1_4_crs_wkt', wkt2, 'WKT2 представление CRS (ISO 19162:2019)')

            # Обновляем описание
            db.set_metadata('1_4_crs_description', new_crs.description(), 'Описание системы координат')

            # Обновляем короткое имя если возможно
            short_name = extract_crs_short_name(new_crs.description())
            if short_name:
                db.set_metadata('1_4_crs_short_name', short_name, 'Короткое название СК')

            log_info(f"F_0_5: Метаданные CRS обновлены в GeoPackage (WKT2): {short_name or new_crs.description()}")

        except Exception as e:
            log_warning(f"F_0_5: Ошибка обновления метаданных CRS: {e}")


class ProjectionRefineTool(QgsMapToolEmitPoint):
    """Инструмент для захвата точек уточнения проекции (версия 2.0 для таблицы)"""

    def __init__(self, canvas, parent_tool):
        super().__init__(canvas)
        self.canvas = canvas
        self.parent_tool = parent_tool

        # Сохраняем текущую конфигурацию привязки
        self.old_snapping_config = None

        # Индикатор привязки
        self.snap_indicator = QgsSnapIndicator(canvas)

        # Устанавливаем курсор
        self.setCursor(Qt.CrossCursor)

    def activate(self):
        """Активация инструмента"""
        super().activate()
        self.setup_snapping()

    def setup_snapping(self):
        """Настройка привязки к вершинам"""
        from qgis.core import QgsSnappingConfig, QgsTolerance, QgsProject

        # Получаем проектную конфигурацию привязки
        project = QgsProject.instance()
        config = project.snappingConfig()

        # Сохраняем старую конфигурацию
        self.old_snapping_config = QgsSnappingConfig(config)

        # Модифицируем конфигурацию для привязки к вершинам
        config.setEnabled(True)
        config.setType(QgsSnappingConfig.VertexFlag)
        config.setMode(QgsSnappingConfig.AllLayers)
        config.setTolerance(10)
        config.setUnits(QgsTolerance.Pixels)

        # Применяем конфигурацию к проекту
        project.setSnappingConfig(config)

    def canvasMoveEvent(self, event):
        """Показ индикатора привязки при движении мыши"""
        match = self.canvas.snappingUtils().snapToMap(event.pos())
        self.snap_indicator.setMatch(match)

    def canvasReleaseEvent(self, event):
        """Обработка клика на карте - передаем точку в диалог"""
        # Проверяем snapping
        match = self.canvas.snappingUtils().snapToMap(event.pos())

        if match.isValid():
            point = QgsPointXY(match.point())
        else:
            # Если привязка не сработала, используем обычные координаты
            point = self.toMapCoordinates(event.pos())

        # Передаем точку в диалог
        if self.parent_tool.dialog:
            # Проверяем тип диалога и вызываем соответствующий метод
            if hasattr(self.parent_tool.dialog, 'set_point_from_map'):
                # Режим 1: RefineProjectionDialog
                self.parent_tool.dialog.set_point_from_map(point)
            elif hasattr(self.parent_tool.dialog, 'add_point_from_map'):
                # Режим 2: CustomProjectionBuilderDialog (расширенный режим)
                self.parent_tool.dialog.add_point_from_map(point)

    def deactivate(self):
        """Деактивация инструмента"""
        # Очищаем индикатор
        from qgis.core import QgsPointLocator
        self.snap_indicator.setMatch(QgsPointLocator.Match())

        # Восстанавливаем старую конфигурацию привязки
        if self.old_snapping_config is not None:
            from qgis.core import QgsProject
            QgsProject.instance().setSnappingConfig(self.old_snapping_config)
        super().deactivate()
