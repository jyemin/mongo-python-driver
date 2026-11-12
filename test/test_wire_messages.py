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

"""Test the decoder and matcher of the unified test format's wire message assertions.

These use hand built messages, because a real server refuses most malformed ones.
"""

from __future__ import annotations

import struct
import sys
import zlib

sys.path[0:0] = [""]

import bson
from test import unittest
from test.wire_messages import (
    WireMessage,
    WireMessageError,
    align_sections,
    assert_messages_match,
    decode,
    expand,
)

_TRACE = {"otel": {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}}


def _header(length: int, opcode: int) -> bytes:
    return struct.pack("<iiii", length, 42, 0, opcode)


def _op_msg(flags: int, sections: bytes) -> bytes:
    body = struct.pack("<I", flags) + sections
    return _header(16 + len(body), 2013) + body


def _section0(doc: dict) -> bytes:
    return b"\x00" + bson.encode(doc)


def _section3(doc: dict) -> bytes:
    return b"\x03" + bson.encode(doc)


def _section1(identifier: str, *docs: dict) -> bytes:
    payload = identifier.encode() + b"\x00" + b"".join(bson.encode(d) for d in docs)
    return b"\x01" + struct.pack("<i", 4 + len(payload)) + payload


def _compress(inner_body: bytes, claimed_size: int) -> bytes:
    rest = struct.pack("<iiB", 2013, claimed_size, 2) + zlib.compress(inner_body)
    return _header(16 + len(rest), 2012) + rest


class _Case(unittest.TestCase):
    def assert_violation(self, data: bytes, text: str) -> None:
        with self.assertRaises(WireMessageError) as ctx:
            decode(data)
        self.assertIn(text, str(ctx.exception))

    def matches(self, expected: dict, data: bytes, ignore_extra: bool = False) -> None:
        assert_messages_match(
            self,
            [expected],
            [WireMessage("application", "operation", ("h", 1), data)],
            ignore_extra,
        )


class TestDecode(_Case):
    def test_plain_op_msg(self):
        self.assertEqual(
            {
                "opcode": "OP_MSG",
                "responseTo": 0,
                "flags": [],
                "sections": [{"kind": 0, "body": {"ping": 1}}],
            },
            decode(_op_msg(0, _section0({"ping": 1}))),
        )

    def test_flags_are_named(self):
        self.assertEqual(
            ["exhaustAllowed"], decode(_op_msg(1 << 16, _section0({"ping": 1})))["flags"]
        )

    def test_telemetry_section(self):
        decoded = decode(_op_msg(0, _section0({"ping": 1}) + _section3(_TRACE)))
        self.assertEqual({"kind": 3, "body": _TRACE}, decoded["sections"][1])

    def test_checksum_is_reported_not_verified(self):
        decoded = decode(_op_msg(1, _section0({"ping": 1}) + bytes([1, 2, 3, 4])))
        self.assertEqual(["checksumPresent"], decoded["flags"])
        self.assertEqual(0x04030201, decoded["checksum"])

    def test_compressed(self):
        inner = _op_msg(0, _section0({"hello": 1}))[16:]
        decoded = decode(_compress(inner, len(inner)))
        self.assertEqual("OP_COMPRESSED", decoded["opcode"])
        self.assertEqual(2, decoded["compressorId"])
        self.assertEqual({"hello": 1}, decoded["message"]["sections"][0]["body"])
        self.assert_violation(_compress(inner, len(inner) + 1), "uncompressed size")

    def test_structural_violations(self):
        data = bytearray(_op_msg(0, _section0({"ping": 1})))
        struct.pack_into("<i", data, 0, len(data) + 3)
        self.assert_violation(bytes(data), "header says the message is")
        self.assert_violation(
            _op_msg(0, _section0({"ping": 1}) + b"\x07\x07\x07"), "Unknown OP_MSG section kind"
        )
        overrun = bytearray(_section1("documents", {"a": 1}))
        struct.pack_into("<i", overrun, 1, 9999)
        self.assert_violation(
            _op_msg(0, _section0({"ping": 1}) + bytes(overrun)), "does not fit in the message"
        )

    def test_section_counts(self):
        self.assert_violation(
            _op_msg(0, _section1("documents", {"a": 1})), "exactly one kind 0 section"
        )
        self.assert_violation(
            _op_msg(0, _section0({"a": 1}) + _section0({"a": 2})), "exactly one kind 0 section"
        )
        self.assert_violation(
            _op_msg(0, _section0({"a": 1}) + _section1("d", {"a": 1}) + _section1("d", {"a": 2})),
            "same identifier",
        )
        self.assert_violation(
            _op_msg(0, _section0({"a": 1}) + _section3(_TRACE) + _section3(_TRACE)),
            "at most one kind 3",
        )


