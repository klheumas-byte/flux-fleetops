from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from flask import current_app
from pymongo.collection import Collection


IndexSpec = dict[str, Any]
INDEX_OPTION_KEYS = ("unique", "sparse", "expireAfterSeconds", "partialFilterExpression")


def _normalize_keys(keys: Sequence[tuple[str, int]]) -> tuple[tuple[str, int], ...]:
    return tuple((field, int(direction)) for field, direction in keys)


def _matching_index_exists(collection: Collection, keys: Sequence[tuple[str, int]], options: dict[str, Any]) -> bool:
    normalized_keys = _normalize_keys(keys)
    existing_indexes = collection.index_information()
    for index in existing_indexes.values():
        existing_keys = tuple((field, int(direction)) for field, direction in index.get("key", []))
        if existing_keys != normalized_keys:
            continue

        matches = True
        for option_key in INDEX_OPTION_KEYS:
            expected = options.get(option_key)
            actual = index.get(option_key)
            if expected != actual:
                matches = False
                break
        if matches:
            return True
    return False


def ensure_indexes_for_collection(collection: Collection, index_specs: Iterable[IndexSpec], *, collection_name: str) -> None:
    created_indexes: list[str] = []
    skipped_indexes: list[str] = []

    for spec in index_specs:
        keys = spec["keys"]
        options = dict(spec.get("options") or {})
        if _matching_index_exists(collection, keys, options):
            skipped_indexes.append(options.get("name") or str(_normalize_keys(keys)))
            continue

        index_name = collection.create_index(keys, **options)
        created_indexes.append(index_name)

    logger = current_app.logger
    if created_indexes:
        logger.info(
            "[Flux Indexes] Created %s indexes on %s: %s",
            len(created_indexes),
            collection_name,
            ", ".join(created_indexes),
        )
    else:
        logger.info("[Flux Indexes] No new indexes needed for %s", collection_name)

    if skipped_indexes:
        logger.debug(
            "[Flux Indexes] Existing indexes already satisfied for %s: %s",
            collection_name,
            ", ".join(skipped_indexes),
        )
