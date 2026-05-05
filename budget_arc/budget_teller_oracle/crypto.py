from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


def generate_master_key() -> str:
    return Fernet.generate_key().decode("ascii")


class TokenCipher:
    def __init__(self, master_key: str):
        self._fernet = Fernet(master_key.encode("ascii"))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Unable to decrypt stored Teller token with current key") from exc

