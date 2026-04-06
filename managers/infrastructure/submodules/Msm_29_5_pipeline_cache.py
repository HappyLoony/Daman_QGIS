# -*- coding: utf-8 -*-
"""
Msm_29_5_PipelineCache - RAM-only cache for pipeline CRS strings.

Pipelines arrive encrypted via /validate response (AES-256-GCM).
Decrypted on arrival, stored XOR-obfuscated in memory (IP protection).
Singleton: one instance per QGIS session.
"""

import os
import base64
import hashlib
from itertools import cycle
from typing import Dict, Optional

from Daman_QGIS.utils import log_info, log_warning, log_error


class PipelineCache:
    """RAM-only cache for pipeline strings with XOR obfuscation."""

    _instance: Optional['PipelineCache'] = None

    def __init__(self):
        self._pipelines: Dict[str, bytearray] = {}
        self._mask: bytes = os.urandom(32)

    @classmethod
    def get_instance(cls) -> 'PipelineCache':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        if cls._instance:
            for key in cls._instance._pipelines:
                arr = cls._instance._pipelines[key]
                for i in range(len(arr)):
                    arr[i] = 0
            cls._instance._pipelines.clear()
            cls._instance._mask = b'\x00' * 32
        cls._instance = None

    def set_pipelines_encrypted(
        self,
        encrypted_pipelines: Dict[str, dict],
        hardware_id: str,
        api_key: str,
    ) -> None:
        """Decrypt AES-256-GCM pipelines from /validate and store XOR-obfuscated.

        Args:
            encrypted_pipelines: {region_code: {data: base64, salt: base64}}
            hardware_id: Hardware ID used as key material
            api_key: API key used as key material
        """
        from time import perf_counter

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            from cryptography.hazmat.primitives import hashes
        except ImportError:
            log_error("Msm_29_5: cryptography library not available")
            return

        _t_total = perf_counter()
        _t_pbkdf2_sum = 0.0
        _t_aes_sum = 0.0
        count = 0
        for region_code, enc_data in encrypted_pipelines.items():
            try:
                packed = base64.b64decode(enc_data["data"])
                salt = base64.b64decode(enc_data["salt"])

                key_material = f"{hardware_id}{api_key}".encode("utf-8")

                _t_kdf = perf_counter()
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=10_000,
                )
                key = kdf.derive(key_material)
                _t_pbkdf2_sum += perf_counter() - _t_kdf

                nonce = packed[:12]
                ciphertext_and_tag = packed[12:]
                aad = f"{region_code}|{hardware_id}".encode("utf-8")

                _t_aes = perf_counter()
                aesgcm = AESGCM(key)
                plaintext = aesgcm.decrypt(nonce, ciphertext_and_tag, aad)
                _t_aes_sum += perf_counter() - _t_aes

                pipeline_str = plaintext.decode("utf-8")

                pipeline_bytes = pipeline_str.encode("utf-8")
                obfuscated = bytearray(
                    a ^ b for a, b in zip(pipeline_bytes, cycle(self._mask))
                )
                self._pipelines[region_code] = obfuscated
                count += 1

            except Exception as e:
                log_warning(f"Msm_29_5: Failed to decrypt pipeline for {region_code}: {e}")

        _elapsed = perf_counter() - _t_total
        _avg = _elapsed / count if count else 0
        log_info(
            f"Msm_29_5: Cached {count} pipelines (encrypted delivery) "
            f"| [TIMING] total: {_elapsed:.3f}s, "
            f"PBKDF2: {_t_pbkdf2_sum:.3f}s, AES: {_t_aes_sum:.3f}s, "
            f"avg: {_avg:.4f}s/pipeline"
        )

    def get_pipeline(self, region_code: str) -> Optional[str]:
        """Get pipeline for a specific region (deobfuscates on read)."""
        obfuscated = self._pipelines.get(region_code)
        if obfuscated is None:
            return None
        try:
            plaintext = bytes(
                a ^ b for a, b in zip(obfuscated, cycle(self._mask))
            )
            return plaintext.decode("utf-8")
        except Exception as e:
            log_error(f"Msm_29_5: Failed to deobfuscate pipeline for {region_code}: {e}")
            return None

    def has_pipelines(self) -> bool:
        return bool(self._pipelines)
