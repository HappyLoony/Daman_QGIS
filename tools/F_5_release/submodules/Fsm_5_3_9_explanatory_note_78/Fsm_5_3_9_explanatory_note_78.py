# -*- coding: utf-8 -*-
"""Fsm_5_3_9 — Координатор экспорта пояснительной записки региона 78.

Точка входа из Fsm_5_3_3_DocumentFactory.export() при doc_type='explanatory_note'.
Маршрутизирует подготовку данных, рендер штампа и сборку тела через 4 субсубмодуля.
"""
import os
from typing import Optional, Dict, Any

from Daman_QGIS.utils import log_info, log_error, log_warning


class Fsm_5_3_9_ExplanatoryNote78:
    """Координатор экспорта пояснительной записки региона 78 (СПб, ПМТ)."""

    DEFAULT_FILENAME = '_Пояснительная_записка.docx'

    def __init__(self, iface, ref_managers=None):
        self.iface = iface
        self.ref_managers = ref_managers

    def export(self, output_folder: str,
               extra_context: Optional[Dict[str, Any]] = None) -> bool:
        """Экспорт _Пояснительная_записка.docx в output_folder.

        Args:
            output_folder: Корень папки экспорта (рядом с подпапками
                «Земельные участки» и «Сервитуты, публичные сервитуты»).
            extra_context: Контекст от Region78FormatModifier
                (filename_override, subfolder, progress_callback и т.п.).
                progress_callback: callable(msg: str, percent: int) — опц.,
                для обновления QProgressDialog в F_5_3.

        Returns:
            True при успехе, False при критической ошибке.
        """
        log_info("Fsm_5_3_9 (export): запуск")
        extra_context = extra_context or {}
        progress_cb = extra_context.get('progress_callback')

        def _report(msg: str, percent: int) -> None:
            """Безопасный вызов progress_callback (если передан)."""
            if progress_cb is not None:
                try:
                    progress_cb(msg, percent)
                except Exception as cb_err:
                    log_warning(f"Fsm_5_3_9 (progress_callback): {cb_err}")

        try:
            # 1. Метаданные проекта
            _report('Чтение метаданных проекта', 5)
            from ..Fsm_5_3_5_export_utils import ExportUtils
            metadata = ExportUtils.get_project_metadata()

            # 2. Сбор данных T1-T7
            _report('Сбор данных по 7 таблицам', 10)
            from .Fsm_5_3_9_1_data_collector import ExplanatoryNoteDataCollector
            # export_folder передаётся для переиспользования merged Excel
            # перечня координат (T5/T6 — в 50-100x быстрее vs сбор через слои).
            collector = ExplanatoryNoteDataCollector(
                self.iface, self.ref_managers, export_folder=output_folder,
            )
            data = collector.collect_all(progress_callback=progress_cb)

            # 3. Штамп ГОСТ
            _report('Построение штампа ГОСТ 21.101-2020', 70)
            from .Fsm_5_3_9_4_styles import ExplanatoryNoteStyles
            from .Fsm_5_3_9_3_stamp import ExplanatoryNoteStamp
            styles = ExplanatoryNoteStyles()
            stamp = ExplanatoryNoteStamp(styles=styles)
            doc = stamp.build_stamp(metadata)

            # 4. Тело документа
            _report('Сборка тела документа', 78)
            from .Fsm_5_3_9_2_doc_builder import ExplanatoryNoteDocBuilder
            builder = ExplanatoryNoteDocBuilder(styles)
            builder.build_body(doc, data, metadata, progress_callback=progress_cb)

            # 5. Сохранение
            _report('Сохранение _Пояснительная_записка.docx', 95)
            filename = self._build_filename(extra_context)
            output_path = self._build_output_path(output_folder, extra_context, filename)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            doc.save(output_path)

            _report('Готово', 100)
            log_info(f"Fsm_5_3_9 (export): документ сохранён: {output_path}")
            return True

        except Exception as e:
            log_error(f"Fsm_5_3_9 (export): {e}")
            return False

    @staticmethod
    def _build_filename(extra_context: Dict[str, Any]) -> str:
        """Имя выходного файла. Из extra_context или DEFAULT_FILENAME."""
        override = extra_context.get('filename_override', '')
        if override:
            base = str(override).strip()
            if not base.lower().endswith('.docx'):
                base = base + '.docx'
            return base
        return Fsm_5_3_9_ExplanatoryNote78.DEFAULT_FILENAME

    @staticmethod
    def _build_output_path(output_folder: str,
                           extra_context: Dict[str, Any],
                           filename: str) -> str:
        """Полный путь: output_folder + (опц. subfolder) + filename."""
        subfolder = str(extra_context.get('subfolder') or '').strip()
        if subfolder:
            return os.path.join(output_folder, subfolder, filename)
        return os.path.join(output_folder, filename)
