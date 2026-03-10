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

"""BSON and options marshalling between Python and native FFI."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

import bson
from bson.codec_options import CodecOptions, DEFAULT_CODEC_OPTIONS
from bson.raw_bson import RawBSONDocument

from pymongo.native_bindings._ffi import ffi

if TYPE_CHECKING:
    from pymongo.read_preferences import _ServerMode


class BsonMarshaller:
    """Handles BSON serialization/deserialization for FFI boundary."""
    
    def __init__(self, codec_options: Optional[CodecOptions] = None):
        """Initialize with codec options.
        
        Args:
            codec_options: BSON codec options for encoding/decoding.
        """
        self.codec_options = codec_options or DEFAULT_CODEC_OPTIONS
    
    def to_bson_struct(self, doc: Any) -> tuple:
        """Convert a document to FFI Bson struct.
        
        Args:
            doc: A dict, RawBSONDocument, or BSON-encodable object.
            
        Returns:
            Tuple of (Bson struct, bytes buffer to keep alive).
        """
        if isinstance(doc, RawBSONDocument):
            data = bytes(doc.raw)
        else:
            data = bson.encode(doc, codec_options=self.codec_options)
        
        bson_struct = ffi.new("Bson *")
        # Keep data alive - caller must hold reference to returned tuple
        bson_struct.data = ffi.from_buffer(data)
        bson_struct.len = len(data)
        return bson_struct, data
    
    def from_bson_struct(self, bson_struct) -> Any:
        """Convert an FFI Bson struct to a Python document.
        
        Args:
            bson_struct: A Bson or OwnedBson struct from FFI.
            
        Returns:
            Decoded document according to codec_options.
        """
        if bson_struct == ffi.NULL:
            return None
        
        data = ffi.buffer(bson_struct.data, bson_struct.len)[:]
        
        if self.codec_options.document_class is RawBSONDocument:
            return RawBSONDocument(data)
        return bson.decode(data, codec_options=self.codec_options)
    
    def from_bson_value(self, bson_value) -> Any:
        """Convert an FFI BsonValue to a Python value.
        
        Args:
            bson_value: A BsonValue or OwnedBsonValue struct from FFI.
            
        Returns:
            Decoded BSON value.
        """
        if bson_value == ffi.NULL:
            return None
        
        # Wrap in a document to decode, then extract the value
        # BSON format: length (4) + type (1) + key + null + value + null
        bson_type = bson_value.bson_type
        data = ffi.buffer(bson_value.data, bson_value.len)[:]
        
        # Build a minimal BSON document containing just this value
        # Document: length (4 bytes) + element + terminator (1 byte)
        # Element: type (1 byte) + key (cstring) + value
        key = b"v\x00"  # "v" + null terminator
        element = bytes([bson_type]) + key + data
        doc_len = 4 + len(element) + 1
        doc_bytes = doc_len.to_bytes(4, "little") + element + b"\x00"
        
        decoded = bson.decode(doc_bytes)
        return decoded.get("v")
    
    def to_bson_array(self, docs: Sequence[Any]) -> tuple:
        """Convert a sequence of documents to FFI BsonArray.
        
        Args:
            docs: Sequence of documents.
            
        Returns:
            Tuple of (BsonArray struct, list of buffers to keep alive).
        """
        buffers = []
        pointers = []
        
        for doc in docs:
            if isinstance(doc, RawBSONDocument):
                data = bytes(doc.raw)
            else:
                data = bson.encode(doc, codec_options=self.codec_options)
            buffers.append(data)
            pointers.append(ffi.from_buffer(data))
        
        # Create array of pointers
        ptr_array = ffi.new("uint8_t*[]", pointers)
        
        array_struct = ffi.new("BsonArray *")
        array_struct.data = ptr_array
        array_struct.len = len(docs)
        
        return array_struct, (buffers, ptr_array)
    
    def from_bson_array(self, bson_array) -> List[Any]:
        """Convert an FFI BsonArray to a list of Python documents.
        
        Args:
            bson_array: A BsonArray struct from FFI.
            
        Returns:
            List of decoded documents.
        """
        if bson_array.data == ffi.NULL or bson_array.len == 0:
            return []
        
        docs = []
        for i in range(bson_array.len):
            ptr = bson_array.data[i]
            # Read BSON document length from first 4 bytes
            length = int.from_bytes(ffi.buffer(ptr, 4)[:], "little")
            data = ffi.buffer(ptr, length)[:]
            
            if self.codec_options.document_class is RawBSONDocument:
                docs.append(RawBSONDocument(data))
            else:
                docs.append(bson.decode(data, codec_options=self.codec_options))
        
        return docs

