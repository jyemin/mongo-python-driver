# Copyright 2024-present MongoDB, Inc.
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

"""Native asynchronous MongoDB client implementation using FFI bindings.

This module provides an AsyncMongoClient-like interface that uses the native
driver library for all operations. Unsupported operations raise
UnsupportedOperationError.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Mapping, Optional, Sequence, Union

import bson
from bson import ObjectId
from bson.codec_options import CodecOptions, DEFAULT_CODEC_OPTIONS

from pymongo.results import InsertOneResult, InsertManyResult
from pymongo.native_bindings._client import NativeClient
from pymongo.native_bindings._callbacks import AsyncCallbackBridge
from pymongo.native_bindings._ffi import ffi
from pymongo.native_bindings.sync_client import (
    UnsupportedOperationError,
    _insert_one_cb,
    _insert_many_cb,
    _find_cb,
    _command_cb,
    _void_cb,
    _get_more_cb,
    _convert_insert_one,
    _convert_insert_many,
    _convert_find,
    _convert_command,
)


class NativeAsyncMongoClient:
    """Native asynchronous MongoDB client using FFI bindings."""
    
    def __init__(self, host: str = "localhost", port: int = 27017, **kwargs: Any):
        hosts = host if "://" in host else f"{host}:{port}"
        self._native = NativeClient(
            hosts,
            app_name=kwargs.get("appName") or kwargs.get("appname"),
            direct_connection=kwargs.get("directConnection", False),
            server_selection_timeout_ms=kwargs.get("serverSelectionTimeoutMS", 30000),
            connect_timeout_ms=kwargs.get("connectTimeoutMS", 20000),
            username=kwargs.get("username"),
            password=kwargs.get("password"),
            auth_source=kwargs.get("authSource"),
            auth_mechanism=kwargs.get("authMechanism"),
            tls=kwargs.get("tls", False),
            tls_ca_file=kwargs.get("tlsCAFile"),
            tls_certificate_key_file=kwargs.get("tlsCertificateKeyFile"),
        )
        self._codec_options = kwargs.get("codec_options", DEFAULT_CODEC_OPTIONS)
    
    def close(self) -> None:
        self._native.close()
    
    async def __aenter__(self) -> "NativeAsyncMongoClient":
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    def __getitem__(self, name: str) -> "NativeAsyncDatabase":
        return self.get_database(name)
    
    def get_database(self, name: str, codec_options: Optional[CodecOptions] = None) -> "NativeAsyncDatabase":
        return NativeAsyncDatabase(self, name, codec_options or self._codec_options)


class NativeAsyncDatabase:
    """Native asynchronous database handle."""
    
    def __init__(self, client: NativeAsyncMongoClient, name: str, codec_options: CodecOptions):
        self._client = client
        self._name = name
        self._codec_options = codec_options
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def client(self) -> NativeAsyncMongoClient:
        return self._client
    
    def __getitem__(self, name: str) -> "NativeAsyncCollection":
        return self.get_collection(name)
    
    def get_collection(self, name: str, codec_options: Optional[CodecOptions] = None) -> "NativeAsyncCollection":
        return NativeAsyncCollection(self, name, codec_options or self._codec_options)
    
    async def command(self, command: Union[str, Mapping[str, Any]], **kwargs: Any) -> Dict[str, Any]:
        """Run a database command."""
        cmd_doc = {command: 1, **kwargs} if isinstance(command, str) else {**command, **kwargs}
        cmd_bytes = bson.encode(cmd_doc, codec_options=self._codec_options)
        bridge = AsyncCallbackBridge(lambda r: _convert_command(r, self._codec_options))
        self._client._native.run_command(self._name, cmd_bytes, _command_cb, bridge.handle)
        return await bridge.future
    
    async def drop(self) -> None:
        """Drop this database."""
        bridge = AsyncCallbackBridge(lambda r: None)
        self._client._native.drop_database(self._name, _void_cb, bridge.handle)
        await bridge.future


class NativeAsyncCollection:
    """Native asynchronous collection handle."""
    
    def __init__(self, database: NativeAsyncDatabase, name: str, codec_options: CodecOptions):
        self._database = database
        self._name = name
        self._codec_options = codec_options
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def database(self) -> NativeAsyncDatabase:
        return self._database
    
    @property
    def full_name(self) -> str:
        return f"{self._database.name}.{self._name}"
    
    async def insert_one(self, document: Mapping[str, Any], bypass_document_validation: bool = False, **kwargs) -> InsertOneResult:
        """Insert a single document."""
        doc = dict(document)
        if "_id" not in doc:
            doc["_id"] = ObjectId()
        doc_bytes = bson.encode(doc, codec_options=self._codec_options)
        bridge = AsyncCallbackBridge(lambda r: _convert_insert_one(r, self._codec_options))
        self._database._client._native.insert_one(
            self._database.name, self._name, doc_bytes, _insert_one_cb, bridge.handle,
            bypass_document_validation=bypass_document_validation,
        )
        inserted_id = await bridge.future
        return InsertOneResult(inserted_id or doc["_id"], acknowledged=True)

    async def insert_many(self, documents: Sequence[Mapping[str, Any]], ordered: bool = True,
                          bypass_document_validation: bool = False, **kwargs) -> InsertManyResult:
        """Insert multiple documents."""
        docs_with_ids = []
        doc_bytes_list = []
        for doc in documents:
            d = dict(doc)
            if "_id" not in d:
                d["_id"] = ObjectId()
            docs_with_ids.append(d)
            doc_bytes_list.append(bson.encode(d, codec_options=self._codec_options))

        bridge = AsyncCallbackBridge(lambda r: _convert_insert_many(r, self._codec_options))
        self._database._client._native.insert_many(
            self._database.name, self._name, doc_bytes_list, _insert_many_cb, bridge.handle, bridge._refs,
            ordered=ordered, bypass_document_validation=bypass_document_validation,
        )
        ids_dict = await bridge.future
        inserted_ids = [ids_dict.get(i, docs_with_ids[i]["_id"]) for i in range(len(docs_with_ids))]
        return InsertManyResult(inserted_ids, acknowledged=True)

    async def find_one(self, filter: Optional[Mapping[str, Any]] = None, **kwargs) -> Optional[Dict[str, Any]]:
        """Find a single document."""
        async for doc in self.find(filter, limit=1, **kwargs):
            return doc
        return None

    def find(self, filter: Optional[Mapping[str, Any]] = None, projection: Optional[Mapping[str, Any]] = None,
             skip: int = 0, limit: int = 0, sort: Optional[List] = None, **kwargs) -> "NativeAsyncCursor":
        """Find documents matching a filter."""
        filter_bytes = bson.encode(filter or {}, codec_options=self._codec_options)
        proj_bytes = bson.encode(projection, codec_options=self._codec_options) if projection else None
        sort_bytes = bson.encode(dict(sort) if isinstance(sort, list) else sort, codec_options=self._codec_options) if sort else None

        return NativeAsyncCursor(
            self._database._client._native, self._database.name, self._name,
            filter_bytes, proj_bytes, sort_bytes, skip, limit, self._codec_options,
        )

    async def drop(self) -> None:
        """Drop this collection."""
        bridge = AsyncCallbackBridge(lambda r: None)
        self._database._client._native.drop_collection(self._database.name, self._name, _void_cb, bridge.handle)
        await bridge.future

    # Unsupported operations
    async def update_one(self, *args, **kwargs):
        raise UnsupportedOperationError("update_one not yet supported in native FFI")

    async def update_many(self, *args, **kwargs):
        raise UnsupportedOperationError("update_many not yet supported in native FFI")

    async def delete_one(self, *args, **kwargs):
        raise UnsupportedOperationError("delete_one not yet supported in native FFI")

    async def delete_many(self, *args, **kwargs):
        raise UnsupportedOperationError("delete_many not yet supported in native FFI")

    async def aggregate(self, *args, **kwargs):
        raise UnsupportedOperationError("aggregate not yet supported in native FFI")


class NativeAsyncCursor:
    """Native asynchronous cursor for iterating find results."""

    def __init__(self, native_client: NativeClient, db_name: str, coll_name: str,
                 filter_bytes: bytes, proj_bytes: Optional[bytes], sort_bytes: Optional[bytes],
                 skip: int, limit: int, codec_options: CodecOptions):
        self._native = native_client
        self._db_name = db_name
        self._coll_name = coll_name
        self._filter_bytes = filter_bytes
        self._proj_bytes = proj_bytes
        self._sort_bytes = sort_bytes
        self._skip = skip
        self._limit = limit
        self._codec_options = codec_options
        self._cursor = None
        self._exhausted = False
        self._buffer: List[Dict[str, Any]] = []
        self._started = False
        self._closed = False

    async def _start(self) -> None:
        """Execute the find query."""
        if self._started:
            return
        self._started = True

        bridge = AsyncCallbackBridge(lambda r: _convert_find(r, self._codec_options))
        self._native.find(
            self._db_name, self._coll_name, self._filter_bytes, _find_cb, bridge.handle,
            projection=self._proj_bytes, sort=self._sort_bytes, skip=self._skip, limit=self._limit,
        )
        self._cursor, self._exhausted, first_batch = await bridge.future
        self._buffer.extend(first_batch)

    def __aiter__(self) -> "NativeAsyncCursor":
        return self

    async def __anext__(self) -> Dict[str, Any]:
        if not self._started:
            await self._start()

        if self._buffer:
            return self._buffer.pop(0)

        if self._exhausted or self._closed:
            raise StopAsyncIteration

        await self._fetch_batch()

        if self._buffer:
            return self._buffer.pop(0)
        raise StopAsyncIteration

    async def _fetch_batch(self) -> None:
        """Fetch the next batch from the server."""
        if self._exhausted or self._closed or self._cursor is None or self._cursor == ffi.NULL:
            return

        def convert(result):
            exhausted, batch = result
            docs = []
            if batch.data != ffi.NULL:
                for i in range(batch.len):
                    ptr = batch.data[i]
                    length = int.from_bytes(ffi.buffer(ptr, 4)[:], "little")
                    docs.append(bson.decode(ffi.buffer(ptr, length)[:], codec_options=self._codec_options))
            return exhausted, docs

        bridge = AsyncCallbackBridge(convert)
        self._native.cursor_get_more(self._cursor, _get_more_cb, bridge.handle)
        self._exhausted, new_docs = await bridge.future
        self._buffer.extend(new_docs)

    async def close(self) -> None:
        """Close the cursor."""
        if not self._closed and self._cursor is not None and self._cursor != ffi.NULL:
            self._native.cursor_close(self._cursor)
            self._closed = True

    async def to_list(self) -> List[Dict[str, Any]]:
        """Return all remaining documents as a list."""
        return [doc async for doc in self]

