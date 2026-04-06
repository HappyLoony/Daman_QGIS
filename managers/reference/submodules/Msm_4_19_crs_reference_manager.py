# -*- coding: utf-8 -*-
"""
Менеджер справочных данных CRS (Coordinate Reference System).

Предоставляет функциональность для:
- Загрузки проекций из Base_CRS.json
- Поиска CRS по коду региона или региона:зоны
- Валидации соответствия CRS базе данных
- Добавления CRS в пользовательскую базу QGIS
- Синхронизации USER CRS реестра с Base_CRS.json

Структура Base_CRS.json:
    [{"id": 1, "name": "МСК-05 ...", "region_name": "...",
      "region_code": "05", "zone": null, "wkt2": "PROJCRS[...]",
      "crs_type": "МСК", "pipeline": "..."}]

Поле pipeline -- только для серверной валидации, НЕ записывается в CRS.
"""

import re
from typing import List, Dict, Optional, Tuple
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.utils import log_info, log_warning, log_error


class CRSReferenceManager(BaseReferenceLoader):
    """Менеджер для работы со справочником CRS"""

    CRS_FILE = 'Base_CRS.json'

    def __init__(self):
        """Инициализация менеджера CRS."""
        super().__init__()

    # =========================================================================
    # Основные методы доступа к данным
    # =========================================================================

    def get_all_crs(self) -> List[Dict]:
        """
        Получить полный список CRS.

        Добавляет вычисляемый ключ _region_zone_key для индексации
        по составному коду region_code:zone.

        Returns:
            Список словарей с данными CRS
        """
        data = self._load_json(self.CRS_FILE) or []
        for item in data:
            zone = item.get('zone')
            region = item.get('region_code', '')
            if zone is not None:
                item['_region_zone_key'] = f"{region}:{zone}"
            else:
                item['_region_zone_key'] = None
        return data

    def get_crs_by_code(self, code: str) -> Optional[Dict]:
        """
        Получить CRS по коду региона или региона:зоны.

        Логика поиска:
        1. Если код содержит ":" - ищем по region_code:zone
        2. Иначе - ищем по region_code (zone=null)

        Args:
            code: "05" (регион) или "05:1" (регион:зона)

        Returns:
            Словарь с данными CRS или None
        """
        if not code:
            return None

        code = code.strip()

        if ':' in code:
            # Поиск по region_code:zone (составной ключ)
            return self._get_by_key(
                data_getter=self.get_all_crs,
                index_key='crs_by_region_zone',
                field_name='_region_zone_key',
                value=code
            )
        else:
            # Поиск по region_code (zone=null)
            return self._get_by_key(
                data_getter=self.get_all_crs,
                index_key='crs_by_region',
                field_name='region_code',
                value=code
            )

    # =========================================================================
    # Методы для работы с регионами и районами
    # =========================================================================

    def get_regions_list(self) -> List[str]:
        """
        Получить список уникальных кодов регионов

        Returns:
            Отсортированный список кодов регионов ["01", "02", "05", ...]
        """
        crs_list = self.get_all_crs()
        regions = set()

        for crs in crs_list:
            region = crs.get('region_code')
            if region:
                regions.add(region)

        return sorted(list(regions))

    def has_zones(self, region_code: str) -> bool:
        """
        Проверить есть ли у региона зоны.

        Args:
            region_code: Код региона ("05")

        Returns:
            True если есть записи с zone != null для данного региона
        """
        if not region_code:
            return False

        crs_list = self.get_all_crs()

        for crs in crs_list:
            if crs.get('region_code') == region_code and crs.get('zone') is not None:
                return True

        return False

    # Обратная совместимость
    has_districts = has_zones

    def get_zones_for_region(self, region_code: str) -> List[str]:
        """
        Получить список зон для региона.

        Args:
            region_code: Код региона ("05")

        Returns:
            Отсортированный список зон ["1", "2", "3", ...]
            или пустой список если зон нет
        """
        if not region_code:
            return []

        crs_list = self.get_all_crs()
        zones = set()

        for crs in crs_list:
            if crs.get('region_code') == region_code and crs.get('zone') is not None:
                zones.add(str(crs['zone']))

        return sorted(list(zones))

    # Обратная совместимость
    get_districts_for_region = get_zones_for_region

    def get_crs_list_for_region(self, region_code: str) -> List[Dict]:
        """
        Получить все CRS для региона (включая зональные).

        Args:
            region_code: Код региона ("05")

        Returns:
            Список словарей с данными CRS
        """
        if not region_code:
            return []

        crs_list = self.get_all_crs()
        result = []

        for crs in crs_list:
            if crs.get('region_code') == region_code:
                result.append(crs)

        return result

    # =========================================================================
    # Методы валидации
    # =========================================================================

    def validate_crs_match(self, crs, code: str) -> bool:
        """
        Проверить соответствие CRS записи в базе.

        Сравнивает WKT2 из JSON с WKT текущей CRS.

        Args:
            crs: QgsCoordinateReferenceSystem - выбранная пользователем CRS
            code: Код региона/зоны

        Returns:
            True если CRS соответствует базе данных
        """
        crs_data = self.get_crs_by_code(code)

        if not crs_data:
            log_warning(f"Msm_4_19: CRS для кода '{code}' не найдена в базе")
            return False

        try:
            from qgis.core import QgsCoordinateReferenceSystem as QgsCrs

            ref_crs = QgsCrs()
            ref_crs.createFromWkt(crs_data.get('wkt2', ''))

            if not ref_crs.isValid():
                log_warning("Msm_4_19: Невалидный WKT2 из базы")
                return False

            # Сравниваем через normalized PROJ4 (WKT может отличаться форматированием)
            from Daman_QGIS.core.crs_utils import normalize_proj4
            return normalize_proj4(crs.toProj()) == normalize_proj4(ref_crs.toProj())
        except Exception as e:
            log_error(f"Msm_4_19: Ошибка сравнения CRS: {e}")
            return False

    # =========================================================================
    # Методы добавления CRS в QGIS
    # =========================================================================

    def add_crs_to_qgis_user_db(self, crs_data: Dict):
        """
        Добавить CRS в пользовательскую базу QGIS.

        Использует QgsCoordinateReferenceSystemRegistry.addUserCrs().

        Args:
            crs_data: Словарь с данными CRS из Base_CRS.json
                      (поля: name, wkt2)

        Returns:
            QgsCoordinateReferenceSystem или None при ошибке
        """
        try:
            from qgis.core import (
                QgsApplication,
                QgsCoordinateReferenceSystem,
                Qgis
            )
        except ImportError:
            log_error("Msm_4_19: QGIS не доступен")
            return None

        wkt2 = crs_data.get('wkt2')

        if not wkt2:
            log_error("Msm_4_19: Нет WKT2 определения")
            return None

        crs = QgsCoordinateReferenceSystem()
        crs.createFromWkt(wkt2)

        if not crs.isValid():
            log_error("Msm_4_19: Невалидная CRS из WKT2")
            return None

        crs_name = crs_data.get('name', 'Custom MSK')

        # Проверяем - может CRS уже существует в QGIS (EPSG и т.д.)
        if crs.authid():
            log_info(f"Msm_4_19: CRS уже существует: {crs.authid()}")
            return crs

        # Поиск среди USER CRS по имени (приоритет для reference CRS)
        from Daman_QGIS.core.crs_utils import (
            find_existing_user_crs,
            find_existing_user_crs_by_name,
        )
        existing_id = find_existing_user_crs_by_name(crs_name)
        if existing_id is not None:
            # Обновить параметры если изменились в Base_CRS.json
            registry = QgsApplication.coordinateReferenceSystemRegistry()
            registry.updateUserCrs(
                existing_id, crs, crs_name,
                Qgis.CrsDefinitionFormat.Wkt,
            )
            QgsCoordinateReferenceSystem.invalidateCache()
            existing_crs = QgsCoordinateReferenceSystem(f"USER:{existing_id}")
            log_info(f"Msm_4_19: CRS обновлена: USER:{existing_id} - {crs_name}")
            return existing_crs

        # Поиск среди существующих USER CRS по normalized PROJ4
        existing_id = find_existing_user_crs(crs)
        if existing_id is not None:
            QgsCoordinateReferenceSystem.invalidateCache()
            existing_crs = QgsCoordinateReferenceSystem(f"USER:{existing_id}")
            log_info(f"Msm_4_19: CRS уже существует как USER:{existing_id}")
            return existing_crs

        try:
            registry = QgsApplication.coordinateReferenceSystemRegistry()

            srsid = registry.addUserCrs(crs, crs_name, Qgis.CrsDefinitionFormat.Wkt)

            if srsid == -1:
                log_error("Msm_4_19: Не удалось добавить CRS (srsid=-1)")
                return None

            QgsCoordinateReferenceSystem.invalidateCache()

            new_crs = QgsCoordinateReferenceSystem(f"USER:{srsid}")
            log_info(f"Msm_4_19: CRS добавлена: USER:{srsid} - {crs_name}")

            return new_crs

        except Exception as e:
            log_error(f"Msm_4_19: Ошибка добавления CRS: {e}")
            return None

    def get_or_create_crs(self, crs_data: Dict):
        """
        Получить существующую или создать новую CRS.

        Args:
            crs_data: Словарь с данными CRS из Base_CRS.json
                      (поля: name, wkt2)

        Returns:
            QgsCoordinateReferenceSystem или None
        """
        try:
            from qgis.core import QgsCoordinateReferenceSystem
        except ImportError:
            log_error("Msm_4_19: QGIS не доступен")
            return None

        wkt2 = crs_data.get('wkt2')
        if not wkt2:
            return None

        crs = QgsCoordinateReferenceSystem()
        crs.createFromWkt(wkt2)

        if crs.isValid() and crs.authid():
            return crs

        return self.add_crs_to_qgis_user_db(crs_data)

    # =========================================================================
    # Методы для работы с кадастровыми номерами (опционально)
    # =========================================================================

    def extract_region_code_from_cadastral(self, cadastral_number: str) -> Optional[str]:
        """
        Извлечь код региона из кадастрового номера

        Args:
            cadastral_number: "05:40:000028:1234" или "05:40:000028"

        Returns:
            "05" (код региона) или None
        """
        if not cadastral_number:
            return None

        # Паттерны кадастровых номеров
        patterns = [
            r'^(\d{2}):\d{2}:\d{6,7}:\d{1,6}$',  # Полный КН: 05:40:000028:1234
            r'^(\d{2}):\d{2}:\d{6,7}$',           # КН квартала: 05:40:000028
            r'^(\d{2})[:.]\d{2}-\d{1,2}\.\d{1,2}$',  # Альтернативный формат
        ]

        for pattern in patterns:
            match = re.match(pattern, cadastral_number.strip())
            if match:
                return match.group(1)

        return None

    def extract_district_code_from_cadastral(self, cadastral_number: str) -> Optional[str]:
        """
        Извлечь код региона:района из кадастрового номера

        Args:
            cadastral_number: "05:40:000028:1234"

        Returns:
            "05:40" (код региона:района) или None
        """
        if not cadastral_number:
            return None

        # Извлекаем первые 5 символов (РР:РР)
        pattern = r'^(\d{2}:\d{2}):\d{6,7}'
        match = re.match(pattern, cadastral_number.strip())

        if match:
            return match.group(1)

        return None

    def suggest_crs_for_cadastral_number(self, cadastral_number: str) -> Optional[Dict]:
        """
        Предложить CRS на основе кадастрового номера

        Сначала пробует по району (более точно), затем по региону

        Args:
            cadastral_number: Кадастровый номер

        Returns:
            Словарь с данными CRS или None
        """
        # Сначала пробуем по району (более точно)
        district_code = self.extract_district_code_from_cadastral(cadastral_number)
        if district_code:
            crs_data = self.get_crs_by_code(district_code)
            if crs_data:
                return crs_data

        # Fallback на регион
        region_code = self.extract_region_code_from_cadastral(cadastral_number)
        if region_code:
            return self.get_crs_by_code(region_code)

        return None

    def validate_project_crs_for_data(
        self,
        project_crs_code: str,
        cadastral_number: str
    ) -> Tuple[bool, str]:
        """
        Проверить соответствие CRS проекта импортируемым данным

        Args:
            project_crs_code: Код CRS проекта (из метаданных)
            cadastral_number: Кадастровый номер из данных

        Returns:
            Кортеж (is_valid, message)
        """
        suggested = self.suggest_crs_for_cadastral_number(cadastral_number)

        if not suggested:
            return True, "Не удалось определить CRS по кадастровому номеру"

        zone = suggested.get('zone')
        region = suggested.get('region_code', '')
        suggested_code = f"{region}:{zone}" if zone is not None else region

        if project_crs_code == suggested_code:
            return True, f"CRS проекта соответствует данным ({suggested_code})"

        return False, (
            f"Внимание: CRS проекта ({project_crs_code}) "
            f"не соответствует данным ({suggested_code})"
        )

    # =========================================================================
    # Синхронизация USER CRS реестра с Base_CRS.json
    # =========================================================================

    def sync_crs_from_json(self) -> Dict:
        """
        Полная синхронизация USER CRS реестра с Base_CRS.json.

        Порядок операций:
        1. Загрузить Base_CRS.json через BaseReferenceLoader (HTTP + JWT)
        2. Получить текущий список USER CRS из QGIS реестра
        3. Для каждой reference CRS (без '_' prefix):
           - Есть в JSON с таким name и WKT2 совпадает -> оставить
           - Есть в JSON с таким name но WKT2 отличается -> updateUserCrs()
           - Нет в JSON -> removeUserCrs()
        4. Для каждой записи в JSON:
           - Нет USER CRS с таким name -> addUserCrs()
        5. Дедупликация по имени
        6. Очистка unknown записей из recent projections

        Custom CRS (с '_' prefix) НИКОГДА не затрагиваются.
        Поле pipeline из JSON ИГНОРИРУЕТСЯ.

        Returns:
            Словарь со статистикой:
            {added, updated, removed, skipped_custom, total, recent_unknown_removed}
        """
        try:
            from qgis.core import (
                QgsApplication,
                QgsCoordinateReferenceSystem,
                Qgis
            )
        except ImportError:
            log_error("Msm_4_19: QGIS не доступен для sync")
            return {}

        from Daman_QGIS.core.crs_utils import (
            is_custom_crs,
            deduplicate_by_name,
            cleanup_recent_projections,
            normalize_proj4,
        )

        stats: Dict[str, int] = {
            'added': 0,
            'updated': 0,
            'removed': 0,
            'skipped_custom': 0,
            'total': 0,
            'recent_unknown_removed': 0,
        }

        # 1. Загрузить JSON
        json_crs_list = self.get_all_crs()
        if not json_crs_list:
            log_warning("Msm_4_19: Base_CRS.json пуст или недоступен, sync пропущен")
            return stats

        # Построить словарь {name: crs_data} из JSON
        json_by_name: Dict[str, Dict] = {}
        for item in json_crs_list:
            name = item.get('name', '').strip()
            if name:
                json_by_name[name] = item

        # 2. Получить текущий USER CRS реестр
        registry = QgsApplication.coordinateReferenceSystemRegistry()
        user_crs_list = list(registry.userCrsList())

        # 3. Обработка существующих USER CRS
        seen_reference_names: set = set()

        for details in user_crs_list:
            name = details.name.strip()
            if not name:
                continue

            # Custom CRS -- не трогаем
            if is_custom_crs(name):
                stats['skipped_custom'] += 1
                continue

            # Reference CRS
            if name in json_by_name:
                # Есть в JSON -- проверить нужно ли обновление
                seen_reference_names.add(name)
                json_item = json_by_name[name]
                wkt2 = json_item.get('wkt2', '')

                if not wkt2:
                    continue

                # Создаём CRS из JSON WKT2 для сравнения
                ref_crs = QgsCoordinateReferenceSystem()
                ref_crs.createFromWkt(wkt2)

                if not ref_crs.isValid():
                    log_warning(f"Msm_4_19: Невалидный WKT2 в JSON для '{name}'")
                    continue

                # Сравниваем по normalized PROJ4
                existing_proj = normalize_proj4(details.crs.toProj())
                json_proj = normalize_proj4(ref_crs.toProj())

                if existing_proj != json_proj:
                    # WKT изменился -> обновить
                    registry.updateUserCrs(
                        details.id, ref_crs, name,
                        Qgis.CrsDefinitionFormat.Wkt,
                    )
                    stats['updated'] += 1
                    log_info(f"Msm_4_19: CRS обновлена: USER:{details.id} - {name}")
                # Если совпадает -- ничего не делаем
            else:
                # Нет в JSON -- удалить reference CRS
                registry.removeUserCrs(details.id)
                stats['removed'] += 1
                log_info(f"Msm_4_19: CRS удалена: USER:{details.id} - {name}")

        # 4. Добавить новые CRS из JSON
        for name, json_item in json_by_name.items():
            if name in seen_reference_names:
                continue  # Уже обработана выше

            wkt2 = json_item.get('wkt2', '')
            if not wkt2:
                continue

            crs = QgsCoordinateReferenceSystem()
            crs.createFromWkt(wkt2)

            if not crs.isValid():
                log_warning(f"Msm_4_19: Невалидный WKT2 для новой CRS '{name}'")
                continue

            # Не добавляем если уже есть EPSG authid
            if crs.authid():
                continue

            srsid = registry.addUserCrs(crs, name, Qgis.CrsDefinitionFormat.Wkt)
            if srsid != -1:
                stats['added'] += 1
                log_info(f"Msm_4_19: CRS добавлена: USER:{srsid} - {name}")
            else:
                log_warning(f"Msm_4_19: Не удалось добавить CRS '{name}'")

        # 5. Дедупликация
        removed_dupes = deduplicate_by_name()
        if removed_dupes:
            log_info(f"Msm_4_19: Дедупликация -- удалено {len(removed_dupes)} дублей")

        # 6. Очистка recent projections
        stats['recent_unknown_removed'] = cleanup_recent_projections()

        # Инвалидация кэша CRS
        QgsCoordinateReferenceSystem.invalidateCache()

        # Финальная статистика
        final_list = list(registry.userCrsList())
        stats['total'] = len(final_list)

        log_info(
            f"Msm_4_19: sync_crs_from_json -- "
            f"added={stats['added']}, updated={stats['updated']}, "
            f"removed={stats['removed']}, custom={stats['skipped_custom']}, "
            f"total={stats['total']}"
        )

        return stats

    # =========================================================================
    # Вспомогательные методы
    # =========================================================================

    def get_crs_description(self, code: str) -> str:
        """
        Получить описание CRS по коду.

        Args:
            code: Код региона/зоны

        Returns:
            Описание CRS или пустая строка
        """
        crs_data = self.get_crs_by_code(code)

        if crs_data:
            return crs_data.get('name', '')

        return ''

    def get_all_user_crs(self) -> List[Dict]:
        """
        Получить список всех пользовательских CRS из QGIS

        Returns:
            Список словарей с данными CRS
        """
        try:
            from qgis.core import QgsApplication
        except ImportError:
            return []

        result = []

        try:
            registry = QgsApplication.coordinateReferenceSystemRegistry()
            user_crs_list = registry.userCrsList()

            for user_crs in user_crs_list:
                result.append({
                    'id': user_crs.id,
                    'name': user_crs.name,
                    'proj': user_crs.proj,
                    'wkt': user_crs.wkt,
                    'crs': user_crs.crs
                })
        except Exception as e:
            log_error(f"Msm_4_19: Ошибка получения списка USER CRS: {e}")

        return result
