from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305, AESCCM, AESGCM

__all__ = ["AEAD"]


class AES_128_GCM(AESGCM):
    def __init__(self, key: bytes):
        key = key[: 128 // 8]
        super().__init__(key)


class AES_192_GCM(AESGCM):
    def __init__(self, key: bytes):
        key = key[: 192 // 8]
        super().__init__(key)


class AES_256_GCM(AESGCM):
    def __init__(self, key: bytes):
        key = key[: 256 // 8]
        super().__init__(key)


class AES_128_CCM(AESCCM):
    def __init__(self, key: bytes):
        key = key[: 128 // 8]
        super().__init__(key)


class AES_192_CCM(AESCCM):
    def __init__(self, key: bytes):
        key = key[: 192 // 8]
        super().__init__(key)


class AES_256_CCM(AESCCM):
    def __init__(self, key: bytes):
        key = key[: 256 // 8]
        super().__init__(key)


AEAD = {
    "chacha20-poly1305": ChaCha20Poly1305,
    "aes-128-gcm": AES_128_GCM,
    "aes-192-gcm": AES_192_GCM,
    "aes-256-gcm": AES_256_GCM,
    "aes-128-ccm": AES_128_CCM,
    "aes-192-ccm": AES_192_CCM,
    "aes-256-ccm": AES_256_CCM,
}
