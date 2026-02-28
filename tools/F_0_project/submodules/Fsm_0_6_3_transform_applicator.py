# -*- coding: utf-8 -*-
"""
Fsm_0_6_3 - Применение трансформации к слою

Backup/restore/apply координатной трансформации с:
- Файловым backup GPKG перед commitChanges
- Округлением через M_6._round_geometry() (3 edge cases)
- Пост-валидацией геометрий (isGeosValid)
"""

import os
import shutil
from typing import Dict, List, Tuple, Optional

from qgis.core import (
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsCoordinateTransformContext,
    QgsGeometry,
    QgsAbstractGeometryTransformer,
    QgsFeature,
    QgsPointXY,
    QgsWkbTypes,
    QgsProject,
)

from .Fsm_0_6_2_transform_methods import BaseTransformMethod, TransformResult
from Daman_QGIS.managers.geometry.M_6_coordinate_precision import CoordinatePrecisionManager
from Daman_QGIS.utils import log_info, log_error, log_warning


class TransformApplicator:
    """
    Применение координатной трансформации к векторному слою.

    Обеспечивает:
    - Backup геометрий в памяти (для быстрого rollback)
    - Файловый backup GPKG (для защиты от crash)
    - Округление координат до 0.01м через M_6
    - Пост-валидацию результата
    """

    @staticmethod
    def backup_layer(layer: QgsVectorLayer) -> Dict[int, QgsGeometry]:
        """
        Сохранить геометрии всех фич для возможного rollback.

        Parameters:
            layer: Векторный слой

        Returns:
            Dict[feature_id, QgsGeometry] - копии геометрий
        """
        backup: Dict[int, QgsGeometry] = {}
        for feature in layer.getFeatures():
            if feature.hasGeometry():
                backup[feature.id()] = QgsGeometry(feature.geometry())
        log_info(f"Fsm_0_6_3: Backup {len(backup)} геометрий")
        return backup

    @staticmethod
    def apply_transform(
        layer: QgsVectorLayer,
        method: BaseTransformMethod
    ) -> Tuple[bool, List[str]]:
        """
        Применить трансформацию ко всем фичам слоя.

        Порядок:
        1. Файловый backup GPKG (.bak)
        2. startEditing
        3. Для каждой фичи: transform -> round (M_6) -> changeGeometry
        4. commitChanges
        5. Удалить .bak при успехе

        Parameters:
            layer: Векторный слой для трансформации
            method: Метод трансформации (уже с рассчитанными параметрами)

        Returns:
            (success, warnings) - результат и список предупреждений
        """
        warnings: List[str] = []

        # Начинаем редактирование ПЕРЕД файловым backup
        # (shutil.copy2 на GPKG с активным SQLite WAL может заблокировать файл)
        already_editing = layer.isEditable()
        if already_editing:
            log_info("Fsm_0_6_3: Слой уже в режиме редактирования")
        else:
            if not layer.startEditing():
                # Диагностика причины отказа
                caps = layer.dataProvider().capabilities() if layer.dataProvider() else 0
                can_change = bool(caps & layer.dataProvider().ChangeGeometries) if layer.dataProvider() else False
                log_error(
                    f"Fsm_0_6_3: Не удалось начать редактирование слоя. "
                    f"Provider={layer.providerType()}, "
                    f"source={layer.source()}, "
                    f"readOnly={layer.readOnly()}, "
                    f"canChangeGeom={can_change}"
                )
                return (False, [
                    f"Не удалось начать редактирование слоя '{layer.name()}'. "
                    f"Проверьте: слой не заблокирован, провайдер поддерживает редактирование "
                    f"(provider={layer.providerType()}, readOnly={layer.readOnly()})"
                ])

        # Файловый backup GPKG (после startEditing, чтобы не блокировать WAL)
        gpkg_path = _get_gpkg_path(layer)
        bak_path = None
        if gpkg_path:
            bak_path = gpkg_path + '.bak'
            try:
                shutil.copy2(gpkg_path, bak_path)
                # Копируем WAL и SHM если есть (SQLite WAL mode)
                for ext in ['-wal', '-shm']:
                    wal_path = gpkg_path + ext
                    if os.path.exists(wal_path):
                        shutil.copy2(wal_path, bak_path + ext)
                log_info(f"Fsm_0_6_3: GPKG backup создан: {bak_path}")
            except OSError as e:
                log_warning(f"Fsm_0_6_3: Не удалось создать backup GPKG: {e}")
                bak_path = None

        transform_count = 0
        round_fallback_count = 0
        invalid_count = 0

        try:
            for feature in layer.getFeatures():
                if not feature.hasGeometry():
                    continue

                geom = feature.geometry()
                fid = feature.id()

                # Трансформация через transformVertices
                new_geom = _transform_geometry(geom, method)
                if new_geom is None:
                    warnings.append(f"Фича {fid}: не удалось трансформировать")
                    continue

                # Округление через M_6 (обработка 3 edge cases)
                rounded_geom = CoordinatePrecisionManager._round_geometry(new_geom)
                if rounded_geom is None:
                    log_warning(f"Fsm_0_6_3: Фича {fid}: M_6 вернул None, используем без округления")
                    rounded_geom = new_geom
                    round_fallback_count += 1

                # Проверка валидности
                if not rounded_geom.isGeosValid():
                    invalid_count += 1

                layer.changeGeometry(fid, rounded_geom)
                transform_count += 1

            # Commit
            if not layer.commitChanges():
                commit_errors = layer.commitErrors()
                error_msg = "; ".join(commit_errors) if commit_errors else "неизвестная ошибка"
                log_error(f"Fsm_0_6_3: Ошибка commit: {error_msg}")
                layer.rollBack()
                # Восстановить из файлового backup
                if bak_path and os.path.exists(bak_path):
                    _restore_from_bak(gpkg_path, bak_path)
                return (False, [f"Ошибка сохранения: {error_msg}"])

            # Успех - удаляем .bak
            _cleanup_bak(bak_path)

            log_info(f"Fsm_0_6_3: Трансформировано {transform_count} фич")

            if round_fallback_count > 0:
                warnings.append(
                    f"{round_fallback_count} фич без округления (fallback)"
                )
            if invalid_count > 0:
                warnings.append(
                    f"{invalid_count} фич с невалидной геометрией после трансформации"
                )

            return (True, warnings)

        except Exception as e:
            log_error(f"Fsm_0_6_3: Ошибка при трансформации: {e}")
            layer.rollBack()
            if bak_path and os.path.exists(bak_path):
                _restore_from_bak(gpkg_path, bak_path)
            return (False, [f"Ошибка трансформации: {e}"])

    @staticmethod
    def restore_from_backup(
        layer: QgsVectorLayer,
        backup: Dict[int, QgsGeometry]
    ) -> bool:
        """
        Восстановить геометрии из backup в памяти.

        Parameters:
            layer: Слой для восстановления
            backup: Словарь feature_id -> QgsGeometry

        Returns:
            True если успешно
        """
        if not backup:
            log_warning("Fsm_0_6_3: Пустой backup, нечего восстанавливать")
            return True

        already_editing = layer.isEditable()
        if not already_editing and not layer.startEditing():
            log_error(
                f"Fsm_0_6_3: Не удалось начать редактирование для restore. "
                f"Provider={layer.providerType()}, readOnly={layer.readOnly()}"
            )
            return False

        try:
            restored = 0
            for fid, geom in backup.items():
                layer.changeGeometry(fid, QgsGeometry(geom))
                restored += 1

            if not layer.commitChanges():
                log_error("Fsm_0_6_3: Не удалось commit при restore")
                layer.rollBack()
                return False

            log_info(f"Fsm_0_6_3: Восстановлено {restored} геометрий из backup")
            return True

        except Exception as e:
            log_error(f"Fsm_0_6_3: Ошибка restore: {e}")
            layer.rollBack()
            return False

    @staticmethod
    def validate_result(layer: QgsVectorLayer) -> List[str]:
        """
        Пост-трансформационная валидация слоя.

        Проверяет:
        - isGeosValid для всех геометрий
        - area > 0 для полигонов

        Returns:
            Список предупреждений (пустой = все OK)
        """
        warnings: List[str] = []
        invalid_fids: List[int] = []
        zero_area_fids: List[int] = []

        is_polygon = layer.geometryType() == QgsWkbTypes.PolygonGeometry

        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue
            geom = feature.geometry()
            fid = feature.id()

            if not geom.isGeosValid():
                invalid_fids.append(fid)

            if is_polygon and geom.area() <= 0:
                zero_area_fids.append(fid)

        if invalid_fids:
            warnings.append(
                f"Невалидные геометрии ({len(invalid_fids)} шт): "
                f"FID {invalid_fids[:5]}{'...' if len(invalid_fids) > 5 else ''}"
            )

        if zero_area_fids:
            warnings.append(
                f"Нулевая площадь ({len(zero_area_fids)} шт): "
                f"FID {zero_area_fids[:5]}{'...' if len(zero_area_fids) > 5 else ''}"
            )

        return warnings

    @staticmethod
    def convert_layer_to_gpkg(
        layer: QgsVectorLayer,
    ) -> Optional[QgsVectorLayer]:
        """
        Конвертировать non-editable слой (DXF и др.) в GPKG.

        Создаёт GPKG-копию рядом с исходным файлом, добавляет в проект,
        удаляет исходный слой из проекта.

        Parameters:
            layer: Исходный (non-editable) векторный слой

        Returns:
            Новый QgsVectorLayer (GPKG) или None при ошибке
        """
        # Определяем путь для GPKG
        source = layer.source()
        if '|' in source:
            source_path = source.split('|')[0]
        else:
            source_path = source

        source_dir = os.path.dirname(source_path)
        source_name = os.path.splitext(os.path.basename(source_path))[0]
        layer_name = layer.name()

        # Файл GPKG: рядом с исходным, имя = имя слоя
        gpkg_path = os.path.join(source_dir, f"{source_name}_transform.gpkg")

        # Если файл уже существует, добавляем суффикс
        counter = 1
        base_gpkg_path = gpkg_path
        while os.path.exists(gpkg_path):
            gpkg_path = base_gpkg_path.replace('.gpkg', f'_{counter}.gpkg')
            counter += 1

        log_info(
            f"Fsm_0_6_3: Конвертация '{layer_name}' "
            f"({layer.providerType()}) -> GPKG: {gpkg_path}"
        )

        # Экспорт через QgsVectorFileWriter
        try:
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.fileEncoding = "UTF-8"

            transform_context = QgsProject.instance().transformContext()

            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                gpkg_path,
                transform_context,
                options,
            )

            if error[0] != QgsVectorFileWriter.NoError:
                log_error(
                    f"Fsm_0_6_3: Ошибка экспорта в GPKG: {error}"
                )
                return None

        except Exception as e:
            log_error(f"Fsm_0_6_3: Исключение при экспорте в GPKG: {e}")
            return None

        # Добавляем новый GPKG слой в проект
        gpkg_uri = f"{gpkg_path}|layername={layer_name}"
        new_layer = QgsVectorLayer(gpkg_uri, layer_name, "ogr")

        if not new_layer.isValid():
            log_error(f"Fsm_0_6_3: Невалидный GPKG слой: {gpkg_uri}")
            return None

        # Удаляем старый слой, добавляем новый
        project = QgsProject.instance()
        old_layer_id = layer.id()

        project.addMapLayer(new_layer)

        # Удаляем оригинальный слой из проекта
        project.removeMapLayer(old_layer_id)

        log_info(
            f"Fsm_0_6_3: Слой '{layer_name}' сконвертирован в GPKG. "
            f"Фич: {new_layer.featureCount()}, путь: {gpkg_path}"
        )

        return new_layer


