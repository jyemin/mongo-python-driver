# Copyright 2026-present MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Support for the unified test format's wire message assertions (schema 1.30).

This module is shared by the synchronous and asynchronous unified test runners. It decodes
the bytes that a client wrote to a connection, without using any PyMongo code that builds,
parses or compresses messages, so that a bug in the driver's encoding cannot also be a bug
in the decoder.
"""

from __future__ import annotations

import struct
import threading
import zlib
from collections import abc
from dataclasses import dataclass
from typing import Any, Optional

import bson
from test.unified_format_shared import MatchEvaluatorUtil

_HEADER_LENGTH = 16
_OP_QUERY = 2004
_OP_COMPRESSED = 2012
_OP_MSG = 2013
_OPCODE_NAMES = {_OP_QUERY: "OP_QUERY", _OP_COMPRESSED: "OP_COMPRESSED", _OP_MSG: "OP_MSG"}
_OPCODES = {name: code for code, name in _OPCODE_NAMES.items()}


class WireMessageError(Exception):
    """A recorded message is not well formed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WireMessageError(message)


@dataclass
class WireMessage:
    source: str  # application, monitor or rtt
    phase: str  # handshake or operation
    address: tuple
    data: bytes


class WireMessageRecorder:
    """Records the messages that one client writes to the server."""

    def __init__(self, sources: list[str], phases: list[str]):
        self.sources = set(sources)
        self.phases = set(phases)
        self._lock = threading.Lock()
        self._messages: list[WireMessage] = []

    def record(self, source: str, phase: str, address: tuple, data: bytes) -> None:
        if source in self.sources and phase in self.phases:
            with self._lock:
                self._messages.append(WireMessage(source, phase, address, bytes(data)))

    def messages(self, source: str | None = None, address: tuple | None = None):
        with self._lock:
            return [
                m
                for m in self._messages
                if (source is None or m.source == source)
                and (address is None or m.address == address)
            ]

    def check_well_formed(self) -> None:
        """Decode every recorded message, whether or not a test asserts on it."""
        for message in self.messages():
            try:
                decode(message.data)
            except WireMessageError as exc:
                raise AssertionError(
                    f"A {message.source} message to {message.address} is not well formed: {exc}"
                ) from exc


# --- Decoding ----------------------------------------------------------------------------


def decode(data: bytes) -> dict[str, Any]:
    """Decode one message into the form that expectWireMessages matches against."""
    _require(len(data) >= _HEADER_LENGTH, f"message is shorter than a header: {len(data)} bytes")
    length, _request_id, response_to, opcode = struct.unpack_from("<iiii", data, 0)
    _require(
        length == len(data),
        f"header says the message is {length} bytes, but {len(data)} bytes were written",
    )
    _require(opcode in _OPCODE_NAMES, f"Unknown opcode {opcode}")
    result: dict[str, Any] = {"opcode": _OPCODE_NAMES[opcode], "responseTo": response_to}
    body = data[_HEADER_LENGTH:]
    if opcode == _OP_COMPRESSED:
        result.update(_decode_compressed(body))
    else:
        result.update(_decode_body(opcode, body))
    return result


def _decode_compressed(body: bytes) -> dict[str, Any]:
    _require(len(body) >= 9, "OP_COMPRESSED is shorter than its fixed fields")
    original_opcode, uncompressed_size, compressor_id = struct.unpack_from("<iiB", body, 0)
    compressed = body[9:]
    if compressor_id == 0:
        inner = compressed
    elif compressor_id == 2:
        try:
            decompressor = zlib.decompressobj()
            inner = decompressor.decompress(compressed, uncompressed_size + 1)
            _require(decompressor.eof, "the zlib stream is truncated or longer than promised")
        except zlib.error as exc:
            raise WireMessageError(f"invalid zlib data: {exc}") from exc
    else:
        raise WireMessageError(
            f"This runner cannot decompress compressorId {compressor_id} independently of the "
            "driver; only noop (0) and zlib (2) are supported"
        )
    _require(
        len(inner) == uncompressed_size,
        f"header says the uncompressed size is {uncompressed_size}, but decompressing "
        f"produced {len(inner)} bytes",
    )
    _require(original_opcode in _OPCODE_NAMES, f"Unknown opcode {original_opcode}")
    return {
        "originalOpcode": _OPCODE_NAMES[original_opcode],
        "uncompressedSize": uncompressed_size,
        "compressorId": compressor_id,
        "message": _decode_body(original_opcode, inner),
    }


