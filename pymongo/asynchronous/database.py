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

"""Minimal AsyncDatabase that delegates to native FFI."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional, Union

from bson.codec_options import DEFAULT_CODEC_OPTIONS, CodecOptions
from pymongo.asynchronous.collection import AsyncCollection

if TYPE_CHECKING:
    from pymongo.asynchronous.mongo_client import AsyncMongoClient


class AsyncDatabase:
    """Async database for MongoDB using native FFI.
    
    Only operations supported by native FFI are available.
    Unsupported operations raise NotImplementedError.
    """

    def __init__(
        self,
        client: "AsyncMongoClient",
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
    def client(self) -> "AsyncMongoClient":
        return self._client

    @property
    def codec_options(self) -> CodecOptions:
        return self._codec_options

    def __getitem__(self, name: str) -> AsyncCollection:
        """Get a collection by name."""
        return AsyncCollection(self, name)

    def __getattr__(self, name: str) -> AsyncCollection:
        """Get a collection by attribute access."""
        if name.startswith("_"):
            raise AttributeError(f"AsyncDatabase has no attribute {name!r}")
        return self[name]

    def get_collection(
        self,
        name: str,
        codec_options: Optional[CodecOptions] = None,
    ) -> AsyncCollection:
        """Get a collection by name."""
        return AsyncCollection(self, name, codec_options=codec_options or self._codec_options)

    async def command(
        self,
        command: Union[str, Mapping[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute a database command via native FFI."""
        return await self._client._native[self._name].command(command, **kwargs)

    async def drop(self, **kwargs: Any) -> None:
        """Drop the database."""
        await self.command("dropDatabase")

    # Unsupported operations
    async def list_collections(self, **kwargs: Any) -> Any:
        raise NotImplementedError("list_collections not yet supported")

    async def list_collection_names(self, **kwargs: Any) -> Any:
        raise NotImplementedError("list_collection_names not yet supported")

    async def create_collection(self, name: str, **kwargs: Any) -> AsyncCollection:
        raise NotImplementedError("create_collection not yet supported")

    async def drop_collection(self, name: str, **kwargs: Any) -> None:
        raise NotImplementedError("drop_collection not yet supported")

    async def validate_collection(self, name: str, **kwargs: Any) -> Any:
        raise NotImplementedError("validate_collection not yet supported")

    async def aggregate(self, pipeline: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("aggregate not yet supported")

    async def watch(self, **kwargs: Any) -> Any:
        raise NotImplementedError("watch not yet supported")

    async def dereference(self, **kwargs: Any) -> Any:
        raise NotImplementedError("dereference not yet supported")

