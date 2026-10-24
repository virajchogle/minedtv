"""Picks ML implementations from config: "stub", "modal", or "package.module:ClassName"."""

import importlib
from functools import lru_cache

from app.config import get_settings
from app.ml.interfaces import Embedder, HighlightDetector, Transcriber


def _load(spec: str, stub, modal_attr: str | None):
    if spec == "stub":
        return stub()
    if spec == "modal":
        if modal_attr is None:
            raise ValueError("No Modal implementation for this interface; use stub or a module path")
        from app.ml import modal_adapter

        return getattr(modal_adapter, modal_attr)()
    module_name, _, attr = spec.partition(":")
    if not attr:
        raise ValueError(f"Expected 'package.module:ClassName', got {spec!r}")
    return getattr(importlib.import_module(module_name), attr)()


@lru_cache
def get_embedder() -> Embedder:
    from app.ml.stubs import StubEmbedder

    embedder = _load(get_settings().embedder_backend, StubEmbedder, "ModalEmbedder")
    if embedder.dim != get_settings().embedding_dim:
        raise ValueError(
            f"Embedder dim {embedder.dim} != EMBEDDING_DIM {get_settings().embedding_dim}; "
            "change EMBEDDING_DIM (and migrate) or the model"
        )
    return embedder


@lru_cache
def get_transcriber() -> Transcriber:
    from app.ml.stubs import StubTranscriber

    return _load(get_settings().transcriber_backend, StubTranscriber, "ModalTranscriber")


@lru_cache
def get_highlight_detector() -> HighlightDetector:
    from app.ml.stubs import StubHighlightDetector

    return _load(get_settings().highlight_backend, StubHighlightDetector, None)