def _decode_body(opcode: int, body: bytes) -> dict[str, Any]:
    if opcode == _OP_MSG:
        return _decode_op_msg(body)
    if opcode == _OP_QUERY:
        return _decode_op_query(body)
    raise WireMessageError(f"Unsupported opcode {opcode}")


_OP_MSG_FLAGS = {0: "checksumPresent", 1: "moreToCome", 16: "exhaustAllowed"}
_OP_QUERY_FLAGS = {
    1: "tailableCursor",
    2: "secondaryOk",
    3: "oplogReplay",
    4: "noCursorTimeout",
    5: "awaitData",
    6: "exhaust",
    7: "partial",
}


def _flag_names(bits: int, names: dict[int, str]) -> list[str]:
    return [names.get(bit, f"unknownBit{bit}") for bit in range(32) if bits & (1 << bit)]


def _read_document(data: bytes, offset: int, limit: int) -> tuple[dict[str, Any], int]:
    _require(limit - offset >= 5, "not enough bytes for a document")
    (size,) = struct.unpack_from("<i", data, offset)
    _require(
        size >= 5 and offset + size <= limit, f"a document claims {size} bytes, which does not fit"
    )
    raw = data[offset : offset + size]
    _require(raw[-1] == 0, "a document does not end with a zero byte")
    return bson.decode(raw), offset + size


def _read_cstring(data: bytes, offset: int, limit: int) -> tuple[str, int]:
    end = data.find(b"\x00", offset, limit)
    _require(end != -1, "a C string is not terminated")
    return data[offset:end].decode("utf-8"), end + 1


def _decode_op_msg(body: bytes) -> dict[str, Any]:
    _require(len(body) >= 4, "OP_MSG is shorter than its flags")
    (flag_bits,) = struct.unpack_from("<I", body, 0)
    checksum_present = bool(flag_bits & 1)
    sections_end = len(body) - (4 if checksum_present else 0)
    _require(
        sections_end >= 4, "message is too short to hold the checksum that checksumPresent promises"
    )

    sections: list[dict[str, Any]] = []
    offset = 4
    while offset < sections_end:
        kind = body[offset]
        offset += 1
        if kind in (0, 3):
            # kind 3 is the telemetry section, a single document like kind 0
            document, offset = _read_document(body, offset, sections_end)
            sections.append({"kind": kind, "body": document})
        elif kind == 1:
            (size,) = struct.unpack_from("<i", body, offset)
            end = offset + size
            _require(
                size >= 5 and end <= sections_end,
                f"a kind 1 section claims {size} bytes, which does not fit in the message",
            )
            identifier, cursor = _read_cstring(body, offset + 4, end)
            documents = []
            while cursor < end:
                document, cursor = _read_document(body, cursor, end)
                documents.append(document)
            _require(cursor == end, "a kind 1 section does not end where its size says it does")
            sections.append({"kind": 1, "identifier": identifier, "documents": documents})
            offset = end
        else:
            raise WireMessageError(f"Unknown OP_MSG section kind {kind}")
    _require(offset == sections_end, "bytes remain after the last section")
    _require_valid_section_counts(sections)

    result: dict[str, Any] = {"flags": _flag_names(flag_bits, _OP_MSG_FLAGS), "sections": sections}
    if checksum_present:
        # The OP_MSG spec reserves the checksum and no driver writes one. It is reported so
        # that a test can assert that there is none, and it is not verified.
        (result["checksum"],) = struct.unpack_from("<I", body, sections_end)
    return result


def _require_valid_section_counts(sections: list[dict[str, Any]]) -> None:
    bodies = sum(1 for s in sections if s["kind"] == 0)
    telemetry = sum(1 for s in sections if s["kind"] == 3)
    identifiers = [s["identifier"] for s in sections if s["kind"] == 1]
    _require(
        bodies == 1, f"an OP_MSG must have exactly one kind 0 section, but this one has {bodies}"
    )
    _require(
        len(identifiers) == len(set(identifiers)),
        "two kind 1 sections have the same identifier",
    )
    _require(
        telemetry <= 1,
        f"an OP_MSG must have at most one kind 3 section, but this one has {telemetry}",
    )


