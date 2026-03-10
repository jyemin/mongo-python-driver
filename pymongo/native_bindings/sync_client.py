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

"""Native synchronous MongoDB client implementation using FFI bindings.

This module provides a MongoClient-like interface that uses the native
driver library for all operations. Unsupported operations raise
UnsupportedOperationError.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import bson
from bson import ObjectId
from bson.codec_options import CodecOptions, DEFAULT_CODEC_OPTIONS
from bson.raw_bson import RawBSONDocument

from pymongo.results import InsertOneResult, InsertManyResult
from pymongo.native_bindings._client import NativeClient
from pymongo.native_bindings._callbacks import SyncCallbackBridge
from pymongo.native_bindings._ffi import ffi


class UnsupportedOperationError(Exception):
    """Raised when an operation is not supported by the native driver FFI."""
    pass


# =============================================================================
# FFI Callbacks - module level to avoid GC issues
# =============================================================================

@ffi.callback('void(void*, const InsertOneResult*, const Error*)')
def _insert_one_cb(userdata, result_ptr, error_ptr):
    bridge = ffi.from_handle(userdata)
    bridge.on_complete(result_ptr, error_ptr)


@ffi.callback('void(void*, const InsertManyResult*, const Error*)')
def _insert_many_cb(userdata, result_ptr, error_ptr):
    bridge = ffi.from_handle(userdata)
    bridge.on_complete(result_ptr, error_ptr)


@ffi.callback('void(void*, const CursorResult*, const Error*)')
def _find_cb(userdata, result_ptr, error_ptr):
    bridge = ffi.from_handle(userdata)
    bridge.on_complete(result_ptr, error_ptr)


@ffi.callback('void(void*, const OwnedBson*, const Error*)')
def _command_cb(userdata, result_ptr, error_ptr):
    bridge = ffi.from_handle(userdata)
    bridge.on_complete(result_ptr, error_ptr)


@ffi.callback('void(void*, const Error*)')
def _void_cb(userdata, error_ptr):
    bridge = ffi.from_handle(userdata)
    bridge.on_complete(None, error_ptr)


# =============================================================================
# Result Converters
# =============================================================================

def _convert_insert_one(result_ptr, codec_options: CodecOptions):
    """Convert FFI InsertOneResult to inserted_id."""
    if result_ptr == ffi.NULL:
        return None
    bv = result_ptr.inserted_id
    if bv.bson_type == 0x07:  # ObjectId
        return ObjectId(ffi.buffer(bv.data, bv.len)[:])
    # Wrap other types in a doc to decode
    data = ffi.buffer(bv.data, bv.len)[:]
    elem = bytes([bv.bson_type]) + b"v\x00" + data
    doc = (4 + len(elem) + 1).to_bytes(4, "little") + elem + b"\x00"
    return bson.decode(doc, codec_options=codec_options).get("v")


def _convert_insert_many(result_ptr, codec_options: CodecOptions) -> Dict[int, Any]:
    """Convert FFI InsertManyResult to dict of inserted IDs."""
    if result_ptr == ffi.NULL:
        return {}
    ids = {}
    for i in range(result_ptr.inserted_ids_len):
        item = result_ptr.inserted_ids[i]
        bv = item.id
        if bv.bson_type == 0x07:
            ids[item.index] = ObjectId(ffi.buffer(bv.data, bv.len)[:])
        else:
            data = ffi.buffer(bv.data, bv.len)[:]
            elem = bytes([bv.bson_type]) + b"v\x00" + data
            doc = (4 + len(elem) + 1).to_bytes(4, "little") + elem + b"\x00"
            ids[item.index] = bson.decode(doc, codec_options=codec_options).get("v")
    return ids


def _convert_find(result_ptr, codec_options: CodecOptions):
    """Convert FFI CursorResult to (cursor_handle, exhausted, docs)."""
    if result_ptr == ffi.NULL:
        return None, True, []
    cursor = result_ptr.cursor
    exhausted = result_ptr.exhausted
    batch = result_ptr.first_batch
    docs = []
    if batch.data != ffi.NULL:
        for i in range(batch.len):
            ptr = batch.data[i]
            length = int.from_bytes(ffi.buffer(ptr, 4)[:], "little")
            docs.append(bson.decode(ffi.buffer(ptr, length)[:], codec_options=codec_options))
    return cursor, exhausted, docs


def _convert_command(result_ptr, codec_options: CodecOptions) -> Dict[str, Any]:
    """Convert FFI OwnedBson to dict."""
    if result_ptr == ffi.NULL:
        return {}
    return bson.decode(ffi.buffer(result_ptr.data, result_ptr.len)[:], codec_options=codec_options)


# =============================================================================
# NativeSyncMongoClient
# =============================================================================

class NativeSyncMongoClient:
    """Native synchronous MongoDB client using FFI bindings.

    This client delegates all operations to the native driver library.
    Operations not supported by the FFI raise UnsupportedOperationError.

    Example::

        with NativeSyncMongoClient("localhost", 27017) as client:
            db = client["test"]
            coll = db["my_collection"]
            result = coll.insert_one({"x": 1})
            print(result.inserted_id)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 27017,
        **kwargs: Any,
    ):
        """Create a new native sync MongoDB client.

        Args:
            host: MongoDB host or connection string.
            port: MongoDB port (ignored if host is a connection string).
            **kwargs: Connection options (appName, directConnection, tls, etc.)
        """
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
        """Close the client and release resources."""
        self._native.close()

    def __enter__(self) -> "NativeSyncMongoClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __getitem__(self, name: str) -> "NativeSyncDatabase":
        """Get a database by name. ``client["db"]`` is equivalent to ``client.get_database("db")``."""
        return self.get_database(name)

    def get_database(self, name: str, codec_options: Optional[CodecOptions] = None) -> "NativeSyncDatabase":
        """Get a database by name.

        Args:
            name: Database name.
            codec_options: Optional codec options for encoding/decoding documents.
        """
        return NativeSyncDatabase(self, name, codec_options or self._codec_options)


