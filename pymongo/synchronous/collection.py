# Copyright 2009-present MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Minimal Collection that delegates to native FFI."""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Iterator, Mapping, Optional, Sequence

from bson.codec_options import DEFAULT_CODEC_OPTIONS, CodecOptions
from pymongo.results import InsertOneResult, InsertManyResult


class ReturnDocument(Enum):
    """Enum for return_document parameter in find_one_and_* methods."""
    BEFORE = False
    AFTER = True

if TYPE_CHECKING:
    from pymongo.synchronous.database import Database


class Collection:
    """Collection for MongoDB using native FFI.
    
    Only operations supported by native FFI are available.
    Unsupported operations raise NotImplementedError.
    """

    def __init__(
        self,
        database: "Database",
        name: str,
        codec_options: Optional[CodecOptions] = None,
    ):
        self._database = database
        self._name = name
        self._codec_options = codec_options or database.codec_options

    @property
    def name(self) -> str:
        return self._name

    @property
    def database(self) -> "Database":
        return self._database

    @property
    def full_name(self) -> str:
        return f"{self._database.name}.{self._name}"

    @property
    def codec_options(self) -> CodecOptions:
        return self._codec_options

    def _native_coll(self):
        """Get the native collection for delegation."""
        return self._database._client._native[self._database.name][self._name]

    def insert_one(
        self,
        document: Mapping[str, Any],
        **kwargs: Any,
    ) -> InsertOneResult:
        """Insert a single document."""
        return self._native_coll().insert_one(document, **kwargs)

    def insert_many(
        self,
        documents: Sequence[Mapping[str, Any]],
        ordered: bool = True,
        **kwargs: Any,
    ) -> InsertManyResult:
        """Insert multiple documents."""
        return self._native_coll().insert_many(documents, ordered=ordered, **kwargs)

    def find_one(
        self,
        filter: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """Find a single document."""
        return self._native_coll().find_one(filter, **kwargs)

    def find(
        self,
        filter: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> Iterator[Dict[str, Any]]:
        """Find documents matching filter."""
        return self._native_coll().find(filter, **kwargs)

    def drop(self, **kwargs: Any) -> None:
        """Drop the collection."""
        return self._native_coll().drop(**kwargs)

    # Unsupported operations
    def update_one(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("update_one not yet supported")

    def update_many(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("update_many not yet supported")

    def delete_one(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("delete_one not yet supported")

    def delete_many(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("delete_many not yet supported")

    def replace_one(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("replace_one not yet supported")

    def aggregate(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("aggregate not yet supported")

    def count_documents(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("count_documents not yet supported")

    def estimated_document_count(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("estimated_document_count not yet supported")

    def distinct(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("distinct not yet supported")

    def create_index(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("create_index not yet supported")

    def create_indexes(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("create_indexes not yet supported")

    def drop_index(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("drop_index not yet supported")

    def drop_indexes(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("drop_indexes not yet supported")

    def list_indexes(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("list_indexes not yet supported")

    def find_one_and_update(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("find_one_and_update not yet supported")

    def find_one_and_delete(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("find_one_and_delete not yet supported")

    def find_one_and_replace(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("find_one_and_replace not yet supported")

    def bulk_write(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("bulk_write not yet supported")

    def watch(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("watch not yet supported")

