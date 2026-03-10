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

"""Native client wrapper for libmongocore.

This is a callback-based, sync/async agnostic client. The caller provides
callbacks that are invoked when operations complete. Use AsyncCallbackBridge
or SyncCallbackBridge to integrate with async/await or blocking patterns.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from pymongo.native_bindings._ffi import ffi, get_lib
from pymongo.native_bindings._errors import convert_error
from pymongo.native_bindings._marshalling import BsonMarshaller

if TYPE_CHECKING:
    from bson.codec_options import CodecOptions


class NativeClient:
    """Low-level native MongoDB client wrapper.
    
    This client is callback-based and does not use async/await directly.
    Operations accept a callback that is invoked when the operation completes.
    """
    
    def __init__(
        self,
        hosts: str,
        *,
        app_name: Optional[str] = None,
        direct_connection: bool = False,
        load_balanced: bool = False,
        max_pool_size: int = -1,
        min_pool_size: int = -1,
        connect_timeout_ms: int = -1,
        server_selection_timeout_ms: int = -1,
        replica_set: Optional[str] = None,
        # Auth settings
        username: Optional[str] = None,
        password: Optional[str] = None,
        auth_source: Optional[str] = None,
        auth_mechanism: Optional[str] = None,
        # TLS settings
        tls: bool = False,
        tls_allow_invalid_certificates: bool = False,
        tls_allow_invalid_hostnames: bool = False,
        tls_ca_file: Optional[str] = None,
        tls_certificate_key_file: Optional[str] = None,
    ):
        """Create a new native client.
        
        Args:
            hosts: Comma-separated host:port pairs (e.g., "localhost:27017").
            app_name: Application name for server logs.
            direct_connection: Connect directly to a single server.
            ... (other standard MongoDB connection options)
        """
        self._lib = get_lib()
        self._marshaller = BsonMarshaller()
        
        # Helper to create C strings (cffi needs ffi.new for strings)
        def cstr(s: Optional[str]):
            if s is None:
                return ffi.NULL
            return ffi.new("char[]", s.encode("utf-8"))

        # Keep references to C strings alive for duration of client creation
        self._cstrings = []
        def keep_cstr(s: Optional[str]):
            cs = cstr(s)
            if cs != ffi.NULL:
                self._cstrings.append(cs)
            return cs

        # Build connection settings
        conn = ffi.new("ConnectionSettings *")
        conn.hosts = keep_cstr(hosts)
        conn.app_name = keep_cstr(app_name)
        conn.compressors = ffi.NULL
        conn.direct_connection = direct_connection
        conn.load_balanced = load_balanced
        conn.max_pool_size = max_pool_size
        conn.min_pool_size = min_pool_size
        conn.max_idle_time_ms = -1
        conn.connect_timeout_ms = connect_timeout_ms
        conn.socket_timeout_ms = -1
        conn.server_selection_timeout_ms = server_selection_timeout_ms
        conn.local_threshold_ms = -1
        conn.heartbeat_frequency_ms = -1
        conn.replica_set = keep_cstr(replica_set)
        conn.read_preference_mode = 0  # Primary
        conn.srv_service_name = ffi.NULL
        conn.srv_max_hosts = -1

        # Build auth settings
        auth = ffi.NULL
        if username:
            auth = ffi.new("AuthSettings *")
            auth.mechanism = keep_cstr(auth_mechanism)
            auth.username = keep_cstr(username)
            auth.password = keep_cstr(password)
            auth.source = keep_cstr(auth_source)

        # Build TLS settings
        tls_settings = ffi.NULL
        if tls or tls_ca_file or tls_certificate_key_file:
            tls_settings = ffi.new("TlsSettings *")
            tls_settings.enabled = tls or bool(tls_ca_file) or bool(tls_certificate_key_file)
            tls_settings.allow_invalid_certificates = tls_allow_invalid_certificates
            tls_settings.allow_invalid_hostnames = tls_allow_invalid_hostnames
            tls_settings.ca_file = keep_cstr(tls_ca_file)
            tls_settings.cert_file = ffi.NULL
            tls_settings.cert_key_file = keep_cstr(tls_certificate_key_file)
        
        # Create the client
        error_out = ffi.new("Error **")
        self._client = self._lib.mongo_client_new(conn, auth, tls_settings, error_out)
        
        if self._client == ffi.NULL:
            if error_out[0] != ffi.NULL:
                exc = convert_error(error_out[0])
                self._lib.error_free(error_out[0])
                raise exc
            raise RuntimeError("Failed to create native client")
        
        # Store settings for reference
        self._hosts = hosts
        self._closed = False
    
    def close(self) -> None:
        """Close the client and release resources."""
        if not self._closed and self._client != ffi.NULL:
            self._lib.mongo_client_destroy(self._client)
            self._closed = True
            self._client = ffi.NULL
    
    def __del__(self):
        self.close()
    
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # -------------------------------------------------------------------------
    # CRUD Operations (callback-based)
    # -------------------------------------------------------------------------

    def insert_one(
        self,
        db_name: str,
        coll_name: str,
        document: bytes,
        callback: Callable,
        userdata: Any,
        *,
        bypass_document_validation: bool = False,
        session=None,
    ) -> None:
        """Insert a single document (async via callback).

        Args:
            db_name: Database name.
            coll_name: Collection name.
            document: BSON-encoded document bytes.
            callback: FFI callback function.
            userdata: FFI handle to pass to callback.
            bypass_document_validation: Skip document validation.
            session: Optional client session handle.
        """
        bson_struct = ffi.new("Bson *")
        bson_struct.data = ffi.from_buffer(document)
        bson_struct.len = len(document)

        ctx = ffi.new("OperationContext *")
        ctx.session = session if session else ffi.NULL
        ctx.read_preference = ffi.NULL
        ctx.write_concern = ffi.NULL
        ctx.read_concern = ffi.NULL
        ctx.timeout_ms = -1

        bypass = 1 if bypass_document_validation else -1

        db_bytes = ffi.new("char[]", db_name.encode("utf-8"))
        coll_bytes = ffi.new("char[]", coll_name.encode("utf-8"))

        self._lib.mongo_insert_one(
            self._client,
            ctx,
            db_bytes,
            coll_bytes,
            bson_struct,
            bypass,
            ffi.NULL,  # comment
            callback,
            userdata,
        )

    def find(
        self,
        db_name: str,
        coll_name: str,
        filter_doc: bytes,
        callback: Callable,
        userdata: Any,
        *,
        projection: Optional[bytes] = None,
        sort: Optional[bytes] = None,
        limit: int = 0,
        skip: int = 0,
        batch_size: int = -1,
        session=None,
    ) -> None:
        """Find documents matching a filter (async via callback).

        Args:
            db_name: Database name.
            coll_name: Collection name.
            filter_doc: BSON-encoded filter document.
            callback: FFI callback function.
            userdata: FFI handle to pass to callback.
            projection: Optional BSON-encoded projection.
            sort: Optional BSON-encoded sort specification.
            limit: Maximum documents to return (0 = no limit).
            skip: Number of documents to skip.
            batch_size: Documents per batch (-1 = default).
            session: Optional client session handle.
        """
        filter_struct = ffi.new("Bson *")
        filter_struct.data = ffi.from_buffer(filter_doc)
        filter_struct.len = len(filter_doc)

        ctx = ffi.new("OperationContext *")
        ctx.session = session if session else ffi.NULL
        ctx.read_preference = ffi.NULL
        ctx.write_concern = ffi.NULL
        ctx.read_concern = ffi.NULL
        ctx.timeout_ms = -1

        opts = ffi.new("FindOptions *")
        opts.allow_disk_use = -1
        opts.allow_partial_results = -1
        opts.batch_size = batch_size
        opts.comment = ffi.NULL
        opts.cursor_type = -1
        opts.hint_name = ffi.NULL
        opts.hint_keys = ffi.NULL
        opts.limit = limit
        opts.max = ffi.NULL
        opts.max_await_time_ms = -1
        opts.max_time_ms = -1
        opts.min = ffi.NULL
        opts.no_cursor_timeout = -1
        opts.return_key = -1
        opts.show_record_id = -1
        opts.skip = skip
        opts.sort = ffi.NULL
        opts.collation = ffi.NULL
        opts.let_vars = ffi.NULL

        if projection:
            proj_struct = ffi.new("Bson *")
            proj_struct.data = ffi.from_buffer(projection)
            proj_struct.len = len(projection)
            opts.projection = proj_struct
        else:
            opts.projection = ffi.NULL

        if sort:
            sort_struct = ffi.new("Bson *")
            sort_struct.data = ffi.from_buffer(sort)
            sort_struct.len = len(sort)
            opts.sort = sort_struct

        db_bytes = ffi.new("char[]", db_name.encode("utf-8"))
        coll_bytes = ffi.new("char[]", coll_name.encode("utf-8"))

        self._lib.mongo_find(
            self._client,
            ctx,
            db_bytes,
            coll_bytes,
            filter_struct,
            opts,
            callback,
            userdata,
        )

    def run_command(
        self,
        db_name: str,
        command: bytes,
        callback: Callable,
        userdata: Any,
        *,
        session=None,
    ) -> None:
        """Run a database command (async via callback).

        Args:
            db_name: Database name.
            command: BSON-encoded command document.
            callback: FFI callback function.
            userdata: FFI handle to pass to callback.
            session: Optional client session handle.
        """
        cmd_struct = ffi.new("Bson *")
        cmd_struct.data = ffi.from_buffer(command)
        cmd_struct.len = len(command)

        ctx = ffi.new("OperationContext *")
        ctx.session = session if session else ffi.NULL
        ctx.read_preference = ffi.NULL
        ctx.write_concern = ffi.NULL
        ctx.read_concern = ffi.NULL
        ctx.timeout_ms = -1

        db_bytes = ffi.new("char[]", db_name.encode("utf-8"))

        self._lib.mongo_run_command(
            self._client,
            ctx,
            db_bytes,
            cmd_struct,
            callback,
            userdata,
        )

    def insert_many(
        self,
        db_name: str,
        coll_name: str,
        documents: list,
        callback: Callable,
        userdata: Any,
        keepalive: list,
        *,
        bypass_document_validation: bool = False,
        ordered: bool = True,
        session=None,
    ) -> None:
        """Insert multiple documents (async via callback).

        Args:
            db_name: Database name.
            coll_name: Collection name.
            documents: List of BSON-encoded document bytes.
            callback: FFI callback function.
            userdata: FFI handle to pass to callback.
            keepalive: List to append FFI objects that must stay alive until callback.
            bypass_document_validation: Skip document validation.
            ordered: If True, stop on first error.
            session: Optional client session handle.
        """
        # Build array of document pointers
        buffers = [ffi.from_buffer(doc) for doc in documents]
        ptr_array = ffi.new("uint8_t*[]", buffers)

        # BsonArray is passed by value, so create the struct directly
        docs_struct = ffi.new("BsonArray *")
        docs_struct.data = ptr_array
        docs_struct.len = len(documents)

        ctx = ffi.new("OperationContext *")
        ctx.session = session if session else ffi.NULL
        ctx.read_preference = ffi.NULL
        ctx.write_concern = ffi.NULL
        ctx.read_concern = ffi.NULL
        ctx.timeout_ms = -1

        bypass = 1 if bypass_document_validation else -1

        db_bytes = ffi.new("char[]", db_name.encode("utf-8"))
        coll_bytes = ffi.new("char[]", coll_name.encode("utf-8"))

        # Keep FFI objects alive until callback completes
        keepalive.extend([documents, buffers, ptr_array, docs_struct, ctx, db_bytes, coll_bytes])

        self._lib.mongo_insert_many(
            self._client,
            ctx,
            db_bytes,
            coll_bytes,
            docs_struct[0],  # Pass by value (dereference)
            bypass,
            ordered,
            ffi.NULL,  # comment
            callback,
            userdata,
        )

    def drop_collection(
        self,
        db_name: str,
        coll_name: str,
        callback: Callable,
        userdata: Any,
        *,
        session=None,
    ) -> None:
        """Drop a collection (async via callback).

        Args:
            db_name: Database name.
            coll_name: Collection name.
            callback: FFI callback function.
            userdata: FFI handle to pass to callback.
            session: Optional client session handle.
        """
        ctx = ffi.new("OperationContext *")
        ctx.session = session if session else ffi.NULL
        ctx.read_preference = ffi.NULL
        ctx.write_concern = ffi.NULL
        ctx.read_concern = ffi.NULL
        ctx.timeout_ms = -1

        db_bytes = ffi.new("char[]", db_name.encode("utf-8"))
        coll_bytes = ffi.new("char[]", coll_name.encode("utf-8"))

        self._lib.mongo_drop_collection(
            self._client,
            ctx,
            db_bytes,
            coll_bytes,
            callback,
            userdata,
        )

    def drop_database(
        self,
        db_name: str,
        callback: Callable,
        userdata: Any,
        *,
        session=None,
    ) -> None:
        """Drop a database (async via callback).

        Args:
            db_name: Database name.
            callback: FFI callback function.
            userdata: FFI handle to pass to callback.
            session: Optional client session handle.
        """
        ctx = ffi.new("OperationContext *")
        ctx.session = session if session else ffi.NULL
        ctx.read_preference = ffi.NULL
        ctx.write_concern = ffi.NULL
        ctx.read_concern = ffi.NULL
        ctx.timeout_ms = -1

        db_bytes = ffi.new("char[]", db_name.encode("utf-8"))

        self._lib.mongo_drop_database(
            self._client,
            ctx,
            db_bytes,
            callback,
            userdata,
        )

    def cursor_get_more(
        self,
        cursor,
        callback: Callable,
        userdata: Any,
        *,
        session=None,
    ) -> None:
        """Get more results from a cursor (async via callback).

        Args:
            cursor: Cursor handle from a find operation.
            callback: FFI callback function.
            userdata: FFI handle to pass to callback.
            session: Optional client session handle.
        """
        self._lib.mongo_cursor_get_more(
            self._client,
            cursor,
            session if session else ffi.NULL,
            userdata,
            callback,
        )

    def cursor_close(self, cursor) -> None:
        """Close a cursor and release resources.

        Args:
            cursor: Cursor handle from a find operation.
        """
        if cursor != ffi.NULL:
            self._lib.mongo_cursor_close(cursor)

    # -------------------------------------------------------------------------
    # Session Operations
    # -------------------------------------------------------------------------

    def session_start(self, *, causal_consistency: bool = True, snapshot: bool = False):
        """Start a new client session.

        Args:
            causal_consistency: Enable causal consistency.
            snapshot: Enable snapshot reads.

        Returns:
            Session handle to pass to operations.

        Raises:
            PyMongoError: If session creation fails.
        """
        opts = ffi.new("SessionOptions *")
        opts.causal_consistency = 1 if causal_consistency else 0
        opts.snapshot = 1 if snapshot else 0
        opts.default_transaction_options = ffi.NULL

        error_out = ffi.new("Error **")
        session = self._lib.mongo_session_start(self._client, opts, error_out)

        if session == ffi.NULL:
            if error_out[0] != ffi.NULL:
                exc = convert_error(error_out[0])
                self._lib.error_free(error_out[0])
                raise exc
            raise RuntimeError("Failed to start session")

        return session

    def session_end(self, session) -> None:
        """End a client session.

        Args:
            session: Session handle from session_start.
        """
        if session != ffi.NULL:
            self._lib.mongo_session_end(session)

    def session_start_transaction(
        self,
        session,
        callback: Callable,
        userdata: Any,
    ) -> None:
        """Start a transaction on a session (async via callback).

        Args:
            session: Session handle.
            callback: FFI callback function.
            userdata: FFI handle to pass to callback.
        """
        self._lib.mongo_session_start_transaction(
            self._client,
            session,
            ffi.NULL,  # options - use defaults
            callback,
            userdata,
        )

    def session_commit_transaction(
        self,
        session,
        callback: Callable,
        userdata: Any,
    ) -> None:
        """Commit a transaction (async via callback).

        Args:
            session: Session handle.
            callback: FFI callback function.
            userdata: FFI handle to pass to callback.
        """
        self._lib.mongo_session_commit_transaction(
            self._client,
            session,
            callback,
            userdata,
        )

    def session_abort_transaction(
        self,
        session,
        callback: Callable,
        userdata: Any,
    ) -> None:
        """Abort a transaction (async via callback).

        Args:
            session: Session handle.
            callback: FFI callback function.
            userdata: FFI handle to pass to callback.
        """
        self._lib.mongo_session_abort_transaction(
            self._client,
            session,
            callback,
            userdata,
        )

