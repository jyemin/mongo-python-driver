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

"""Minimal Database that delegates to native FFI."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional, Union

from bson.codec_options import DEFAULT_CODEC_OPTIONS, CodecOptions
from pymongo.synchronous.collection import Collection

if TYPE_CHECKING:
    from pymongo.synchronous.mongo_client import MongoClient


class Database:
    """Database for MongoDB using native FFI.
    
    Only operations supported by native FFI are available.
    Unsupported operations raise NotImplementedError.
    """

    def __init__(
        self,
        client: "MongoClient",
        name: str,
        codec_options: Optional[CodecOptions] = None,
    ):
        self._client = client
        self._name = name
        self._codec_options = codec_options or client.codec_options

    @property
    def name(self) -> str:
        return self._name

    @property
    def client(self) -> "MongoClient":
        return self._client

    @property
    def codec_options(self) -> CodecOptions:
        return self._codec_options

    def __getitem__(self, name: str) -> Collection:
        """Get a collection by name."""
        return Collection(self, name)

    def __getattr__(self, name: str) -> Collection:
        """Get a collection by attribute access."""
        if name.startswith("_"):
            raise AttributeError(f"Database has no attribute {name!r}")
        return self[name]

    def get_collection(
        self,
        name: str,
        codec_options: Optional[CodecOptions] = None,
    ) -> Collection:
        """Get a collection by name."""
        return Collection(self, name, codec_options=codec_options or self._codec_options)

    def command(
        self,
        command: Union[str, Mapping[str, Any]],
        value: Any = 1,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute a database command via native FFI."""
        # Handle command("name", value, **kwargs) pattern
        if isinstance(command, str):
            cmd_doc = {command: value, **kwargs}
        else:
            cmd_doc = dict(command)
            cmd_doc.update(kwargs)
        return self._client._native[self._name].command(cmd_doc)

    def drop(self, **kwargs: Any) -> None:
        """Drop the database."""
        self._client._native[self._name].drop()

    # Unsupported operations
    def list_collections(self, **kwargs: Any) -> Any:
        raise NotImplementedError("list_collections not yet supported")

    def list_collection_names(self, **kwargs: Any) -> Any:
        raise NotImplementedError("list_collection_names not yet supported")

    def create_collection(self, name: str, **kwargs: Any) -> Collection:
        """Create a collection."""
        self.command("create", name, **kwargs)
        return self.get_collection(name)

    def drop_collection(self, name: str, **kwargs: Any) -> None:
        """Drop a collection."""
        self.get_collection(name).drop()

    def validate_collection(self, name: str, **kwargs: Any) -> Any:
        raise NotImplementedError("validate_collection not yet supported")

    def aggregate(self, pipeline: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("aggregate not yet supported")

    def watch(self, **kwargs: Any) -> Any:
        raise NotImplementedError("watch not yet supported")

    def dereference(self, **kwargs: Any) -> Any:
        raise NotImplementedError("dereference not yet supported")

