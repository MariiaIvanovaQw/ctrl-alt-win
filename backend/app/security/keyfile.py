"""
Ключи подписи в файлах data/keys/.

При запуске нескольких процессов (uvicorn --workers N) все они должны
подписывать токены одним ключом. Файл создаётся атомарно (O_EXCL): процесс,
который не успел первым, читает ключ победителя, а не перезаписывает его.
"""

import os
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def load_or_create_rsa(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass  # другой процесс создал ключ раньше — используем его
        else:
            with os.fdopen(fd, "wb") as fh:
                fh.write(pem)
            return key
    for _ in range(50):  # файл мог быть создан, но ещё не дописан
        data = path.read_bytes()
        if data.strip().endswith(b"-----END PRIVATE KEY-----"):
            return serialization.load_pem_private_key(data, password=None)
        time.sleep(0.05)
    raise RuntimeError("Повреждён файл ключа %s" % path)
