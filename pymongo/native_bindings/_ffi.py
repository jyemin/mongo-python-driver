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

"""cffi definitions for libmongocore.

This module defines the C types and function signatures from libmongodb.h
for use with cffi's ABI mode.
"""

from __future__ import annotations

from cffi import FFI

ffi = FFI()

# C type definitions from libmongodb.h
ffi.cdef("""
    /* Opaque types */
    typedef struct MongoClient MongoClient;
    typedef struct ClientSession ClientSession;
    typedef struct Cursor Cursor;
    typedef struct ReadConcern ReadConcern;
    typedef struct ReadPreference ReadPreference;
    typedef struct WriteConcern WriteConcern;

    /* BSON types */
    typedef struct Bson {
        const uint8_t *data;
        size_t len;
    } Bson;
    
    typedef struct Bson OwnedBson;
    
    typedef struct BsonValue {
        const uint8_t *data;
        size_t len;
        uint8_t bson_type;
    } BsonValue;
    
    typedef struct BsonValue OwnedBsonValue;
    
    typedef struct BsonArray {
        const uint8_t *const *data;
        size_t len;
    } BsonArray;

    /* Error types */
    typedef uint8_t ErrorType;
    
    typedef struct ServerError {
        int32_t code;
        const char *code_name;
        const char *message;
        const char *const *labels;
        size_t labels_len;
        OwnedBson server_response;
    } ServerError;
    
    typedef struct WriteError {
        uint32_t index;
        int32_t code;
        const char *code_name;
        const char *message;
        OwnedBson details;
    } WriteError;
    
    typedef struct WriteConcernError {
        int32_t code;
        const char *code_name;
        const char *message;
        OwnedBson details;
        const char *const *labels;
        size_t labels_len;
    } WriteConcernError;
    
    typedef struct InsertManyError {
        const WriteError *write_errors;
        size_t write_errors_len;
        const WriteConcernError *write_concern_error;
        OwnedBson inserted_ids;
    } InsertManyError;
    
    typedef struct BulkWriteError {
        const WriteError *write_errors;
        size_t write_errors_len;
        const WriteConcernError *write_concern_error;
        const void *partial_result;
    } BulkWriteError;
    
    typedef struct IoError { const char *message; } IoError;
    typedef struct ServerSelectionError { const char *message; int64_t timeout_ms; } ServerSelectionError;
    typedef struct TimeoutError { const char *message; int64_t timeout_ms; } TimeoutError;
    typedef struct AuthError { const char *message; } AuthError;
    typedef struct InvalidArgumentError { const char *message; } InvalidArgumentError;
    typedef struct TransactionError { const char *message; const char *const *labels; size_t labels_len; } TransactionError;
    typedef struct IncompatibleServerError { const char *message; } IncompatibleServerError;
    typedef struct InvalidResponseError { const char *message; } InvalidResponseError;
    typedef struct ChangeStreamError { const char *message; bool resumable; } ChangeStreamError;
    typedef struct ShutdownError { } ShutdownError;
    
    typedef union ErrorUnion {
        const ServerError *server;
        const InsertManyError *insert_many;
        const BulkWriteError *bulk_write;
        const IoError *io;
        const ServerSelectionError *server_selection;
        const TimeoutError *timeout;
        const AuthError *auth;
        const InvalidArgumentError *invalid_argument;
        const TransactionError *transaction;
        const IncompatibleServerError *incompatible_server;
        const InvalidResponseError *invalid_response;
        const ChangeStreamError *change_stream;
        const ShutdownError *shutdown;
    } ErrorUnion;
    
    typedef struct Error {
        uint8_t error_type;
        ErrorUnion error;
    } Error;

    /* Settings structs */
    typedef struct ConnectionSettings {
        const char *hosts;
        const char *app_name;
        const char *compressors;
        bool direct_connection;
        bool load_balanced;
        int32_t max_pool_size;
        int32_t min_pool_size;
        int64_t max_idle_time_ms;
        int64_t connect_timeout_ms;
        int64_t socket_timeout_ms;
        int64_t server_selection_timeout_ms;
        int64_t local_threshold_ms;
        int64_t heartbeat_frequency_ms;
        const char *replica_set;
        uint8_t read_preference_mode;
        const char *srv_service_name;
        int32_t srv_max_hosts;
    } ConnectionSettings;

    typedef struct AuthSettings {
        const char *mechanism;
        const char *username;
        const char *password;
        const char *source;
    } AuthSettings;

    typedef struct TlsSettings {
        bool enabled;
        bool allow_invalid_certificates;
        bool allow_invalid_hostnames;
        const char *ca_file;
        const char *cert_file;
        const char *cert_key_file;
    } TlsSettings;

    typedef struct OperationContext {
        ClientSession *session;
        const ReadPreference *read_preference;
        const WriteConcern *write_concern;
        const ReadConcern *read_concern;
        int64_t timeout_ms;
    } OperationContext;

    /* Result structs */
    typedef struct InsertOneResult {
        OwnedBsonValue inserted_id;
    } InsertOneResult;

    typedef struct InsertedId {
        size_t index;
        OwnedBsonValue id;
    } InsertedId;

    typedef struct InsertManyResult {
        const InsertedId *inserted_ids;
        size_t inserted_ids_len;
    } InsertManyResult;

    typedef struct CursorResult {
        Cursor *cursor;
        bool exhausted;
        BsonArray first_batch;
    } CursorResult;

    /* Find options */
    typedef struct FindOptions {
        int8_t allow_disk_use;
        int8_t allow_partial_results;
        int32_t batch_size;
        const Bson *comment;
        int8_t cursor_type;
        const char *hint_name;
        const Bson *hint_keys;
        int64_t limit;
        const Bson *max;
        int64_t max_await_time_ms;
        int64_t max_time_ms;
        const Bson *min;
        int8_t no_cursor_timeout;
        const Bson *projection;
        int8_t return_key;
        int8_t show_record_id;
        int64_t skip;
        const Bson *sort;
        const Bson *collation;
        const Bson *let_vars;
    } FindOptions;

    /* Callback types */
    typedef void (*InsertOneCallback)(void *userdata, const InsertOneResult *result, const Error *error);
    typedef void (*InsertManyCallback)(void *userdata, const InsertManyResult *result, const Error *error);
    typedef void (*FindCallback)(void *userdata, const CursorResult *result, const Error *error);
    typedef void (*GetMoreResultCallback)(void *userdata, bool exhausted, BsonArray data, const Error *error);
    typedef void (*RunCommandCallback)(void *userdata, const OwnedBson *result, const Error *error);
    typedef void (*DropCallback)(void *userdata, const Error *error);
    typedef void (*TransactionCallback)(void *userdata, const Error *error);

    /* Client functions */
    MongoClient *mongo_client_new(
        const ConnectionSettings *connection_settings,
        const AuthSettings *auth_settings,
        const TlsSettings *tls_settings,
        Error **error_out
    );
    void mongo_client_destroy(MongoClient *client);

    /* Error functions */
    void error_free(Error *error_ptr);

    /* CRUD operations */
    void mongo_insert_one(
        MongoClient *client,
        const OperationContext *ctx,
        const char *db_name,
        const char *coll_name,
        const Bson *document,
        int8_t bypass_document_validation,
        const BsonValue *comment,
        InsertOneCallback callback,
        void *userdata
    );

    void mongo_insert_many(
        MongoClient *client,
        const OperationContext *ctx,
        const char *db_name,
        const char *coll_name,
        BsonArray documents,
        int8_t bypass_document_validation,
        bool ordered,
        const BsonValue *comment,
        InsertManyCallback callback,
        void *userdata
    );

    void mongo_find(
        MongoClient *client,
        const OperationContext *ctx,
        const char *db_name,
        const char *coll_name,
        const Bson *filter,
        const FindOptions *opts,
        FindCallback callback,
        void *userdata
    );

    /* Cursor operations */
    void mongo_cursor_get_more(
        MongoClient *client,
        Cursor *cursor,
        ClientSession *session,
        void *userdata,
        GetMoreResultCallback callback
    );
    void mongo_cursor_close(Cursor *cursor);

    /* Command operations */
    void mongo_run_command(
        MongoClient *client,
        OperationContext *context,
        const char *db_name,
        const Bson *command,
        RunCommandCallback callback,
        void *userdata
    );

    /* Database/Collection operations */
    void mongo_drop_database(
        MongoClient *client,
        OperationContext *context,
        const char *db_name,
        DropCallback callback,
        void *userdata
    );

    void mongo_drop_collection(
        MongoClient *client,
        OperationContext *context,
        const char *db_name,
        const char *coll_name,
        DropCallback callback,
        void *userdata
    );

    /* Session options */
    typedef struct TransactionOptions {
        const char *read_concern_level;
        int32_t write_concern_w;
        const char *write_concern_w_tag;
        int8_t write_concern_j;
        int64_t write_concern_w_timeout_ms;
        uint8_t read_preference_mode;
        int64_t max_commit_time_ms;
    } TransactionOptions;

    typedef struct SessionOptions {
        int8_t causal_consistency;
        int8_t snapshot;
        const TransactionOptions *default_transaction_options;
    } SessionOptions;

    /* Session operations */
    ClientSession *mongo_session_start(
        MongoClient *client,
        const SessionOptions *options,
        Error **error_out
    );
    void mongo_session_end(ClientSession *session);

    void mongo_session_start_transaction(
        MongoClient *client,
        ClientSession *session,
        const TransactionOptions *options,
        TransactionCallback callback,
        void *userdata
    );

    void mongo_session_commit_transaction(
        MongoClient *client,
        ClientSession *session,
        TransactionCallback callback,
        void *userdata
    );

    void mongo_session_abort_transaction(
        MongoClient *client,
        ClientSession *session,
        TransactionCallback callback,
        void *userdata
    );

    /* Read/Write Concern */
    typedef struct ReadConcernOptions {
        const char *level;
    } ReadConcernOptions;

    typedef struct WriteConcernOptions {
        int32_t w;
        const char *w_tag;
        int8_t journal;
        int64_t w_timeout_ms;
    } WriteConcernOptions;

    typedef struct ReadPreferenceOptions {
        const Bson *tags;
        int64_t max_staleness_seconds;
        const Bson *hedge;
    } ReadPreferenceOptions;

    ReadConcern *mongo_read_concern_create(const ReadConcernOptions *options);
    void mongo_read_concern_destroy(ReadConcern *handle);

    WriteConcern *mongo_write_concern_create(const WriteConcernOptions *options);
    void mongo_write_concern_destroy(WriteConcern *handle);

    ReadPreference *mongo_read_preference_create(uint8_t mode, const ReadPreferenceOptions *options);
    void mongo_read_preference_destroy(ReadPreference *handle);
""")

# Library handle - loaded lazily
_lib = None


def get_lib():
    """Get the loaded native library, loading it if necessary."""
    global _lib
    if _lib is None:
        from pymongo.native_bindings._loader import get_library_path
        path = get_library_path()
        if path is None:
            raise RuntimeError("Native library not found. Set LIBMONGODB_PATH environment variable.")
        _lib = ffi.dlopen(path)
    return _lib


# Pre-cache type for efficient pointer casting (avoids pycparser overhead)
_uintptr_t = ffi.typeof("uintptr_t")


def cast_to_int(ptr):
    """Cast a cffi pointer to an integer efficiently."""
    return int(ffi.cast(_uintptr_t, ptr))

