# -*- coding: utf-8 -*-

import json
from pathlib import Path
from typing import Any, Dict, cast

DATA_DIR = Path(__file__).parent / "data"

_PERSIST_STORAGE_DIR = Path(__file__).parent.parent / "runtime"


class PersistDictStorage:
    def __init__(self, name: str):
        self.name = name.lower()
        self._filepath: Path = _PERSIST_STORAGE_DIR / f"{self.name}.json"
        self._cache: Dict[str, Any] = dict()

        if self._filepath.exists():
            self._cache = json.loads(self._filepath.read_text())
        else:
            _PERSIST_STORAGE_DIR.mkdir(exist_ok=True)

    def _flush_cache(self) -> None:
        text = json.dumps(self._cache)
        self._filepath.write_text(text)

    def read_str(self, key: str) -> str:
        return cast(str, self._cache[key])

    def store_str(self, key: str, value: str) -> None:
        self._cache[key] = value
        self._flush_cache()

    def read_json(self, key: str) -> Dict[str, Any]:
        return cast(Dict[str, Any], self._cache[key])

    def write_json(self, key: str, value: Dict[str, Any]) -> None:
        self._cache[key] = value
        self._flush_cache()
