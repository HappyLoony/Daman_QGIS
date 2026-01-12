# -*- coding: utf-8 -*-
"""
Fsm_0_4_10: Асинхронный Task для проверки топологии

Наследует от BaseAsyncTask (M_17) для унифицированной обработки.
Использует QgsTask для фоновой обработки без блокировки UI.

Основан на паттерне из плагина KAT Overlap (GPLv3)
Адаптирован для Daman_QGIS

ВАЖНО: QgsProcessingContext должен создаваться в main thread и передаваться
в task, так как processing.run() внутри себя обращается к iface.mapCanvas()
что вызывает access violation при вызове из background thread.
"""

from typing import List, Optional
from qgis.core import QgsProject, QgsProcessingContext, QgsVectorLayer
from Daman_QGIS.managers.submodules.Msm_17_1_base_task import BaseAsyncTask
from Daman_QGIS.utils import log_info


class Fsm_0_4_10_TopologyCheckTask(BaseAsyncTask):
    """
    Task для асинхронной проверки топологии слоя.

    Наследует от BaseAsyncTask - run(), finished() уже реализованы.
    Реализует только execute() с логикой проверки.

    IMPORTANT: Передавать layer_id, не layer object!

    Использование:
        from Daman_QGIS.managers import get_async_manager

        task = Fsm_0_4_10_TopologyCheckTask(
            layer_id=layer.id(),
            layer_name=layer.name()
        )
        manager = get_async_manager(iface)
        manager.run(task, on_completed=handle_result)
    """

    def __init__(self,
                 layer_id: str,
                 layer_name: str,
                 check_types: Optional[List[str]] = None,
                 processing_context: Optional[QgsProcessingContext] = None):
        """
        Args:
            layer_id: ID слоя для проверки (НЕ layer object!)
            layer_name: Имя слоя (для отображения)
            check_types: Список типов проверок (None = все)
            processing_context: QgsProcessingContext созданный в main thread
                               (ОБЯЗАТЕЛЬНО для thread-safe работы processing.run())
        """
        super().__init__(f"Проверка топологии: {layer_name}", can_cancel=True)

        self.layer_id = layer_id
        self.layer_name = layer_name
        self.check_types = check_types
        self.processing_context = processing_context

    def execute(self):
        """
        Основная логика проверки топологии.

        Выполняется в background thread.

        Returns:
            dict: Результаты проверки с ключами:
                - error_count: количество ошибок
                - errors: список ошибок
                - error_layer: слой с ошибками (если есть)
        """
        log_info(f"Fsm_0_4_10: Запуск проверки для слоя '{self.layer_name}'")

        # Импортируем координатор здесь, чтобы избежать циклических импортов
        from .Fsm_0_4_5_coordinator import Fsm_0_4_5_TopologyCoordinator

        # Получаем слой по ID (безопасно для background thread)
        layer = QgsProject.instance().mapLayer(self.layer_id)
        if not layer or not isinstance(layer, QgsVectorLayer):
            raise ValueError(f"Слой '{self.layer_name}' не найден или не является векторным (id={self.layer_id})")

        # Проверяем отмену перед началом
        if self.is_cancelled():
            return None

        # Создаем координатор с processing_context для thread-safe операций
        coordinator = Fsm_0_4_5_TopologyCoordinator(
            processing_context=self.processing_context
        )

        # Callback для прогресса
        def progress_callback(progress: int):
            if not self.is_cancelled():
                message = self._get_progress_message(progress)
                self.report_progress(progress, message)

        # Выполняем проверку
        result = coordinator.check_layer(
            layer,
            check_types=self.check_types,
            progress_callback=progress_callback
        )

        # Финальная проверка отмены
        if self.is_cancelled():
            return None

        log_info(f"Fsm_0_4_10: Проверка завершена, найдено {result.get('error_count', 0)} ошибок")
        return result

    def _get_progress_message(self, progress: int) -> str:
        """Получение текстового сообщения для прогресса"""
        if progress < 25:
            return "Проверка валидности..."
        elif progress < 50:
            return "Проверка дублей..."
        elif progress < 75:
            return "Проверка топологии..."
        elif progress < 100:
            return "Проверка точности..."
        return "Завершение..."
