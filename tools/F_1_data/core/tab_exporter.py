# -*- coding: utf-8 -*-
"""
Экспортер в формат MapInfo TAB.

## КРИТИЧЕСКАЯ ОСОБЕННОСТЬ: precision = BOUNDS / 2*10^9

MapInfo TAB хранит координаты как 32-bit integer относительно header
BOUNDS (xmin, ymin, xmax, ymax). Шаг квантования = (xmax - xmin) / 2*10^9.
Дефолт OGR для projected CRS = ±30M / ±15M → шаг 30 мм / 15 мм, что
ХУЖЕ кадастровой точности 0.01 м.

Решение: для МСК передаём DEFAULT_BOUNDS = "-1M, -1M, 19M, 19M"
(extent 20M квадрат → шаг ровно 0.01 м). Координаты, уже округлённые
до 0.01 м (PRECISION_DECIMALS=2), попадают на сетку TAB бит-в-бит,
без сдвига.

## ДВЕ ВЕТКИ ЗАПИСИ

`_export_layer` диспетчит:
- МСК / любая локальная CRS (USER:* без EPSG-кода) → `_export_to_tab_gdal`
  через OGR с BOUNDS=-1M..19M и Nonearth coordsys (нулевой сдвиг).
- Географическая CRS (WGS-84, isGeographic=True) → `writeAsVectorFormatV3`
  с дефолтным OGR BOUNDS (180°/90°) — на широте 60° шаг ≈ 2-4 см.
  Используется в `create_wgs84=True` ветке для копии в WGS-84 (для KML,
  Google Earth и т.п., не для кадастровых документов).

Критерий ветвления — см. `_is_local_crs`.

## ИНВАРИАНТ ПОРЯДКА ВЕРШИН

OGR драйвер `MapInfo File` пишет геометрию КАК ЕСТЬ (порядок vertex_idx
не меняет). Если геометрия в gpkg нормализована (CW + начало с СЗ —
см. Fsm_5_3_1_CoordinateList._normalize_layer_geometry_cw_from_nw для
требования КГА СПб), TAB унаследует этот порядок. Иначе — порядок
исходного TAB-импорта.

## ГАРАНТИИ ДЛЯ КАДАСТРА

- Координаты в МСК ветке: 0 мкм сдвига (проверено на 5348 точках).
- Замыкание полигональных колец сохраняется.
- Mapinfo стиль (Brush/Pen) применяется через `_apply_mapinfo_style_post`,
  т.к. OGR не пишет style_MapInfo при создании TAB.
"""

import os
from typing import List, Dict, Any, Optional
from osgeo import ogr, osr

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsVectorFileWriter,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsMessageLog, Qgis, QgsWkbTypes
)

from .base_exporter import BaseExporter
from Daman_QGIS.managers import get_reference_managers
from Daman_QGIS.constants import PLUGIN_NAME, PRECISION_DECIMALS
from Daman_QGIS.utils import log_info, log_warning, log_error


