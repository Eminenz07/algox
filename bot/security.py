import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def _get_key(key_hex: str) -> bytes:
    # Convert hex key to bytes (must be exactly 32 bytes for AES-256)
    key_bytes = bytes.fromhex(key_hex)
    if len(key_bytes) != 32:
        # Fallback padding/truncation just in case, but hex key should be 64 characters long (32 bytes)
        key_bytes = key_bytes[:32].ljust(32, b'\x00')
    return key_bytes

def encrypt_text(plain_text: str, key_hex: str) -> tuple[str, str]:
    """
    Encrypts plain_text using AES-256-GCM.
    Returns (ciphertext_hex, iv_hex).
    """
    if not plain_text:
        return "", ""
    aesgcm = AESGCM(_get_key(key_hex))
    iv = os.urandom(12)  # GCM recommended IV size is 12 bytes
    ciphertext = aesgcm.encrypt(iv, plain_text.encode('utf-8'), None)
    return ciphertext.hex(), iv.hex()

def decrypt_text(ciphertext_hex: str, iv_hex: str, key_hex: str) -> str:
    """
    Decrypts ciphertext_hex using AES-256-GCM and iv_hex.
    Returns plain_text.
    """
    if not ciphertext_hex or not iv_hex:
        return ""
    aesgcm = AESGCM(_get_key(key_hex))
    ciphertext = bytes.fromhex(ciphertext_hex)
    iv = bytes.fromhex(iv_hex)
    decrypted_bytes = aesgcm.decrypt(iv, ciphertext, None)
    return decrypted_bytes.decode('utf-8')
