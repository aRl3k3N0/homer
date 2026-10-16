import os
import time
import uuid


def uuid_v7() -> str:
    """Генерирует UUID версии 7 (RFC 9562) и возвращает строку вида '0193e1e3-a6ee-7411-9c5c-0e448fd93911'."""
    # 48-битная временная метка в миллисекундах
    unix_ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF

    # 80 бит случайности: 2 байта rand_a + 8 байт rand_b
    rand_a = os.urandom(2)
    rand_b = os.urandom(8)

    uuid_int = (
        (unix_ts_ms << 80)
        | (0x7 << 76)                              # version = 7 (биты 76..79)
        | (int.from_bytes(rand_a, "big") << 64)    # rand_a (биты 64..79)
        | (0b10 << 62)                             # variant = 10 (биты 62..63)
        | int.from_bytes(rand_b, "big")            # rand_b (биты 0..61)
    )

    return str(uuid.UUID(int=uuid_int))