# =============================================================================
# NativeSyncDatabase
# =============================================================================

class NativeSyncDatabase:
    """Native synchronous database handle."""

    def __init__(self, client: NativeSyncMongoClient, name: str, codec_options: CodecOptions):
        self._client = client
        self._name = name
        self._codec_options = codec_options

    @property
    def name(self) -> str:
        """Database name."""
        return self._name

    @property
    def client(self) -> NativeSyncMongoClient:
        """The client that owns this database."""
        return self._client

    def __getitem__(self, name: str) -> "NativeSyncCollection":
        """Get a collection by name."""
        return self.get_collection(name)

    def get_collection(self, name: str, codec_options: Optional[CodecOptions] = None) -> "NativeSyncCollection":
        """Get a collection by name."""
        return NativeSyncCollection(self, name, codec_options or self._codec_options)

    def command(self, command: Union[str, Mapping[str, Any]], **kwargs: Any) -> Dict[str, Any]:
        """Run a database command.

        Args:
            command: Command name (string) or command document.
            **kwargs: Additional command arguments.

        Returns:
            Command result document.
        """
        if isinstance(command, str):
            cmd_doc = {command: 1, **kwargs}
        else:
            cmd_doc = dict(command)
            cmd_doc.update(kwargs)

        cmd_bytes = bson.encode(cmd_doc, codec_options=self._codec_options)

        bridge = SyncCallbackBridge(lambda r: _convert_command(r, self._codec_options))
        self._client._native.run_command(self._name, cmd_bytes, _command_cb, bridge.handle)
        return bridge.wait()

    def drop(self) -> None:
        """Drop this database."""
        bridge = SyncCallbackBridge(lambda r: None)
        self._client._native.drop_database(self._name, _void_cb, bridge.handle)
        bridge.wait()


# =============================================================================
# NativeSyncCollection
# =============================================================================

