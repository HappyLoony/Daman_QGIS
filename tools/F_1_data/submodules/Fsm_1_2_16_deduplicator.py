"""
Fsm_1_2_16_Deduplicator - Универсальная дедупликация геометрий

Двухуровневая дедупликация для multi-endpoint WFS слоёв:
  Level 1: normalize() + WKB hash для точных дубликатов (O(n))
  Level 2: IoU >= 0.95 через пространственный индекс для near-duplicates (O(n log n))

Используется в: Fsm_1_2_11 (КЛ), Fsm_1_2_14 (ПС), Fsm_1_2_9 (ЗОУИТ)
"""

from typing import Dict, List, Set

from qgis.core import (
    Qgis,
    QgsFeature,
    QgsGeometry,
    QgsSpatialIndex,
    QgsVectorLayer,
)

from Daman_QGIS.utils import log_info, log_warning, log_error


class Fsm_1_2_16_Deduplicator:
    """Универсальная дедупликация геометрий для multi-endpoint WFS слоёв.

    Level 1: normalize() + WKB hash -- точные дубликаты O(n)
    Level 2: IoU >= threshold -- near-duplicates O(n log n), только полигоны
    """

    IOU_THRESHOLD = 0.95

    def __init__(self, caller_id: str = "Fsm_1_2_16"):
        """
        Args:
            caller_id: MODULE_ID для лог-сообщений (напр. "Fsm_1_2_11")
        """
        self.caller_id = caller_id

    def deduplicate(
        self,
        layer: QgsVectorLayer,
        enable_near_duplicates: bool = True,
        iou_threshold: float = 0.95,
    ) -> Dict[str, int]:
        """Полный pipeline дедупликации: Level 1 (exact) + Level 2 (near).

        Args:
            layer: QgsVectorLayer для дедупликации (memory layer)
            enable_near_duplicates: запускать ли Level 2 (IoU)
            iou_threshold: порог IoU для Level 2 (по умолчанию 0.95)

        Returns:
            dict: exact_removed, near_removed, total_removed, remaining
        """
        initial_count = layer.featureCount()

        if initial_count == 0:
            return {
                "exact_removed": 0,
                "near_removed": 0,
                "total_removed": 0,
                "remaining": 0,
            }

        # Level 1: точные дубликаты
        exact_removed = self.deduplicate_exact(layer)

        # Level 2: near-дубликаты (только полигоны, если включено)
        near_removed = 0
        if enable_near_duplicates:
            near_removed = self.deduplicate_near(layer, iou_threshold)

        total_removed = exact_removed + near_removed
        remaining = layer.featureCount()

        if total_removed > 0:
            log_info(
                f"{self.caller_id}: Dedup: {initial_count} -> {remaining} "
                f"(exact: -{exact_removed}, near: -{near_removed})"
            )
        else:
            log_info(f"{self.caller_id}: Dedup: дубликатов не обнаружено ({initial_count} obj)")

        return {
            "exact_removed": exact_removed,
            "near_removed": near_removed,
            "total_removed": total_removed,
            "remaining": remaining,
        }

    def deduplicate_exact(self, layer: QgsVectorLayer) -> int:
        """Level 1: удаление точных дубликатов через normalize() + WKB hash.

        normalize() приводит геометрию к канонической форме:
        - Единый порядок вершин
        - Кольца начинаются с нижне-левой точки
        - Right-hand rule ориентация

        Args:
            layer: QgsVectorLayer (memory layer)

        Returns:
            int: количество удалённых дубликатов
        """
        seen_wkb: Set[bytes] = set()
        duplicate_ids: List[int] = []

        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue

            # Клонируем геометрию чтобы не мутировать слой
            geom = QgsGeometry(feature.geometry())
            geom.normalize()
            wkb = bytes(geom.asWkb())

            if wkb in seen_wkb:
                duplicate_ids.append(feature.id())
            else:
                seen_wkb.add(wkb)

        if not duplicate_ids:
            return 0

        return self._delete_features(layer, duplicate_ids)

    def deduplicate_near(
        self,
        layer: QgsVectorLayer,
        iou_threshold: float = 0.95,
    ) -> int:
        """Level 2: удаление near-дубликатов через IoU + пространственный индекс.

        Только для полигонных слоёв. Line/point слои пропускаются.

        IoU = area(A intersection B) / area(A union B)
        union area вычисляется алгебраически: area_a + area_b - intersection_area

        Args:
            layer: QgsVectorLayer (memory layer)
            iou_threshold: минимальный IoU для near-дубликата (по умолчанию 0.95)

        Returns:
            int: количество удалённых near-дубликатов
        """
        # Только полигоны
        if layer.geometryType() != Qgis.GeometryType.Polygon:
            return 0

        if layer.featureCount() == 0:
            return 0

        # Построение пространственного индекса и кэша геометрий
        spatial_index = QgsSpatialIndex()
        features_cache: Dict[int, QgsGeometry] = {}

        for feature in layer.getFeatures():
            if not feature.hasGeometry() or feature.geometry().isEmpty():
                continue
            fid = feature.id()
            spatial_index.addFeature(feature)
            features_cache[fid] = QgsGeometry(feature.geometry())

        # Поиск near-дубликатов
        duplicate_ids: Set[int] = set()
        checked_fids = sorted(features_cache.keys())
        iou_error_count = 0

        for fid_a in checked_fids:
            if fid_a in duplicate_ids:
                continue

            geom_a = features_cache[fid_a]
            area_a = geom_a.area()
            if area_a <= 0:
                continue

            # Кандидаты по bbox
            candidates = spatial_index.intersects(geom_a.boundingBox())

            for fid_b in candidates:
                # Только пары с fid_b > fid_a (избежать двойной проверки)
                if fid_b <= fid_a or fid_b in duplicate_ids:
                    continue

                geom_b = features_cache[fid_b]
                area_b = geom_b.area()
                if area_b <= 0:
                    continue

                # IoU
                try:
                    intersection = geom_a.intersection(geom_b)
                    if intersection.isEmpty():
                        continue
                    intersection_area = intersection.area()
                    if intersection_area <= 0:
                        continue

                    union_area = area_a + area_b - intersection_area
                    if union_area <= 0:
                        continue

                    iou = intersection_area / union_area
                    if iou >= iou_threshold:
                        duplicate_ids.add(fid_b)
                except Exception as e:
                    iou_error_count += 1
                    if iou_error_count == 1:
                        log_warning(
                            f"Fsm_1_2_16 (deduplicate_near): "
                            f"IoU error fid {fid_a}-{fid_b}: {str(e)}"
                        )
                    continue

        if iou_error_count > 1:
            log_warning(
                f"Fsm_1_2_16 (deduplicate_near): "
                f"IoU errors total: {iou_error_count}"
            )

        if not duplicate_ids:
            return 0

        return self._delete_features(layer, list(duplicate_ids))

    def _delete_features(self, layer: QgsVectorLayer, fids: List[int]) -> int:
        """Удаление features по списку fid.

        Args:
            layer: QgsVectorLayer
            fids: список feature IDs для удаления

        Returns:
            int: количество удалённых features (0 при ошибке)
        """
        if not fids:
            return 0

        try:
            if not layer.startEditing():
                log_error(f"Fsm_1_2_16 (_delete_features): не удалось начать редактирование")
                return 0

            layer.deleteFeatures(fids)
            layer.commitChanges()
            return len(fids)

        except Exception as e:
            log_error(f"Fsm_1_2_16 (_delete_features): ошибка удаления: {str(e)}")
            layer.rollBack()
            return 0
