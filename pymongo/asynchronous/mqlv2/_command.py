"""Pipeline wrapper and Mqlv2Source protocol for db.mqlv2()."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pymongo.asynchronous.mqlv2 import _ast
from pymongo.asynchronous.mqlv2._serializer import Serializer


@runtime_checkable
class Mqlv2Source(Protocol):
    """Any object that can produce a MQLv2 query string."""

    def to_mqlv2(self) -> str: ...


class Pipeline:
    """Wraps a root Stage AST node; implements Mqlv2Source for db.mqlv2()."""

    def __init__(self, stage: _ast.Stage) -> None:
        self._stage = stage

    def to_mqlv2(self) -> str:
        return Serializer().serialize(self._stage)