class _MethodTransformer(QgsAbstractGeometryTransformer):
    """Трансформер вершин через BaseTransformMethod."""

    def __init__(self, method: BaseTransformMethod):
        super().__init__()
        self._method = method

    def transformPoint(
        self, x: float, y: float, z: float, m: float
    ) -> tuple:
        """Трансформация одной вершины."""
        new_x, new_y = self._method.apply_to_point(x, y)
        return True, new_x, new_y, z, m


def _transform_geometry(
    geom: QgsGeometry,
    method: BaseTransformMethod
) -> Optional[QgsGeometry]:
    """
    Трансформировать геометрию через QgsAbstractGeometryTransformer.

    Использует мутабельный доступ к геометрии через geom.get()
    и метод transform(transformer) для in-place трансформации вершин.

    Parameters:
        geom: Исходная геометрия
        method: Метод трансформации

    Returns:
        Новая геометрия или None при ошибке
    """
    try:
        new_geom = QgsGeometry(geom)  # Копия
        abstract_geom = new_geom.get()  # Мутабельный доступ

        transformer = _MethodTransformer(method)
        success = abstract_geom.transform(transformer)

        if not success:
            log_error("Fsm_0_6_3: transform() вернул False")
            return None

        return new_geom

    except Exception as e:
        log_error(f"Fsm_0_6_3: Ошибка трансформации геометрии: {e}")
        return None