class NativeSyncCollection:
    """Native synchronous collection handle."""

    def __init__(self, database: NativeSyncDatabase, name: str, codec_options: CodecOptions):
        self._database = database
        self._name = name
        self._codec_options = codec_options

    @property
    def name(self) -> str:
        """Collection name."""
        return self._name

    @property
    def database(self) -> NativeSyncDatabase:
        """The database that owns this collection."""
        return self._database

    @property
    def full_name(self) -> str:
        """Full namespace (database.collection)."""
        return f"{self._database.name}.{self._name}"

    # -------------------------------------------------------------------------
    # Insert Operations
    # -------------------------------------------------------------------------

    def insert_one(
        self,
        document: Mapping[str, Any],
        bypass_document_validation: bool = False,
        **kwargs: Any,
    ) -> InsertOneResult:
        """Insert a single document.

        Args:
            document: The document to insert.
            bypass_document_validation: If True, skip document validation.

        Returns:
            InsertOneResult with inserted_id.
        """
        # Add _id if not present
        doc = dict(document)
        if "_id" not in doc:
            doc["_id"] = ObjectId()

        doc_bytes = bson.encode(doc, codec_options=self._codec_options)

        bridge = SyncCallbackBridge(lambda r: _convert_insert_one(r, self._codec_options))
        self._database._client._native.insert_one(
            self._database.name,
            self._name,
            doc_bytes,
            _insert_one_cb,
            bridge.handle,
            bypass_document_validation=bypass_document_validation,
        )
        inserted_id = bridge.wait()
        return InsertOneResult(inserted_id or doc["_id"], acknowledged=True)

    def insert_many(
        self,
        documents: Sequence[Mapping[str, Any]],
        ordered: bool = True,
        bypass_document_validation: bool = False,
        **kwargs: Any,
    ) -> InsertManyResult:
        """Insert multiple documents.

        Args:
            documents: Sequence of documents to insert.
            ordered: If True, stop on first error.
            bypass_document_validation: If True, skip document validation.

        Returns:
            InsertManyResult with inserted_ids.
        """
        # Add _ids if not present and encode
        docs_with_ids = []
        doc_bytes_list = []
        for doc in documents:
            d = dict(doc)
            if "_id" not in d:
                d["_id"] = ObjectId()
            docs_with_ids.append(d)
            doc_bytes_list.append(bson.encode(d, codec_options=self._codec_options))

        bridge = SyncCallbackBridge(lambda r: _convert_insert_many(r, self._codec_options))
        self._database._client._native.insert_many(
            self._database.name,
            self._name,
            doc_bytes_list,
            _insert_many_cb,
            bridge.handle,
            bridge._refs,  # keepalive
            ordered=ordered,
            bypass_document_validation=bypass_document_validation,
        )
        ids_dict = bridge.wait()
        # Return _ids in order
        inserted_ids = [ids_dict.get(i, docs_with_ids[i]["_id"]) for i in range(len(docs_with_ids))]
        return InsertManyResult(inserted_ids, acknowledged=True)

    # -------------------------------------------------------------------------
    # Find Operations
    # -------------------------------------------------------------------------

    def find_one(
        self,
        filter: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """Find a single document.

        Args:
            filter: Query filter.
            **kwargs: Additional options (projection, sort, etc.)

        Returns:
            The document, or None if not found.
        """
        for doc in self.find(filter, limit=1, **kwargs):
            return doc
        return None

    def find(
        self,
        filter: Optional[Mapping[str, Any]] = None,
        projection: Optional[Mapping[str, Any]] = None,
        skip: int = 0,
        limit: int = 0,
        sort: Optional[List] = None,
        **kwargs: Any,
    ) -> "NativeSyncCursor":
        """Find documents matching a filter.

        Args:
            filter: Query filter.
            projection: Fields to include/exclude.
            skip: Number of documents to skip.
            limit: Maximum documents to return.
            sort: Sort specification.

        Returns:
            Cursor to iterate over results.
        """
        filter_doc = filter or {}
        filter_bytes = bson.encode(filter_doc, codec_options=self._codec_options)

        proj_bytes = None
        if projection:
            proj_bytes = bson.encode(projection, codec_options=self._codec_options)

        sort_bytes = None
        if sort:
            # Convert list of tuples to dict
            sort_doc = dict(sort) if isinstance(sort, list) else sort
            sort_bytes = bson.encode(sort_doc, codec_options=self._codec_options)

        bridge = SyncCallbackBridge(lambda r: _convert_find(r, self._codec_options))
        self._database._client._native.find(
            self._database.name,
            self._name,
            filter_bytes,
            _find_cb,
            bridge.handle,
            projection=proj_bytes,
            sort=sort_bytes,
            skip=skip,
            limit=limit,
        )
        cursor_handle, exhausted, first_batch = bridge.wait()
        return NativeSyncCursor(
            self._database._client._native,
            cursor_handle,
            exhausted,
            first_batch,
            self._codec_options,
        )

    # -------------------------------------------------------------------------
    # Drop
    # -------------------------------------------------------------------------

    def drop(self) -> None:
        """Drop this collection."""
        bridge = SyncCallbackBridge(lambda r: None)
        self._database._client._native.drop_collection(
            self._database.name, self._name, _void_cb, bridge.handle
        )
        bridge.wait()

    # -------------------------------------------------------------------------
    # Unsupported Operations
    # -------------------------------------------------------------------------

    def update_one(self, *args, **kwargs):
        raise UnsupportedOperationError("update_one not yet supported in native FFI")

    def update_many(self, *args, **kwargs):
        raise UnsupportedOperationError("update_many not yet supported in native FFI")

    def delete_one(self, *args, **kwargs):
        raise UnsupportedOperationError("delete_one not yet supported in native FFI")

    def delete_many(self, *args, **kwargs):
        raise UnsupportedOperationError("delete_many not yet supported in native FFI")

    def aggregate(self, *args, **kwargs):
        raise UnsupportedOperationError("aggregate not yet supported in native FFI")

    def count_documents(self, *args, **kwargs):
        raise UnsupportedOperationError("count_documents not yet supported in native FFI")

    def distinct(self, *args, **kwargs):
        raise UnsupportedOperationError("distinct not yet supported in native FFI")


# =============================================================================
# NativeSyncCursor
# =============================================================================

@ffi.callback('void(void*, bool, BsonArray, const Error*)')
def _get_more_cb(userdata, exhausted, data, error_ptr):
    bridge = ffi.from_handle(userdata)
    bridge.on_complete((exhausted, data), error_ptr)


class NativeSyncCursor:
    """Native synchronous cursor for iterating find results."""

    def __init__(
        self,
        native_client: NativeClient,
        cursor_handle,
        exhausted: bool,
        first_batch: List[Dict[str, Any]],
        codec_options: CodecOptions,
    ):
        self._native = native_client
        self._cursor = cursor_handle
        self._exhausted = exhausted
        self._buffer = list(first_batch)
        self._codec_options = codec_options
        self._closed = False

    def __iter__(self) -> "NativeSyncCursor":
        return self

    def __next__(self) -> Dict[str, Any]:
        if self._buffer:
            return self._buffer.pop(0)

        if self._exhausted or self._closed:
            raise StopIteration

        self._fetch_batch()

        if self._buffer:
            return self._buffer.pop(0)

        raise StopIteration

    def _fetch_batch(self) -> None:
        """Fetch the next batch from the server."""
        if self._exhausted or self._closed or self._cursor == ffi.NULL:
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

        bridge = SyncCallbackBridge(convert)
        self._native.cursor_get_more(self._cursor, _get_more_cb, bridge.handle)
        self._exhausted, new_docs = bridge.wait()
        self._buffer.extend(new_docs)

    def close(self) -> None:
        """Close the cursor."""
        if not self._closed and self._cursor != ffi.NULL:
            self._native.cursor_close(self._cursor)
            self._closed = True

    def __enter__(self) -> "NativeSyncCursor":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def to_list(self) -> List[Dict[str, Any]]:
        """Return all remaining documents as a list."""
        return list(self)