def _decode_op_query(body: bytes) -> dict[str, Any]:
    _require(len(body) >= 4, "OP_QUERY is shorter than its flags")
    (flag_bits,) = struct.unpack_from("<I", body, 0)
    name, offset = _read_cstring(body, 4, len(body))
    _require(len(body) - offset >= 8, "OP_QUERY is shorter than its skip and return counts")
    number_to_skip, number_to_return = struct.unpack_from("<ii", body, offset)
    offset += 8
    query, offset = _read_document(body, offset, len(body))
    result: dict[str, Any] = {
        "flags": _flag_names(flag_bits, _OP_QUERY_FLAGS),
        "fullCollectionName": name,
        "numberToSkip": number_to_skip,
        "numberToReturn": number_to_return,
        "query": query,
    }
    if offset < len(body):
        result["returnFieldsSelector"], offset = _read_document(body, offset, len(body))
    _require(offset == len(body), "bytes remain after the OP_QUERY documents")
    return result


# --- Matching ----------------------------------------------------------------------------


def expand(expected: dict[str, Any]) -> dict[str, Any]:
    """Expand the ``command`` shorthand of an expected message."""
    result = dict(expected)
    opcode = result.get("opcode") or result.get("originalOpcode")
    if "command" in result:
        command = result.pop("command")
        if opcode == "OP_QUERY":
            result["query"] = command
        else:
            result["sections"] = [{"kind": 0, "body": command}]
    if isinstance(result.get("message"), dict):
        inner = dict(result["message"])
        inner["originalOpcode"] = result.get("originalOpcode")
        inner = expand(inner)
        inner.pop("originalOpcode", None)
        result["message"] = inner
    return result


def _same_section(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if "kind" not in expected or expected["kind"] != actual.get("kind"):
        return False
    return (
        expected["kind"] != 1
        or "identifier" not in expected
        or expected["identifier"] == actual.get("identifier")
    )


def _align(expected_sections: list, actual_sections: list) -> list:
    unused = list(actual_sections)
    ordered = []
    for expected in expected_sections:
        match = next(
            (a for a in unused if isinstance(expected, dict) and _same_section(expected, a)), None
        )
        if match is not None:
            unused.remove(match)
            ordered.append(match)
    # a section that no expected section matches stays, so that the sizes differ
    return ordered + unused


def align_sections(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    """Reorder the sections of the actual message into the order of the expected ones.

    The OP_MSG spec allows sections in any order, so their order is not significant.
    """
    result = dict(actual)
    if isinstance(expected.get("sections"), list) and isinstance(actual.get("sections"), list):
        result["sections"] = _align(expected["sections"], actual["sections"])
    if isinstance(expected.get("message"), dict) and isinstance(actual.get("message"), dict):
        result["message"] = align_sections(expected["message"], actual["message"])
    return result


class StrictMatchEvaluator(MatchEvaluatorUtil):
    """The matching rules of the unified test format, with array sizes enforced.

    The shared evaluator does not compare the lengths of arrays.
    """

    def match_result(self, expectation, actual, in_recursive_call=False, test=True):
        if isinstance(expectation, abc.MutableSequence):
            self.test.assertIsInstance(actual, abc.MutableSequence)
            self.test.assertEqual(len(expectation), len(actual), "Arrays must be the same size")
        return super().match_result(
            expectation, actual, in_recursive_call=in_recursive_call, test=test
        )


def assert_messages_match(
    test: Any,
    expected_messages: list[dict[str, Any]],
    actual: list[WireMessage],
    ignore_extra: bool,
) -> None:
    """Assert that the recorded messages match the expected messages."""
    if not expected_messages:
        # An empty list asserts that nothing was written, even if extra messages are ignored.
        test.assertEqual([], [decode(m.data) for m in actual], "Expected no wire messages")
        return
    if ignore_extra:
        test.assertGreaterEqual(len(actual), len(expected_messages), "Too few wire messages")
    else:
        test.assertEqual(
            len(expected_messages), len(actual), "Number of wire messages must be the same"
        )
    matcher = StrictMatchEvaluator(test)
    for expected, message in zip(expected_messages, actual, strict=False):
        expanded = expand(expected)
        decoded = align_sections(expanded, decode(message.data))
        # in_recursive_call makes the message a non-root document, so extra keys are rejected
        matcher.match_result(expanded, decoded, in_recursive_call=True)
