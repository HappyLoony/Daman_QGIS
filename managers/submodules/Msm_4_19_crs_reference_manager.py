# -*- coding: utf-8 -*-
"""
Менеджер справочных данных CRS (Coordinate Reference System).

Предоставляет функциональность для:
- Загрузки проекций из Base_CRS.json
- Поиска CRS по коду региона или региона:района
- Валидации соответствия CRS базе данных
- Добавления CRS в пользовательскую базу QGIS
"""

import re
from typing import List, Dict, Optional, Tuple
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.utils import log_info, log_warning, log_error


class CRSReferenceManager(BaseReferenceLoader):
    """Менеджер для работы со справочником CRS"""

    CRS_FILE = 'Base_CRS.json'

    def __init__(self, reference_dir: str):
        """
        Инициализация менеджера CRS

        Args:
            reference_dir: Путь к директории со справочными JSON файлами
        """
        super().__init__(reference_dir)

    # =========================================================================
    # Основные методы доступа к данным
    # =========================================================================

    def get_all_crs(self) -> List[Dict]:
        """
        Получить полный список CRS

        Returns:
            Список словарей с данными CRS
        """
        return self._load_json(self.CRS_FILE) or []

    def get_crs_by_code(self, code: str) -> Optional[Dict]:
        """
        Получить CRS по коду региона или региона:района

        Логика поиска:
        1. Если код содержит ":" - ищем по code_region_district
        2. Иначе - ищем по code_region

        Args:
            code: "05" (регион) или "05:40" (регион:район)

        Returns:
            Словарь с данными CRS или None
        """
        if not code:
            return None

        code = code.strip()

        if ':' in code:
            # Поиск по коду региона:района
            return self._get_by_key(
                data_getter=self.get_all_crs,
                index_key='crs_by_region_district',
                field_name='code_region_district',
                value=code
            )
        else:
            # Поиск по коду региона
            return self._get_by_key(
                data_getter=self.get_all_crs,
                index_key='crs_by_region',
                field_name='code_region',
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
            # Добавляем код региона
            if crs.get('code_region'):
                regions.add(crs['code_region'])
            # Для записей с районами извлекаем код региона
            elif crs.get('code_region_district'):
                region = crs['code_region_district'].split(':')[0]
                regions.add(region)

        return sorted(list(regions))

    def has_districts(self, region_code: str) -> bool:
        """
        Проверить есть ли у региона районы (зоны)

        Args:
            region_code: Код региона ("05")

        Returns:
            True если есть записи типа "05:XX"
        """
        if not region_code:
            return False

        crs_list = self.get_all_crs()

        for crs in crs_list:
            code_rd = crs.get('code_region_district')
            if code_rd and code_rd.startswith(f"{region_code}:"):
                return True

        return False

    def get_districts_for_region(self, region_code: str) -> List[str]:
        """
        Получить список кодов районов для региона

        Args:
            region_code: Код региона ("05")

        Returns:
            Отсортированный список кодов районов ["40", "41", "42", ...]
            или пустой список если районов нет
        """
        if not region_code:
            return []

        crs_list = self.get_all_crs()
        districts = set()

        for crs in crs_list:
            code_rd = crs.get('code_region_district')
            if code_rd and code_rd.startswith(f"{region_code}:"):
                # Извлекаем код района (после ":")
                district = code_rd.split(':')[1]
                districts.add(district)

        return sorted(list(districts))

    def get_crs_list_for_region(self, region_code: str) -> List[Dict]:
        """
        Получить все CRS для региона (включая районные)

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
            # Точное совпадение по региону
            if crs.get('code_region') == region_code:
                result.append(crs)
            # Или районы этого региона
            elif crs.get('code_region_district', '').startswith(f"{region_code}:"):
                result.append(crs)

        return result

    # =========================================================================
    # Методы валидации
    # =========================================================================

    def validate_crs_match(self, crs, code: str) -> bool:
        """
        Проверить соответствие CRS записи в базе

        Args:
            crs: QgsCoordinateReferenceSystem - выбранная пользователем CRS
            code: Код региона/района

        Returns:
            True если CRS соответствует базе данных
        """
        crs_data = self.get_crs_by_code(code)

        if not crs_data:
            log_warning(f"Msm_4_19: CRS для кода '{code}' не найдена в базе")
            return False

        # Сравниваем PROJ4 строки
        try:
            crs_proj = crs.toProj() if hasattr(crs, 'toProj') else crs.toProj4()
            base_proj = crs_data.get('proj4', '')

            # Нормализуем строки для сравнения
            crs_proj_norm = self._normalize_proj4(crs_proj)
            base_proj_norm = self._normalize_proj4(base_proj)

            return crs_proj_norm == base_proj_norm
        except Exception as e:
            log_error(f"Msm_4_19: Ошибка сравнения CRS: {e}")
            return False

    def _normalize_proj4(self, proj4: str) -> str:
        """
        Нормализовать PROJ4 строку для сравнения

        Удаляет пробелы, сортирует параметры

        Args:
            proj4: PROJ4 строка

        Returns:
            Нормализованная строка
        """
        if not proj4:
            return ''

        # Разбиваем на параметры, убираем пустые, сортируем
        params = proj4.strip().split()
        params = [p.strip() for p in params if p.strip()]
        params.sort()

        return ' '.join(params)

    # =========================================================================
    # Методы добавления CRS в QGIS
    # =========================================================================

    def add_crs_to_qgis_user_db(self, crs_data: Dict):
        """
        Добавить CRS в пользовательскую базу QGIS

        Использует QgsCoordinateReferenceSystemRegistry.addUserCrs()

        Args:
            crs_data: Словарь с данными CRS из Base_CRS.json

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

        # 1. Сначала пробуем WKT2 (ISO 19162:2019, lossless), затем WKT1
        wkt = crs_data.get('ogc_wkt2') or crs_data.get('ogc_wkt')
        proj4 = crs_data.get('proj4')

        crs = QgsCoordinateReferenceSystem()

        if wkt:
            crs.createFromWkt(wkt)
        elif proj4:
            crs.createFromProj(proj4)
        else:
            log_error("Msm_4_19: Нет WKT или PROJ4 определения")
            return None

        if not crs.isValid():
            log_error(f"Msm_4_19: Невалидная CRS")
            return None

        # 2. Проверяем - может CRS уже существует
        if crs.authid():
            log_info(f"Msm_4_19: CRS уже существует: {crs.authid()}")
            return crs

        # 3. Добавляем через Registry (современный подход QGIS 3.18+)
        crs_name = crs_data.get('full_name', 'Custom MSK')

        try:
            registry = QgsApplication.coordinateReferenceSystemRegistry()

            # Используем WKT формат (рекомендуется)
            srsid = registry.addUserCrs(crs, crs_name, Qgis.CrsDefinitionFormat.Wkt)

            if srsid == -1:
                log_error(f"Msm_4_19: Не удалось добавить CRS (srsid=-1)")
                return None

            # 4. Очищаем кэш
            QgsCoordinateReferenceSystem.invalidateCache()

            # 5. Создаем CRS с новым ID
            new_crs = QgsCoordinateReferenceSystem(f"USER:{srsid}")
            log_info(f"Msm_4_19: CRS добавлена: USER:{srsid} - {crs_name}")

            return new_crs

        except Exception as e:
            log_error(f"Msm_4_19: Ошибка добавления CRS: {e}")
            return None

    def get_or_create_crs(self, crs_data: Dict):
        """
        Получить существующую или создать новую CRS

        Args:
            crs_data: Словарь с данными CRS из Base_CRS.json

        Returns:
            QgsCoordinateReferenceSystem или None
        """
        try:
            from qgis.core import QgsCoordinateReferenceSystem
        except ImportError:
            log_error("Msm_4_19: QGIS не доступен")
            return None

        # Пробуем создать из WKT2/WKT1 или PROJ4
        wkt = crs_data.get('ogc_wkt2') or crs_data.get('ogc_wkt')
        proj4 = crs_data.get('proj4')

        crs = QgsCoordinateReferenceSystem()

        if wkt:
            crs.createFromWkt(wkt)
        elif proj4:
            crs.createFromProj(proj4)

        if crs.isValid() and crs.authid():
            # CRS уже существует в базе QGIS
            return crs

        # CRS не существует - добавляем
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

        suggested_code = (
            suggested.get('code_region_district') or
            suggested.get('code_region')
        )

        if project_crs_code == suggested_code:
            return True, f"CRS проекта соответствует данным ({suggested_code})"

        return False, (
            f"Внимание: CRS проекта ({project_crs_code}) "
            f"не соответствует данным ({suggested_code})"
        )

    # =========================================================================
    # Вспомогательные методы
    # =========================================================================

    def get_crs_description(self, code: str) -> str:
        """
        Получить описание CRS по коду

        Args:
            code: Код региона/района

        Returns:
            Описание CRS или пустая строка
        """
        crs_data = self.get_crs_by_code(code)

        if crs_data:
            return crs_data.get('full_name', '')

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
