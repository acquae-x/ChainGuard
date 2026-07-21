"""凭证静态加密。

**fail-closed**：库缺失或密钥缺失时抛 EncryptionUnavailable，任何情况下都不返回明文。
历史实现在这两种情况下只发一条 RuntimeWarning 然后原样返回入参，调用侧被迫用
"密文 == 明文" 这种脆弱的等值比较来识别降级；一旦某个新调用点忘了比较，明文就会
静默落库。契约改为抛异常后，忘记处理的结果是 500 而不是明文入库。

**密文带 KDF 版本前缀。** 需要版本化的原因不是"可能存在遗留明文"——`encrypt_bytes`
的两个调用者（sso.py / erp_integration.py）一直在写入前拒绝降级，明文写不进那两个
密文列。真正会让存量密文失效的是密钥派生方案本身的变更：

  无前缀        v1，裸 sha256(key)，本次改造之前写入的存量密文
  cgenc:v2:     v2，CHAINGUARD_ENCRYPTION_KEY 本身是合法 Fernet key 则直接使用，
                否则按口令用 scrypt 派生

sha256 与 scrypt 派生出的密钥不通用，不加前缀直接换 KDF 会让全部存量密文 InvalidToken。
读时按前缀选派生器（两代都能解），写时一律 v2；调用侧用 needs_rewrap() 判断存量密文
是否需要在下次写入时升级。

**轮换**：CHAINGUARD_ENCRYPTION_KEY_PREVIOUS 以逗号分隔承载旧密钥，MultiFernet 解密时
依次尝试，加密只用主密钥——换密钥无需停机回填。
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from typing import Any


ENV_KEY = "CHAINGUARD_ENCRYPTION_KEY"
ENV_PREVIOUS_KEYS = "CHAINGUARD_ENCRYPTION_KEY_PREVIOUS"

CIPHERTEXT_PREFIX_V2 = b"cgenc:v2:"

# scrypt 的盐是固定的应用常量，不是每条密文随机。这里能这么做，是因为被派生的是
# 一个高熵的部署密钥而非用户口令：固定盐要防的是跨应用彩虹表，而不是同库口令碰撞，
# 且密钥必须可重现地派生（密文列里没有存盐的位置）。真正推荐的用法仍是直接提供一个
# 合法 Fernet key，那条路径完全不走 KDF。
_SCRYPT_SALT = b"chainguard.credential.kdf.v2"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

_FERNET_KEY_CHARS = 44
_FERNET_KEY_BYTES = 32


class EncryptionUnavailable(RuntimeError):
    """加密不可用。fail-closed 契约：宁可拒绝读写，也不落/不吐明文。"""


def _fernet_classes() -> tuple[Any, Any]:
    try:
        from cryptography.fernet import Fernet, MultiFernet
    except ImportError as err:  # pragma: no cover - 依赖缺失属部署错误
        raise EncryptionUnavailable(
            "cryptography 未安装，凭证加密不可用。它已在 requirements.txt 显式声明，"
            "请重新安装依赖。"
        ) from err
    return Fernet, MultiFernet


def _key_material() -> list[str]:
    """主密钥在前，历史密钥在后。顺序即 MultiFernet 的解密尝试顺序。"""
    primary = os.environ.get(ENV_KEY, "").strip()
    if not primary:
        raise EncryptionUnavailable(f"{ENV_KEY} 未配置，凭证加密不可用。")
    previous = [
        item.strip()
        for item in os.environ.get(ENV_PREVIOUS_KEYS, "").split(",")
        if item.strip()
    ]
    return [primary, *previous]


@lru_cache(maxsize=16)
def _derive_v2(key_raw: str) -> bytes:
    """合法 Fernet key 直接采用；否则当作口令走 scrypt。"""
    try:
        if len(key_raw) == _FERNET_KEY_CHARS and len(base64.urlsafe_b64decode(key_raw)) == _FERNET_KEY_BYTES:
            return key_raw.encode("ascii")
    except Exception:
        pass  # 不是 base64，按口令处理
    digest = hashlib.scrypt(
        key_raw.encode("utf-8"),
        salt=_SCRYPT_SALT,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_FERNET_KEY_BYTES,
    )
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=16)
def _derive_v1(key_raw: str) -> bytes:
    """存量密文的派生方式：裸 sha256，无 KDF 无盐。仅用于解密，不再用于加密。"""
    return base64.urlsafe_b64encode(hashlib.sha256(key_raw.encode("utf-8")).digest())


def _multi_fernet(derive: Any) -> Any:
    Fernet, MultiFernet = _fernet_classes()
    try:
        return MultiFernet([Fernet(derive(key)) for key in _key_material()])
    except EncryptionUnavailable:
        raise
    except Exception as err:
        raise EncryptionUnavailable(f"{ENV_KEY} 不是有效的密钥材料：{err}") from err


def encrypt_bytes(data: bytes) -> bytes:
    """加密并打上 v2 前缀。加密不可用时抛 EncryptionUnavailable，绝不返回明文。"""
    return CIPHERTEXT_PREFIX_V2 + _multi_fernet(_derive_v2).encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    """按前缀选派生器解密。无前缀按 v1 存量处理，解密不可用时抛 EncryptionUnavailable。"""
    if data.startswith(CIPHERTEXT_PREFIX_V2):
        return _multi_fernet(_derive_v2).decrypt(data[len(CIPHERTEXT_PREFIX_V2):])
    return _multi_fernet(_derive_v1).decrypt(data)


def needs_rewrap(data: bytes) -> bool:
    """该密文是否用的是已淘汰的派生方案，需要在下次写入时以 v2 重新加密。"""
    return not data.startswith(CIPHERTEXT_PREFIX_V2)


def encryption_status() -> dict[str, Any]:
    """只读探针，本身不加解密、不抛异常——供 /security 面板与调用侧前置判断使用。"""
    try:
        from cryptography.fernet import Fernet  # noqa: F401

        library_available = True
    except Exception:
        library_available = False

    primary = os.environ.get(ENV_KEY, "").strip()
    key_configured = bool(primary)
    rotation_keys = len([i for i in os.environ.get(ENV_PREVIOUS_KEYS, "").split(",") if i.strip()])
    active = library_available and key_configured

    if not library_available:
        note = "cryptography 库缺失，凭证加解密不可用（fail-closed，不降级为明文）。"
    elif not key_configured:
        note = f"{ENV_KEY} 未配置，凭证加解密不可用（fail-closed，不降级为明文）。"
    else:
        derivation = "直接使用所提供的 Fernet 密钥" if _is_fernet_key(primary) else "scrypt 派生"
        note = f"Fernet 加密已启用（{derivation}）；可解密的历史密钥 {rotation_keys} 个。"

    return {
        "library_available": library_available,
        "key_configured": key_configured,
        "active": active,
        "algorithm": "Fernet(AES-128-CBC + HMAC)",
        "key_derivation": "fernet-key" if key_configured and _is_fernet_key(primary) else "scrypt",
        "rotation_keys": rotation_keys,
        "note": note,
    }


def _is_fernet_key(value: str) -> bool:
    try:
        return len(value) == _FERNET_KEY_CHARS and len(base64.urlsafe_b64decode(value)) == _FERNET_KEY_BYTES
    except Exception:
        return False