class TabExporter(BaseExporter):
    """
    Экспортер в формат MapInfo TAB.

    Полный обзор архитектуры (precision/BOUNDS/две ветки записи) — в
    module-level docstring выше. Краткое:

    - Для МСК (locally-defined CRS, USER:* без EPSG) → NonEarth GDAL
      ветка с BOUNDS=-1M..19M → шаг ровно 0.01 м → нулевой сдвиг.
    - Для WGS-84 → QGIS writeAsVectorFormatV3 с дефолтным OGR BOUNDS
      (180°/90°) → шаг 2-4 см на широте СПб.
    - Порядок вершин не модифицируется — наследуется из QGIS-геометрии.
    """
    
    def __init__(self, iface=None):
        """Инициализация экспортера TAB"""
        super().__init__(iface)
        
        # Дополнительные параметры для TAB
        self.default_params.update({
            'create_wgs84': True,  # Создавать ли файл в WGS-84
            'use_non_earth': True,  # Использовать Non-Earth для МСК
            'clean_temp_files': True,  # Удалять временные MIF файлы
            'bounds': None,  # Bounds для NonEarth (None = default)
        })
        
        # Инициализируем reference_manager для стилей
        self.ref_managers = get_reference_managers()
    
    def export_layers(self, 
                     layers: List[QgsVectorLayer],
                     output_folder: str,
                     **params) -> Dict[str, bool]:
        """
        Экспорт слоев в TAB файлы
        
        Args:
            layers: Список слоев для экспорта
            output_folder: Папка назначения
            **params: Параметры экспорта
            
        Returns:
            Словарь {layer_name: success}
        """
        # Объединяем параметры
        export_params = self.merge_params(**params)
        
        # Сохраняем последнюю папку
        self.set_last_export_folder(output_folder)
        
        results = {}
        total_layers = len(layers)
        
        for idx, layer in enumerate(layers):
            if not isinstance(layer, QgsVectorLayer):
                results[layer.name()] = False
                continue
            
            # Прогресс
            progress = int((idx + 1) * 100 / total_layers)
            self.progress.emit(progress)
            
            # Экспортируем слой
            success = self._export_layer(layer, output_folder, export_params)
            results[layer.name()] = success
            
            if success:
                self.message.emit(f"Экспортирован: {layer.name()}")
            else:
                self.message.emit(f"Ошибка экспорта: {layer.name()}")
        
        return results
    def _export_layer(self,
                     layer: QgsVectorLayer,
                     output_folder: str,
                     params: Dict[str, Any]) -> bool:
        """
        Экспорт одного слоя в TAB — ДИСПЕТЧЕР между двумя ветками записи.

        Логика выбора (см. module-docstring):
        - `use_non_earth=True` (дефолт) И `_is_local_crs(target_crs)=True`
          → `_export_to_tab_gdal` с DEFAULT_BOUNDS=-1M..19M (precision 0.01 м).
        - Иначе → `writeAsVectorFormatV3` с дефолтным OGR BOUNDS
          (для географических CRS, precision 2-4 см на широте СПб).

        Args:
            layer: Слой для экспорта
            output_folder: Папка назначения
            params: Параметры экспорта (use_non_earth, bounds, create_wgs84,
                    clean_temp_files)

        Returns:
            True если успешно
        """
        # Получаем стиль MapInfo из Base_layers.json
        mapinfo_style = None
        layer_info = self.ref_managers.layer.get_layer_by_full_name(layer.name())
        if layer_info and layer_info.get('style_MapInfo') and layer_info['style_MapInfo'] != '-':
            mapinfo_style = layer_info['style_MapInfo']
            log_info(
                f"Найден стиль MapInfo для слоя {layer.name()}: {mapinfo_style}"
            )

        # Получаем информацию о СК
        crs_short_name, project_crs = self.get_project_crs_info()

        # Форматируем имя файла
        filename = self.format_filename(
            layer,
            params.get('filename_pattern')
        )

        # Экспортируем в СК проекта
        tab_path = os.path.join(output_folder, f"{filename}.tab")
        success = self._export_to_tab(
            layer,
            tab_path,
            project_crs,
            params,
            mapinfo_style
        )

        if not success:
            return False

        # Экспортируем в WGS-84 если нужно
        if params.get('create_wgs84', True):
            wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")

            # Для WGS84 файла убираем короткое название СК из имени
            # Проверяем, есть ли короткое название СК в имени файла
            crs_underscore = crs_short_name.replace(' ', '_') if crs_short_name else None
            if crs_short_name and (crs_short_name in filename or (crs_underscore and crs_underscore in filename)):
                # Убираем короткое название СК и возможные разделители
                wgs84_filename = filename.replace(f"_{crs_short_name.replace(' ', '_')}", "")
                wgs84_filename = wgs84_filename.replace(f"_{crs_short_name}", "")
                wgs84_filename = wgs84_filename.replace(crs_short_name.replace(' ', '_'), "")
                wgs84_filename = wgs84_filename.replace(crs_short_name, "")
                # Убираем двойные подчеркивания если появились
                wgs84_filename = wgs84_filename.replace("__", "_")
                # Убираем подчеркивание в конце если есть
                if wgs84_filename.endswith("_"):
                    wgs84_filename = wgs84_filename[:-1]
            else:
                wgs84_filename = filename

            # Добавляем суффикс WGS84
            wgs84_filename = f"{wgs84_filename}_WGS84"
            wgs84_path = os.path.join(output_folder, f"{wgs84_filename}.tab")

            success = self._export_to_tab(
                layer,
                wgs84_path,
                wgs84_crs,
                params,
                mapinfo_style
            )

        return success
    def _export_to_tab(self,
                      layer: QgsVectorLayer,
                      output_path: str,
                      target_crs: QgsCoordinateReferenceSystem,
                      params: Dict[str, Any],
                      mapinfo_style: Optional[str] = None) -> bool:
        """
        Экспорт в TAB

        Args:
            layer: Слой для экспорта
            output_path: Путь к выходному TAB файлу
            target_crs: Целевая СК
            params: Параметры экспорта

        Returns:
            True если успешно
        """
        # Нормализуем путь
        output_path = os.path.normpath(output_path)

        log_info(
            f"Начинаем экспорт в TAB: {output_path}"
        )

        # Проверяем является ли СК местной (МСК)
        is_local_crs = self._is_local_crs(target_crs)

        # Если это МСК и нужен Non-Earth - используем GDAL
        if params.get('use_non_earth', True) and is_local_crs:
            return self._export_to_tab_gdal(
                layer, output_path, target_crs, mapinfo_style,
                bounds=params.get('bounds')
            )

        # Иначе используем стандартный экспорт QGIS (для WGS-84 и других географических СК)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "MapInfo File"
        options.fileEncoding = "cp1251"

        # Добавляем трансформацию если нужно
        if layer.crs() != target_crs:
            transform = QgsCoordinateTransform(
                layer.crs(),
                target_crs,
                QgsProject.instance()
            )
            options.ct = transform

        # Экспортируем напрямую в TAB
        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            output_path,
            QgsProject.instance().transformContext(),
            options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Ошибка экспорта в TAB: {error[1]}")

        # QgsVectorFileWriter не записывает MapInfo style_MapInfo при создании TAB.
        # Если стиль задан — открываем файл через OGR и проставляем SetStyleString
        # каждой фиче (тот же механизм, что в GDAL/Nonearth ветке).
        if mapinfo_style:
            self._apply_mapinfo_style_post(output_path, mapinfo_style)

        log_info(
            f"TAB файл создан: {output_path}"
        )

        return True

    def _apply_mapinfo_style_post(self, tab_path: str, mapinfo_style: str) -> None:
        """
        Применить MapInfo стиль ко всем фичам уже созданного TAB файла.

        QgsVectorFileWriter создаёт TAB без style_MapInfo. Чтобы стиль
        попал в файл, открываем его через OGR в режиме update и проставляем
        SetStyleString каждой фиче. Используется тот же подход, что в
        _export_to_tab_gdal (там стиль применяется при первичной записи).

        Args:
            tab_path: Путь к TAB файлу
            mapinfo_style: Строка MapInfo стиля, например
                "Brush(2,16777215,0) Pen(1,2,0)"
        """
        driver = ogr.GetDriverByName('MapInfo File')
        if driver is None:
            log_warning(
                f"TabExporter: драйвер 'MapInfo File' недоступен — "
                f"стиль не применён к {tab_path}"
            )
            return

        ds = driver.Open(tab_path, 1)  # 1 = update mode
        if ds is None:
            log_warning(
                f"TabExporter: не удалось открыть {tab_path} для применения стиля"
            )
            return

        try:
            lyr = ds.GetLayer(0)
            if lyr is None:
                log_warning(f"TabExporter: слой не найден в {tab_path}")
                return

            applied = 0
            feat = lyr.GetNextFeature()
            while feat is not None:
                feat.SetStyleString(mapinfo_style)
                lyr.SetFeature(feat)
                feat = lyr.GetNextFeature()
                applied += 1

            log_info(
                f"TabExporter: MapInfo стиль применён к {applied} фичам в {tab_path}"
            )
        finally:
            ds = None  # release OGR DataSource (flush + close)
    
    def _is_local_crs(self, crs: QgsCoordinateReferenceSystem) -> bool:
        """
        Проверка является ли СК местной (МСК) — определяет ветку TAB-записи.

        КРИТЕРИИ (по приоритету):
        1. Описание/authid содержит 'мск'/'местная'/'local'/'гск' → True
           (явные МСК и ГСК-2011).
        2. CRS isGeographic → False (LAT/LON исключаем — пойдут через
           writeAsVectorFormatV3 в WGS-84 ветку).
        3. authid пустой ИЛИ не начинается с 'EPSG:' → True
           (USER:NNNNN, любые custom WKT CRS — почти всегда локальные).
        4. EPSG:* (стандартная проекция, не из ключевых слов) → False.

        Возвращая True → попадаем в `_export_to_tab_gdal` с BOUNDS=-1M..19M
        и Nonearth coordsys (precision 0.01 м, нулевой сдвиг для МСК).

        Прецедент: СК-1964 Санкт-Петербург обычно регистрируется как
        USER:NNNNN (без EPSG-кода) → пункт 3 даёт True → правильная NonEarth
        ветка. Не путать с EPSG:7846 (ГСК-2011), где работает пункт 1.

        Args:
            crs: Система координат

        Returns:
            True если СК трактуется как МСК/локальная (NonEarth ветка)
        """
        # Проверяем по названию
        description = crs.description().lower() if crs.description() else ""
        auth_id = crs.authid().lower() if crs.authid() else ""
        
        # МСК обычно содержат эти ключевые слова
        msk_keywords = ['мск', 'местная', 'local', 'гск']
        
        for keyword in msk_keywords:
            if keyword in description or keyword in auth_id:
                return True
        
        # Также проверяем что это не стандартная географическая СК
        if crs.isGeographic():
            return False
        
        # Если EPSG код отсутствует или нестандартный - возможно МСК
        if not crs.authid() or not crs.authid().startswith('EPSG:'):
            return True
        
        return False
    # Bounds по умолчанию для NonEarth — покрывают все МСК России И дают
    # шаг квантования ровно 0.01 м (extent 20M по обеим осям, делёный
    # на 2*10^9 значений integer-сетки MapInfo TAB).
    # Формула шага: (xmax - xmin) / 2*10^9 = 20*10^6 / 2*10^9 = 0.01 м.
    # Любая координата уже округлённая до 0.01 м (PRECISION_DECIMALS=2)
    # ложится на узел сетки без сдвига.
    DEFAULT_BOUNDS = "-1000000,-1000000,19000000,19000000"

    def _export_to_tab_gdal(self, layer: QgsVectorLayer, output_path: str, target_crs: QgsCoordinateReferenceSystem, mapinfo_style: Optional[str] = None, bounds: Optional[str] = None) -> bool:
        """
        Создаёт TAB файл с Nonearth проекцией через GDAL.

        Используется для МСК-CRS (ветка определена в `_export_layer` через
        `_is_local_crs`). Записывает TAB через OGR-драйвер `MapInfo File`
        с явным `BOUNDS=...` в layer options.

        КРИТИЧНО: BOUNDS определяет precision хранения координат
        (шаг = (xmax - xmin) / 2*10^9). При DEFAULT_BOUNDS extent 20M →
        шаг 0.01 м = кадастровая точность. Координаты, округлённые до
        0.01 м, пишутся бит-в-бит (0 мкм сдвиг).

        Args:
            layer: Слой для экспорта (QgsVectorLayer)
            output_path: Путь к выходному TAB файлу
            target_crs: Целевая СК (QgsCoordinateReferenceSystem)
            mapinfo_style: Стиль MapInfo для применения
            bounds: Bounds для NonEarth (например '0,0,200000,200000').
                    None = DEFAULT_BOUNDS

        Returns:
            bool: Успешно ли создан TAB файл
        """
        # Создаем драйвер MapInfo
        driver = ogr.GetDriverByName('MapInfo File')
        if not driver:
            raise RuntimeError("Драйвер MapInfo File не найден в GDAL")

        # Удаляем существующий файл если есть
        if os.path.exists(output_path):
            driver.DeleteDataSource(output_path)

        # Создаем DataSource
        ds = driver.CreateDataSource(output_path)
        if not ds:
            raise RuntimeError(f"Не удалось создать TAB файл: {output_path}")

        # Создаем Nonearth координатную систему
        srs = osr.SpatialReference()
        srs.SetLocalCS("Nonearth")
        srs.SetLinearUnits("metre", 1.0)

        # Определяем тип геометрии
        geom_type = layer.wkbType()

        # Mixed: wkbType может быть Polygon после GPKG save (QgsVectorFileWriter меняет Unknown -> Polygon)
        # Проверяем: custom property (надёжно) + fallback на wkbType
        flat = QgsWkbTypes.flatType(geom_type)
        is_mixed = (
            layer.customProperty('daman_mixed_geometry', False)
            or flat in (Qgis.WkbType.GeometryCollection, Qgis.WkbType.Unknown)
        )

        if not is_mixed and (QgsWkbTypes.hasM(geom_type) or QgsWkbTypes.hasZ(geom_type)):
            geom_type = QgsWkbTypes.to25D(geom_type)

        # Конвертируем тип геометрии QGIS в OGR
        if is_mixed:
            ogr_geom_type = ogr.wkbUnknown
        elif geom_type in [Qgis.WkbType.LineString, Qgis.WkbType.MultiLineString]:
            ogr_geom_type = ogr.wkbLineString
        elif geom_type in [Qgis.WkbType.Polygon, Qgis.WkbType.MultiPolygon]:
            ogr_geom_type = ogr.wkbPolygon
        elif geom_type in [Qgis.WkbType.Point, Qgis.WkbType.MultiPoint]:
            ogr_geom_type = ogr.wkbPoint
        else:
            ogr_geom_type = ogr.wkbUnknown

        # Создаем слой с Nonearth и границами
        bounds_str = bounds if bounds else self.DEFAULT_BOUNDS
        lyr = ds.CreateLayer(
            'layer1',
            srs,
            ogr_geom_type,
            options=[f'BOUNDS={bounds_str}', 'ENCODING=cp1251']
        )

        if not lyr:
            raise RuntimeError("Не удалось создать слой в TAB файле")

        # Добавляем поля из исходного слоя (fid — внутреннее поле GPKG, пропускаем)
        export_field_indices = []
        for idx, field in enumerate(layer.fields()):
            field_name = field.name()
            field_type = field.typeName().upper()

            if field_name == 'fid' and 'INT' in field_type:
                log_info(f"TAB export: поле '{field_name}' пропущено (GPKG internal)")
                continue

            export_field_indices.append(idx)

            # Конвертируем типы полей QGIS в OGR
            if 'INT' in field_type:
                ogr_field = ogr.FieldDefn(field_name, ogr.OFTInteger)
            elif 'REAL' in field_type or 'DOUBLE' in field_type:
                ogr_field = ogr.FieldDefn(field_name, ogr.OFTReal)
            else:
                ogr_field = ogr.FieldDefn(field_name, ogr.OFTString)
                if field.length() > 0:
                    ogr_field.SetWidth(field.length())

            lyr.CreateField(ogr_field)

        # Создаем трансформацию координат если нужно
        transform = None
        if layer.crs() != target_crs:
            transform = QgsCoordinateTransform(
                layer.crs(),
                target_crs,
                QgsProject.instance()
            )

        # Экспортируем features
        exported_count = 0
        skipped_count = 0

        for qgs_feature in layer.getFeatures():
            geom = qgs_feature.geometry()
            if not geom or geom.isEmpty():
                skipped_count += 1
                continue

            # Трансформируем геометрию если нужно
            if transform:
                geom.transform(transform)

            # Округляем координаты до 0.01м (PRECISION_DECIMALS = 2)
            # Обязательно до конвертации в WKT, иначе MapInfo
            # при узких Bounds сохранит избыточную точность
            grid_size = 10 ** (-PRECISION_DECIMALS)  # 0.01
            geom = geom.snappedToGrid(grid_size, grid_size)

            # Mixed слои: замкнутые LineString -> Polygon
            if is_mixed:
                geom = self._promote_closed_lines(geom, qgs_feature.id())

            # Создаем OGR feature
            ogr_feature = ogr.Feature(lyr.GetLayerDefn())

            # Копируем атрибуты (только экспортируемые поля, без fid)
            all_attrs = qgs_feature.attributes()
            for ogr_idx, qgs_idx in enumerate(export_field_indices):
                if qgs_idx < len(all_attrs):
                    attr = all_attrs[qgs_idx]
                    if attr is not None:
                        if isinstance(attr, (int, float)):
                            ogr_feature.SetField(ogr_idx, attr)
                        else:
                            ogr_feature.SetField(ogr_idx, str(attr))

            # Конвертируем геометрию из QGIS в OGR
            wkt = geom.asWkt()
            ogr_geom = ogr.CreateGeometryFromWkt(wkt)

            if ogr_geom:
                ogr_feature.SetGeometry(ogr_geom)

                # Применяем стиль MapInfo если он задан
                if mapinfo_style:
                    ogr_feature.SetStyleString(mapinfo_style)

                # Добавляем feature в слой
                lyr.CreateFeature(ogr_feature)
                exported_count += 1

            # Освобождаем ресурсы
            ogr_feature = None

        # Закрываем DataSource
        ds = None

        log_info(f"TAB export: '{layer.name()}' exported={exported_count}, skipped={skipped_count}")

        if mapinfo_style:
            log_info(
                f"TAB файл с Nonearth и стилем MapInfo создан: {output_path}"
            )
        else:
            log_info(
                f"TAB файл с Nonearth создан через GDAL: {output_path}"
            )

        return True

    def _promote_closed_lines(self, geom, feature_id=None):
        """
        Для Mixed слоёв: замкнутые LineString конвертируются в Polygon.

        Замкнутая полилиния (первая точка == последняя) по сути является
        контуром полигона. MapInfo TAB различает pline и region —
        замкнутые контуры должны быть region (Polygon).

        Args:
            geom: QgsGeometry
            feature_id: ID фичи для логирования

        Returns:
            QgsGeometry (Polygon если была замкнутая линия, иначе без изменений)
        """
        from qgis.core import QgsGeometry, QgsWkbTypes

        flat_type = QgsWkbTypes.flatType(geom.wkbType())

        # Одиночная LineString
        if flat_type == Qgis.WkbType.LineString:
            points = geom.asPolyline()
            if len(points) >= 4 and points[0] == points[-1]:
                polygon = QgsGeometry.fromPolygonXY([points])
                log_info(
                    f"Fsm_1_5_7: feature {feature_id} — "
                    f"замкнутая LineString ({len(points)} точек) -> Polygon"
                )
                return polygon

        # MultiLineString — каждую часть проверяем
        elif flat_type == Qgis.WkbType.MultiLineString:
            lines = geom.asMultiPolyline()
            polygons = []
            remaining_lines = []
            for line in lines:
                if len(line) >= 4 and line[0] == line[-1]:
                    polygons.append([line])
                else:
                    remaining_lines.append(line)

            if polygons and not remaining_lines:
                # Все части замкнуты — MultiPolygon
                result = QgsGeometry.fromMultiPolygonXY(polygons)
                log_info(
                    f"Fsm_1_5_7: feature {feature_id} — "
                    f"MultiLineString ({len(polygons)} замкнутых) -> MultiPolygon"
                )
                return result
            elif polygons:
                log_info(
                    f"Fsm_1_5_7: feature {feature_id} — "
                    f"MultiLineString: {len(polygons)} замкнутых, "
                    f"{len(remaining_lines)} открытых — оставляем как есть"
                )

        return geom

