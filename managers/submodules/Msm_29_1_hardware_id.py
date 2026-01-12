# -*- coding: utf-8 -*-
"""
Msm_29_1_HardwareIDGenerator - Генератор Hardware ID.

Генерирует уникальный идентификатор компьютера на основе:
- CPU ID
- Motherboard Serial
- BIOS Serial
- Primary Disk Serial
- Machine GUID (Windows installation ID)

Используется для привязки лицензии к конкретному ПК.
"""

import hashlib
import subprocess
import platform
from typing import Optional, Dict, Any

from ...utils import log_info, log_error, log_warning


class HardwareIDGenerator:
    """
    Генератор Hardware ID на основе компонентов ПК.

    Использует комбинацию 5 компонентов:
    - CPU ID
    - Motherboard Serial
    - BIOS Serial
    - Primary Disk Serial
    - Machine GUID
    """

    def __init__(self):
        self._components: Dict[str, str] = {}
        self._hardware_id: Optional[str] = None

    def generate(self) -> Optional[str]:
        """
        Генерация Hardware ID.

        Returns:
            SHA256 хэш компонентов или None при ошибке
        """
        if self._hardware_id:
            return self._hardware_id

        if platform.system() != "Windows":
            log_error("Msm_29_1: Only Windows is supported")
            return None

        try:
            self._components = self._collect_components()

            if not self._components:
                log_error("Msm_29_1: No hardware components collected")
                return None

            # Формируем строку для хэширования
            # Сортируем ключи для консистентности
            component_string = "|".join(
                f"{k}:{v}" for k, v in sorted(self._components.items())
            )

            # SHA256 хэш
            self._hardware_id = hashlib.sha256(component_string.encode()).hexdigest()

            log_info(f"Msm_29_1: Generated Hardware ID from {len(self._components)} components")
            return self._hardware_id

        except Exception as e:
            log_error(f"Msm_29_1: Failed to generate Hardware ID: {e}")
            return None

    def get_components(self) -> Dict[str, str]:
        """Получение собранных компонентов."""
        if not self._components:
            self._components = self._collect_components()
        return self._components.copy()

    def _collect_components(self) -> Dict[str, str]:
        """Сбор информации о компонентах."""
        components = {}

        # CPU ID
        cpu_id = self._get_wmi_value("Win32_Processor", "ProcessorId")
        if cpu_id:
            components["cpu_id"] = cpu_id

        # Motherboard Serial
        mb_serial = self._get_wmi_value("Win32_BaseBoard", "SerialNumber")
        if mb_serial and mb_serial not in ["To Be Filled By O.E.M.", "Default string", ""]:
            components["motherboard_serial"] = mb_serial

        # BIOS Serial
        bios_serial = self._get_wmi_value("Win32_BIOS", "SerialNumber")
        if bios_serial and bios_serial not in ["To Be Filled By O.E.M.", "Default string", ""]:
            components["bios_serial"] = bios_serial

        # Primary Disk Serial (системный диск)
        disk_serial = self._get_system_disk_serial()
        if disk_serial:
            components["disk_serial"] = disk_serial

        # Machine GUID (Windows installation ID)
        machine_guid = self._get_machine_guid()
        if machine_guid:
            components["machine_guid"] = machine_guid

        return components

    def _get_wmi_value(self, wmi_class: str, property_name: str) -> Optional[str]:
        """
        Получение значения через WMIC.

        Args:
            wmi_class: Класс WMI (например, Win32_Processor)
            property_name: Имя свойства

        Returns:
            Значение свойства или None
        """
        try:
            cmd = f'wmic {wmi_class} get {property_name}'
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    value = lines[1].strip()
                    if value:
                        return value

            return None

        except subprocess.TimeoutExpired:
            log_warning(f"Msm_29_1: WMI timeout for {wmi_class}.{property_name}")
            return None
        except Exception as e:
            log_warning(f"Msm_29_1: WMI error for {wmi_class}.{property_name}: {e}")
            return None

    def _get_system_disk_serial(self) -> Optional[str]:
        """Получение серийного номера системного диска."""
        try:
            # Получаем индекс системного диска
            cmd = 'wmic diskdrive where "Index=0" get SerialNumber'
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    serial = lines[1].strip()
                    if serial:
                        return serial

            return None

        except Exception as e:
            log_warning(f"Msm_29_1: Failed to get disk serial: {e}")
            return None

    def _get_machine_guid(self) -> Optional[str]:
        """
        Получение Machine GUID из реестра Windows.

        Это уникальный ID установки Windows.
        """
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY
            )
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)

            return value

        except Exception as e:
            log_warning(f"Msm_29_1: Failed to get Machine GUID: {e}")
            return None

    def compare_components(
        self,
        stored: Dict[str, str],
        current: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Сравнение компонентов и подсчёт совпадений.

        Returns:
            {"matched": N, "total": M, "changed": [...]}
        """
        matched = 0
        changed = []
        total = len(stored)

        for key, stored_value in stored.items():
            current_value = current.get(key)
            if current_value == stored_value:
                matched += 1
            else:
                changed.append(key)

        return {
            "matched": matched,
            "total": total,
            "changed": changed,
            "match_ratio": matched / total if total > 0 else 0
        }
