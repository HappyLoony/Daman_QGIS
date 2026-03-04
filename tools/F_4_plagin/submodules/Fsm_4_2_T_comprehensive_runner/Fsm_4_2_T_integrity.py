# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_integrity - Тесты integrity check (anti-tampering)

Проверяет устойчивость _verify_integrity() к методам обхода:
- JWT manipulation (no token, forged payload, missing claims)
- File tampering (modification, deletion, .pyc substitution)
- Runtime manipulation (monkey-patching hashlib, method override)
- Edge cases (empty hashes, non-dict claims, malformed JWT)

Основано на исследовании OWASP, HackTricks JWT, Python bytecode attacks.
"""

import os
import sys
import hashlib
import json
import base64
import shutil
import tempfile


class TestIntegrity:
    """Тесты anti-tampering integrity check для main_plugin._verify_integrity()"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.plugin_instance = None
        self.original_token = None
        self.token_mgr = None
        self.backup_files = {}  # {path: original_bytes}

    def run_all_tests(self):
        """Запуск всех тестов integrity check"""
        self.logger.section("ТЕСТ INTEGRITY: Anti-tampering проверка")

        try:
            self.test_01_init()
            self.test_02_normal_pass()
            self.test_03_no_token_bypass()
            self.test_04_malformed_jwt()
            self.test_05_no_integrity_claim()
            self.test_06_non_dict_integrity_claim()
            self.test_07_empty_hash_values()
            self.test_08_forged_jwt_matching_hashes()
            self.test_09_forged_jwt_wrong_hashes()
            self.test_10_file_modification_detected()
            self.test_11_file_missing_detected()
            self.test_12_monkey_patch_hashlib()
            self.test_13_monkey_patch_method()
            self.test_14_monkey_patch_token()
            self.test_15_pyc_bypass()
            self.test_16_json_decode_error()
            self.test_17_exception_does_not_pass()
        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов Integrity: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
        finally:
            self._restore_all()

        self.logger.summary()

    # === Setup / Helpers ===

    def _get_plugin_instance(self):
        """Получить экземпляр DamanQGIS из QGIS"""
        try:
            from qgis.utils import plugins
            if 'Daman_QGIS' in plugins:
                return plugins['Daman_QGIS']
        except Exception:
            pass
        return None

    def _save_token(self):
        """Сохранить текущий access token"""
        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import TokenManager
            self.token_mgr = TokenManager.get_instance()
            if self.token_mgr:
                self.original_token = self.token_mgr._access_token
        except Exception:
            pass

    def _restore_token(self):
        """Восстановить оригинальный access token"""
        if self.token_mgr and self.original_token is not None:
            self.token_mgr._access_token = self.original_token

    def _set_token(self, token_value):
        """Установить произвольный access token"""
        if self.token_mgr:
            self.token_mgr._access_token = token_value

    def _build_jwt(self, payload_dict):
        """Собрать фейковый JWT с произвольным payload (без подписи)"""
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
        ).rstrip(b'=').decode()

        payload = base64.urlsafe_b64encode(
            json.dumps(payload_dict).encode()
        ).rstrip(b'=').decode()

        signature = base64.urlsafe_b64encode(b'fake_signature').rstrip(b'=').decode()

        return f"{header}.{payload}.{signature}"

    def _compute_real_hashes(self):
        """Вычислить реальные SHA-256 хеши критических файлов"""
        if not self.plugin_instance:
            return {}

        hashes = {}
        for key, rel_path in self.plugin_instance.INTEGRITY_FILES.items():
            filepath = os.path.join(self.plugin_instance.plugin_dir, rel_path)
            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    hashes[key] = hashlib.sha256(f.read()).hexdigest()
        return hashes

    def _backup_file(self, filepath):
        """Сделать бэкап файла"""
        if os.path.exists(filepath) and filepath not in self.backup_files:
            self.backup_files[filepath] = open(filepath, 'rb').read()

    def _restore_file(self, filepath):
        """Восстановить файл из бэкапа"""
        if filepath in self.backup_files:
            with open(filepath, 'wb') as f:
                f.write(self.backup_files[filepath])
            del self.backup_files[filepath]

    def _restore_all(self):
        """Восстановить все изменения"""
        self._restore_token()
        for filepath in list(self.backup_files.keys()):
            self._restore_file(filepath)

    # === Tests ===

    def test_01_init(self):
        """ТЕСТ 1: Инициализация - получение plugin instance и token"""
        self.logger.section("1. Инициализация тестовой среды")

        self.plugin_instance = self._get_plugin_instance()
        self.logger.check(
            self.plugin_instance is not None,
            "Plugin instance получен",
            "Plugin instance не найден! Тесты будут пропущены"
        )

        if not self.plugin_instance:
            return

        self.logger.check(
            hasattr(self.plugin_instance, '_verify_integrity'),
            "Метод _verify_integrity существует",
            "Метод _verify_integrity отсутствует!"
        )

        self.logger.check(
            hasattr(self.plugin_instance, 'INTEGRITY_FILES'),
            "INTEGRITY_FILES определен",
            "INTEGRITY_FILES отсутствует!"
        )

        self.logger.data("Проверяемых файлов", str(len(self.plugin_instance.INTEGRITY_FILES)))

        self._save_token()
        self.logger.check(
            self.original_token is not None,
            "Access token получен из TokenManager",
            "Access token отсутствует (лицензия не активирована?)"
        )

    def test_02_normal_pass(self):
        """ТЕСТ 2: Нормальная работа - оригинальные файлы должны пройти"""
        self.logger.section("2. Нормальная работа (baseline)")

        if not self.plugin_instance or not self.original_token:
            self.logger.skip("Plugin или token недоступен")
            return

        self._restore_token()
        result = self.plugin_instance._verify_integrity()
        self.logger.check(
            result is True,
            "Integrity check пройден с оригинальными файлами",
            "Integrity check не пройден даже с оригинальными файлами!"
        )

    def test_03_no_token_bypass(self):
        """ТЕСТ 3: Bypass через удаление токена

        Атака: очистить access_token до вызова проверки.
        Текущее поведение: return True (проверка пропускается).
        Это допустимо только до активации лицензии.
        """
        self.logger.section("3. JWT bypass: нет токена")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        self._set_token(None)
        result = self.plugin_instance._verify_integrity()
        self._restore_token()

        # Документируем поведение: без токена проверка пропускается
        self.logger.check(
            result is True,
            "Без токена: return True (ожидаемо -- нет JWT = нечего проверять)",
            "Без токена: неожиданный результат"
        )
        self.logger.warning(
            "ВЕКТОР АТАКИ: если атакующий очистит token до проверки, "
            "integrity check пропускается. Рекомендация: проверять наличие "
            "токена как обязательное условие после активации лицензии."
        )

    def test_04_malformed_jwt(self):
        """ТЕСТ 4: Malformed JWT (не 3 части)

        Атака: подставить невалидный JWT чтобы вызвать ранний return.
        """
        self.logger.section("4. JWT bypass: malformed token")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        malformed_tokens = [
            ("пустая строка", ""),
            ("одна часть", "header_only"),
            ("две части", "header.payload"),
            ("четыре части", "a.b.c.d"),
            ("мусорные данные", "!@#$%^&*()"),
        ]

        for name, token in malformed_tokens:
            self._set_token(token)
            result = self.plugin_instance._verify_integrity()

            if token == "":
                # Пустая строка -- falsy, как None
                self.logger.check(
                    result is True,
                    f"Malformed ({name}): return True (falsy token = нет проверки)",
                    f"Malformed ({name}): неожиданный результат"
                )
            elif token.count('.') != 2:
                # Не 3 части
                self.logger.check(
                    result is True,
                    f"Malformed ({name}): return True (не JWT формат)",
                    f"Malformed ({name}): неожиданный результат"
                )
            else:
                # Невалидный base64 payload -> JSONDecodeError -> return False
                self.logger.check(
                    result is False,
                    f"Malformed ({name}): return False (fail-closed)",
                    f"Malformed ({name}): return True -- BYPASS!"
                )

        self._restore_token()

    def test_05_no_integrity_claim(self):
        """ТЕСТ 5: JWT без integrity claim

        Атака: подставить JWT с валидным payload но без 'integrity'.
        Текущее поведение: return True (сервер не включил claim).
        """
        self.logger.section("5. JWT bypass: нет integrity claim")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        fake_jwt = self._build_jwt({"sub": "test", "type": "access"})
        self._set_token(fake_jwt)
        result = self.plugin_instance._verify_integrity()
        self._restore_token()

        self.logger.check(
            result is True,
            "Без integrity claim: return True (ожидаемо -- нечего сравнивать)",
            "Без integrity claim: неожиданный результат"
        )
        self.logger.warning(
            "ВЕКТОР АТАКИ: forged JWT без integrity claim обходит проверку. "
            "Рекомендация: требовать integrity claim если токен присутствует."
        )

    def test_06_non_dict_integrity_claim(self):
        """ТЕСТ 6: integrity claim не dict (list, string, number, null)

        Атака: подставить integrity = [] или "string" чтобы пройти isinstance check.
        """
        self.logger.section("6. JWT bypass: невалидный тип integrity claim")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        invalid_claims = [
            ("null", {"integrity": None}),
            ("empty list", {"integrity": []}),
            ("string", {"integrity": "not_a_dict"}),
            ("number", {"integrity": 42}),
            ("true", {"integrity": True}),
            ("empty string", {"integrity": ""}),
        ]

        for name, payload in invalid_claims:
            fake_jwt = self._build_jwt(payload)
            self._set_token(fake_jwt)
            result = self.plugin_instance._verify_integrity()

            # Все non-dict должны вернуть True (isinstance check)
            self.logger.check(
                result is True,
                f"integrity={name}: return True (не dict = пропуск)",
                f"integrity={name}: неожиданный результат"
            )

        self._restore_token()

    def test_07_empty_hash_values(self):
        """ТЕСТ 7: integrity claim с пустыми значениями хешей

        Атака: {"integrity": {"main_plugin": "", "msm_29_3": null}}
        Строка 640-642: if not expected: continue -- пропускает файл.
        """
        self.logger.section("7. JWT bypass: пустые значения хешей")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        # Все ключи с пустыми значениями
        empty_hashes = {key: "" for key in self.plugin_instance.INTEGRITY_FILES}
        fake_jwt = self._build_jwt({"integrity": empty_hashes})
        self._set_token(fake_jwt)
        result = self.plugin_instance._verify_integrity()
        self._restore_token()

        # Пустые значения = continue для всех файлов = нет mismatches = True
        self.logger.check(
            result is True,
            "Пустые хеши: return True (все файлы пропущены через continue)",
            "Пустые хеши: неожиданный результат"
        )
        self.logger.warning(
            "ВЕКТОР АТАКИ: JWT с пустыми хешами обходит все проверки. "
            "Рекомендация: считать пустой хеш = mismatch."
        )

    def test_08_forged_jwt_matching_hashes(self):
        """ТЕСТ 8: Forged JWT с правильными хешами

        Атака: вычислить реальные хеши и подставить в forged JWT.
        JWT payload декодируется БЕЗ верификации подписи.
        """
        self.logger.section("8. JWT forgery: подмена с правильными хешами")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        real_hashes = self._compute_real_hashes()
        if not real_hashes:
            self.logger.fail("Не удалось вычислить реальные хеши")
            return

        fake_jwt = self._build_jwt({"integrity": real_hashes})
        self._set_token(fake_jwt)
        result = self.plugin_instance._verify_integrity()
        self._restore_token()

        # Forged JWT с правильными хешами ПРОЙДЕТ проверку
        self.logger.check(
            result is True,
            "Forged JWT с реальными хешами: return True (ожидаемо)",
            "Forged JWT с реальными хешами: return False"
        )
        self.logger.warning(
            "ВЕКТОР АТАКИ: JWT декодируется без верификации подписи. "
            "Атакующий может сгенерировать свой JWT с правильными хешами. "
            "Рекомендация: верифицировать JWT подпись на клиенте (требует public key)."
        )

    def test_09_forged_jwt_wrong_hashes(self):
        """ТЕСТ 9: Forged JWT с неправильными хешами

        Проверяет что подмена хешей на произвольные БЛОКИРУЕТ плагин.
        """
        self.logger.section("9. Integrity block: неправильные хеши")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        wrong_hashes = {key: "a" * 64 for key in self.plugin_instance.INTEGRITY_FILES}
        fake_jwt = self._build_jwt({"integrity": wrong_hashes})
        self._set_token(fake_jwt)
        result = self.plugin_instance._verify_integrity()
        self._restore_token()

        self.logger.check(
            result is False,
            "Неправильные хеши: return False (БЛОКИРОВКА)",
            "Неправильные хеши: return True -- BYPASS!"
        )

    def test_10_file_modification_detected(self):
        """ТЕСТ 10: Модификация файла обнаруживается

        Модифицируем один из проверяемых файлов и проверяем блокировку.
        """
        self.logger.section("10. File tampering: модификация файла")

        if not self.plugin_instance or not self.original_token:
            self.logger.skip("Plugin или token недоступен")
            return

        # Берём наименее критичный файл для модификации
        target_key = 'base_ref'
        rel_path = self.plugin_instance.INTEGRITY_FILES.get(target_key)
        if not rel_path:
            self.logger.skip("base_ref не найден в INTEGRITY_FILES")
            return

        filepath = os.path.join(self.plugin_instance.plugin_dir, rel_path)
        if not os.path.exists(filepath):
            self.logger.skip(f"Файл не существует: {filepath}")
            return

        self._backup_file(filepath)
        self._restore_token()

        try:
            # Добавляем комментарий в конец файла
            with open(filepath, 'ab') as f:
                f.write(b'\n# integrity test modification\n')

            result = self.plugin_instance._verify_integrity()

            self.logger.check(
                result is False,
                f"Модификация {target_key}: return False (ОБНАРУЖЕНА)",
                f"Модификация {target_key}: return True -- НЕ ОБНАРУЖЕНА!"
            )
        finally:
            self._restore_file(filepath)

    def test_11_file_missing_detected(self):
        """ТЕСТ 11: Удаление файла обнаруживается"""
        self.logger.section("11. File tampering: удаление файла")

        if not self.plugin_instance or not self.original_token:
            self.logger.skip("Plugin или token недоступен")
            return

        target_key = 'base_ref'
        rel_path = self.plugin_instance.INTEGRITY_FILES.get(target_key)
        if not rel_path:
            self.logger.skip("base_ref не найден в INTEGRITY_FILES")
            return

        filepath = os.path.join(self.plugin_instance.plugin_dir, rel_path)
        if not os.path.exists(filepath):
            self.logger.skip(f"Файл не существует: {filepath}")
            return

        self._backup_file(filepath)
        self._restore_token()

        try:
            os.rename(filepath, filepath + '.bak_test')

            result = self.plugin_instance._verify_integrity()

            self.logger.check(
                result is False,
                f"Удаление {target_key}: return False (ОБНАРУЖЕНО)",
                f"Удаление {target_key}: return True -- НЕ ОБНАРУЖЕНО!"
            )
        finally:
            # Восстанавливаем
            if os.path.exists(filepath + '.bak_test'):
                os.rename(filepath + '.bak_test', filepath)
            self._restore_file(filepath)

    def test_12_monkey_patch_hashlib(self):
        """ТЕСТ 12: Monkey-patching hashlib.sha256

        Атака: подменить hashlib.sha256 на функцию возвращающую нужный хеш.
        Проверяем что после патча integrity check всё равно работает корректно.
        """
        self.logger.section("12. Runtime attack: monkey-patch hashlib")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        # Сначала убедимся что с оригинальным токеном проверка проходит
        self._restore_token()

        # Сохраняем оригинальный hashlib.sha256
        original_sha256 = hashlib.sha256

        # Подставляем forged JWT с заведомо неправильными хешами
        wrong_hashes = {key: "b" * 64 for key in self.plugin_instance.INTEGRITY_FILES}
        fake_jwt = self._build_jwt({"integrity": wrong_hashes})
        self._set_token(fake_jwt)

        try:
            # Monkey-patch: sha256 всегда возвращает хеш "b" * 64
            class FakeSHA256:
                def __init__(self, data=b''):
                    pass

                def hexdigest(self):
                    return "b" * 64

            hashlib.sha256 = FakeSHA256

            result = self.plugin_instance._verify_integrity()

            # С monkey-patched hashlib, все хеши совпадут с wrong_hashes
            self.logger.check(
                result is True,
                "Monkey-patched hashlib: проверка пройдена (хеши совпали с подменой)",
                "Monkey-patched hashlib: проверка не пройдена"
            )
            self.logger.warning(
                "ВЕКТОР АТАКИ: monkey-patching hashlib.sha256 позволяет обойти проверку. "
                "Рекомендация: импортировать hashlib в замыкании или использовать _hashlib напрямую."
            )
        finally:
            hashlib.sha256 = original_sha256
            self._restore_token()

    def test_13_monkey_patch_method(self):
        """ТЕСТ 13: Прямая подмена _verify_integrity

        Атака: заменить метод на lambda: True до вызова.
        """
        self.logger.section("13. Runtime attack: подмена _verify_integrity")

        if not self.plugin_instance:
            self.logger.skip("Plugin недоступен")
            return

        original_method = self.plugin_instance.__class__._verify_integrity

        try:
            # Подменяем метод
            self.plugin_instance.__class__._verify_integrity = lambda self: True

            result = self.plugin_instance._verify_integrity()

            self.logger.check(
                result is True,
                "Подмена метода: return True (метод заменён)",
                "Подмена метода: неожиданный результат"
            )
            self.logger.warning(
                "ВЕКТОР АТАКИ: _verify_integrity можно заменить через monkey-patch. "
                "Это фундаментальное ограничение клиентской проверки в Python. "
                "Рекомендация: серверная верификация (клиент отправляет хеши на сервер)."
            )
        finally:
            self.plugin_instance.__class__._verify_integrity = original_method

    def test_14_monkey_patch_token(self):
        """ТЕСТ 14: Подмена access_token в TokenManager

        Атака: заменить _access_token на forged JWT с правильными хешами.
        """
        self.logger.section("14. Runtime attack: подмена access_token")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        real_hashes = self._compute_real_hashes()
        if not real_hashes:
            self.logger.fail("Не удалось вычислить реальные хеши")
            return

        forged_jwt = self._build_jwt({"integrity": real_hashes})
        self._set_token(forged_jwt)
        result = self.plugin_instance._verify_integrity()
        self._restore_token()

        self.logger.check(
            result is True,
            "Forged token с real hashes: return True (обход)",
            "Forged token с real hashes: return False"
        )
        self.logger.warning(
            "ВЕКТОР АТАКИ: замена _access_token на forged JWT обходит проверку, "
            "т.к. подпись JWT не верифицируется на клиенте."
        )

    def test_15_pyc_bypass(self):
        """ТЕСТ 15: .pyc bypass -- integrity проверяет .py, Python выполняет .pyc

        Проверяем что __pycache__ существует для проверяемых файлов.
        Если да -- это потенциальный вектор атаки.
        """
        self.logger.section("15. Bytecode attack: .pyc bypass")

        if not self.plugin_instance:
            self.logger.skip("Plugin недоступен")
            return

        pyc_found = 0
        for key, rel_path in self.plugin_instance.INTEGRITY_FILES.items():
            filepath = os.path.join(self.plugin_instance.plugin_dir, rel_path)
            dir_path = os.path.dirname(filepath)
            filename = os.path.basename(filepath)
            pycache_dir = os.path.join(dir_path, '__pycache__')

            if os.path.exists(pycache_dir):
                # Ищем .pyc файлы для этого модуля
                module_name = filename.replace('.py', '')
                pyc_files = [
                    f for f in os.listdir(pycache_dir)
                    if f.startswith(module_name) and f.endswith('.pyc')
                ]
                if pyc_files:
                    pyc_found += 1
                    self.logger.data(f"  {key}", f"{len(pyc_files)} .pyc файлов")

        if pyc_found > 0:
            self.logger.warning(
                f"ВЕКТОР АТАКИ: {pyc_found} из {len(self.plugin_instance.INTEGRITY_FILES)} "
                "проверяемых файлов имеют .pyc в __pycache__. Integrity проверяет .py, "
                "но Python может выполнять .pyc. Рекомендация: также проверять .pyc "
                "или удалять __pycache__ перед проверкой."
            )
        else:
            self.logger.success("Нет .pyc файлов для проверяемых модулей")

    def test_16_json_decode_error(self):
        """ТЕСТ 16: JWT с невалидным base64 payload -> JSONDecodeError

        Проверяем fail-closed: ошибка декодирования = блокировка.
        """
        self.logger.section("16. Fail-closed: JSONDecodeError")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        # JWT с мусором в payload
        garbage_jwt = "eyJhbGciOiJIUzI1NiJ9.NOT_VALID_BASE64!@#$.fakesig"
        self._set_token(garbage_jwt)
        result = self.plugin_instance._verify_integrity()
        self._restore_token()

        self.logger.check(
            result is False,
            "JSONDecodeError: return False (fail-closed)",
            "JSONDecodeError: return True -- BYPASS через невалидный payload!"
        )

    def test_17_exception_does_not_pass(self):
        """ТЕСТ 17: Любое исключение = fail-closed

        Проверяем что непредвиденные ошибки не приводят к bypass.
        """
        self.logger.section("17. Fail-closed: generic exception")

        if not self.plugin_instance or not self.token_mgr:
            self.logger.skip("Plugin или TokenManager недоступен")
            return

        # JWT с валидным base64 но содержащим не-JSON
        # base64("This is not JSON") = VGhpcyBpcyBub3QgSlNPTg
        not_json_payload = base64.urlsafe_b64encode(b'This is not JSON').rstrip(b'=').decode()
        bad_jwt = f"eyJhbGciOiJIUzI1NiJ9.{not_json_payload}.fakesig"
        self._set_token(bad_jwt)
        result = self.plugin_instance._verify_integrity()
        self._restore_token()

        self.logger.check(
            result is False,
            "Generic exception: return False (fail-closed)",
            "Generic exception: return True -- BYPASS!"
        )