def _get_gpkg_path(layer: QgsVectorLayer) -> Optional[str]:
    """Извлечь путь к GPKG из source слоя."""
    source = layer.source()
    # GPKG source format: "/path/to/file.gpkg|layername=LayerName"
    if '|' in source:
        path = source.split('|')[0]
    else:
        path = source

    if path.lower().endswith('.gpkg') and os.path.exists(path):
        return path
    return None


def _cleanup_bak(bak_path: Optional[str]) -> None:
    """Удалить .bak файл и связанные WAL/SHM файлы."""
    if not bak_path:
        return
    for suffix in ['', '-wal', '-shm']:
        path = bak_path + suffix
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    if not os.path.exists(bak_path):
        log_info(f"Fsm_0_6_3: Backup удалён: {bak_path}")


def _restore_from_bak(gpkg_path: Optional[str], bak_path: str) -> None:
    """Восстановить GPKG из .bak файла (включая WAL/SHM)."""
    if gpkg_path and os.path.exists(bak_path):
        try:
            shutil.copy2(bak_path, gpkg_path)
            for ext in ['-wal', '-shm']:
                bak_ext = bak_path + ext
                gpkg_ext = gpkg_path + ext
                if os.path.exists(bak_ext):
                    shutil.copy2(bak_ext, gpkg_ext)
            _cleanup_bak(bak_path)
            log_info("Fsm_0_6_3: GPKG восстановлен из backup")
        except OSError as e:
            log_error(f"Fsm_0_6_3: Не удалось восстановить из backup: {e}")
