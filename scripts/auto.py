"""Bank access for the drivers - thin shim over `bank.py`.

Kept only so older notes/scripts that `import auto` keep working. All logic
lives in bank.py, which is browser-free and covered by selftest.py.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bank as _bank  # noqa: E402
import config  # noqa: E402

BANK = config.BANK

norm = _bank.norm
near = _bank.near
put = _bank.put
parse_point = _bank.parse_point
stalled = _bank.stalled


def load():
    return _bank.load(BANK)


def save(b):
    _bank.save(b, BANK)


def lookup(b, stem):
    return _bank.lookup(b, stem)


def learn(items, source=None):
    """Fold harvested items into the bank. Returns (total, new_keys)."""
    b = load()
    new = 0
    for it in items or []:
        if put(b, it.get("stem", ""), it.get("letters"), it.get("typeName"),
               it.get("opts"), source=source):
            new += 1
    save(b)
    return len(b), new
