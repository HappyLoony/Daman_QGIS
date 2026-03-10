# -*- coding: utf-8 -*-
"""
F_4_4_Feedback - Обратная связь с отправкой логов сессий

Координатор для:
- Отправки описания проблемы/предложения
- Автоматического прикрепления логов последних 3 сессий
- Отправки через Yandex Cloud API (action=feedback)
"""

from qgis.PyQt.QtGui import QIcon

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.utils import log_info

from .submodules.Fsm_4_4_1_feedback_dialog import FeedbackDialog


class F_4_4_Feedback(BaseTool):
    """Инструмент обратной связи"""

    requires_license = True

    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "5_4 Обратная связь"

    @property
    def icon(self) -> QIcon:
        """Иконка инструмента"""
        return QIcon(':/images/themes/default/mActionHelpContents.svg')

    def create_dialog(self):
        """Создание диалога обратной связи"""
        log_info("F_4_4: Открыт диалог обратной связи")
        return FeedbackDialog(self.iface)