class TestMatch(_Case):
    def test_expand_command_shorthand(self):
        self.assertEqual(
            [{"kind": 0, "body": {"ping": 1}}],
            expand({"opcode": "OP_MSG", "command": {"ping": 1}})["sections"],
        )

    def test_extra_key_fails_but_matchAsRoot_allows_it(self):
        data = _op_msg(0, _section0({"ping": 1, "extra": 1}))
        expected = {"opcode": "OP_MSG", "responseTo": 0, "flags": [], "command": {"ping": 1}}
        with self.assertRaises(AssertionError):
            self.matches(expected, data)
        expected["command"] = {"$$matchAsRoot": {"ping": 1}}
        self.matches(expected, data)

    def test_extra_section_fails(self):
        data = _op_msg(0, _section0({"ping": 1}) + _section3(_TRACE))
        with self.assertRaises(AssertionError):
            self.matches(
                {"opcode": "OP_MSG", "responseTo": 0, "flags": [], "command": {"ping": 1}}, data
            )

    def test_sections_match_in_any_order(self):
        data = _op_msg(0, _section3(_TRACE) + _section0({"ping": 1}))
        expected = {
            "opcode": "OP_MSG",
            "responseTo": 0,
            "flags": [],
            "sections": [
                {"kind": 0, "body": {"ping": 1}},
                {"kind": 3, "body": {"otel": {"traceparent": {"$$type": "string"}}}},
            ],
        }
        self.matches(expected, data)
        wrong = {
            **expected,
            "sections": [{"kind": 0, "body": {"ping": 2}}, expected["sections"][1]],
        }
        with self.assertRaises(AssertionError):
            self.matches(wrong, data)

    def test_document_sequences_pair_by_identifier(self):
        decoded = decode(
            _op_msg(
                0,
                _section1("nsInfo", {"ns": "a.b"})
                + _section0({"bulkWrite": 1})
                + _section1("ops", {"insert": 0}, {"insert": 1}),
            )
        )
        expected = {
            "sections": [
                {"kind": 0, "body": {"bulkWrite": 1}},
                {"kind": 1, "identifier": "ops", "documents": [{"insert": 0}, {"insert": 1}]},
                {"kind": 1, "identifier": "nsInfo", "documents": [{"ns": "a.b"}]},
            ]
        }
        aligned = align_sections(expected, decoded)
        self.assertEqual([0, 1, 1], [s["kind"] for s in aligned["sections"]])
        self.assertEqual("ops", aligned["sections"][1]["identifier"])

    def test_empty_expected_messages_asserts_none_even_when_ignoring_extras(self):
        assert_messages_match(self, [], [], True)
        assert_messages_match(self, [], [], False)
        written = WireMessage("monitor", "operation", ("h", 1), _op_msg(0, _section0({"hello": 1})))
        with self.assertRaises(AssertionError):
            assert_messages_match(self, [], [written], True)
        with self.assertRaises(AssertionError):
            assert_messages_match(self, [], [written], False)

    def test_array_sizes_must_match(self):
        data = _op_msg(0, _section0({"hello": 1, "compression": ["zlib"]}))
        expected = {
            "opcode": "OP_MSG",
            "responseTo": 0,
            "flags": [],
            "command": {"hello": 1, "compression": []},
        }
        with self.assertRaises(AssertionError):
            self.matches(expected, data)


if __name__ == "__main__":
    unittest.main()
