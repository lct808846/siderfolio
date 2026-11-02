"""Conservative literal-query admission and bounded, process-local query vectors."""

import re
import threading
import time
from collections import OrderedDict

from astroagent.knowledge_text import checksum, normalize


def requires_literal_anchor(question):
    """Compact ASCII terms/catalogue IDs need an original-text match or more context.

    Natural-language sentences and CJK questions remain eligible for semantic-only
    retrieval. This is an ambiguity guard, not a classifier of scientific support.
    """
    value = normalize(question).strip(" \t\r\n\"'“”‘’?!。！？")
    if not re.search(r"\w", value):
        return True
    return bool(
        re.fullmatch(r"[+-]?[a-z0-9][a-z0-9_.:+/-]*", value)
        or re.fullmatch(r"[a-z]{1,12}\s+\d[a-z0-9_.:+/-]*", value)
    )


def query_cache_key(project_id, model_sha256, dimension, question):
    # Keep neither raw questions nor document text in cache keys.
    return project_id, model_sha256, dimension, checksum(question)


class QueryVectorCache:
    def __init__(self, capacity=32, ttl_seconds=300, clock=time.monotonic):
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def _expire(self, now):
        for key in [key for key, (expires, _) in self.entries.items() if expires <= now]:
            del self.entries[key]

    def get(self, key):
        with self.lock:
            self._expire(self.clock())
            value = self.entries.get(key)
            if value is None:
                return None
            self.entries.move_to_end(key)
            return list(value[1])

    def put(self, key, vector):
        if self.capacity <= 0:
            return
        with self.lock:
            now = self.clock()
            self._expire(now)
            self.entries[key] = now + self.ttl_seconds, tuple(vector)
            self.entries.move_to_end(key)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
