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

"""Integration tests for native bindings."""

import unittest
from bson import ObjectId

from pymongo.native_bindings import (
    NativeSyncMongoClient,
    NativeSyncSession,
    UnsupportedOperationError,
    is_available,
)


class TestNativeSyncClient(unittest.TestCase):
    """Tests for NativeSyncMongoClient."""
    
    @classmethod
    def setUpClass(cls):
        if not is_available():
            raise unittest.SkipTest("Native library not available")
        cls.client = NativeSyncMongoClient("localhost", 27017)
        cls.db = cls.client["test_native"]
        cls.coll = cls.db["test_collection"]
    
    @classmethod
    def tearDownClass(cls):
        cls.coll.drop()
        cls.client.close()
    
    def setUp(self):
        self.coll.drop()
    
    # -------------------------------------------------------------------------
    # Basic Operations
    # -------------------------------------------------------------------------
    
    def test_insert_one(self):
        result = self.coll.insert_one({"x": 1})
        self.assertIsInstance(result.inserted_id, ObjectId)
        self.assertTrue(result.acknowledged)
    
    def test_insert_one_with_id(self):
        doc_id = ObjectId()
        result = self.coll.insert_one({"_id": doc_id, "x": 1})
        self.assertEqual(result.inserted_id, doc_id)
    
    def test_insert_many(self):
        result = self.coll.insert_many([{"x": 1}, {"x": 2}, {"x": 3}])
        self.assertEqual(len(result.inserted_ids), 3)
        self.assertTrue(result.acknowledged)
    
    def test_find_one(self):
        self.coll.insert_one({"name": "Alice", "age": 30})
        doc = self.coll.find_one({"name": "Alice"})
        self.assertIsNotNone(doc)
        self.assertEqual(doc["name"], "Alice")
        self.assertEqual(doc["age"], 30)
    
    def test_find_one_not_found(self):
        doc = self.coll.find_one({"name": "NonExistent"})
        self.assertIsNone(doc)
    
    def test_find(self):
        self.coll.insert_many([{"x": 1}, {"x": 2}, {"x": 3}])
        docs = list(self.coll.find())
        self.assertEqual(len(docs), 3)
    
    def test_find_with_filter(self):
        self.coll.insert_many([{"x": 1}, {"x": 2}, {"x": 3}])
        docs = list(self.coll.find({"x": {"$gt": 1}}))
        self.assertEqual(len(docs), 2)
    
    def test_find_with_projection(self):
        self.coll.insert_one({"x": 1, "y": 2, "z": 3})
        doc = self.coll.find_one(projection={"x": 1, "_id": 0})
        self.assertEqual(doc, {"x": 1})
    
    def test_find_with_limit(self):
        self.coll.insert_many([{"x": i} for i in range(10)])
        docs = list(self.coll.find(limit=3))
        self.assertEqual(len(docs), 3)
    
    def test_find_with_skip(self):
        self.coll.insert_many([{"x": i} for i in range(10)])
        docs = list(self.coll.find(skip=7))
        self.assertEqual(len(docs), 3)
    
    def test_find_with_sort(self):
        self.coll.insert_many([{"x": 3}, {"x": 1}, {"x": 2}])
        docs = list(self.coll.find(sort=[("x", 1)]))
        self.assertEqual([d["x"] for d in docs], [1, 2, 3])
    
    def test_cursor_iteration_multiple_batches(self):
        """Test cursor getMore with many documents."""
        self.coll.insert_many([{"i": i} for i in range(250)])
        count = 0
        for doc in self.coll.find(batch_size=10):
            count += 1
        self.assertEqual(count, 250)
    
    def test_drop_collection(self):
        self.coll.insert_one({"x": 1})
        self.coll.drop()
        self.assertEqual(self.coll.find_one(), None)
    
    def test_database_command(self):
        result = self.db.command("ping")
        self.assertEqual(result.get("ok"), 1.0)
    
    # -------------------------------------------------------------------------
    # Unsupported Operations
    # -------------------------------------------------------------------------
    
    def test_update_one_unsupported(self):
        with self.assertRaises(UnsupportedOperationError):
            self.coll.update_one({"x": 1}, {"$set": {"x": 2}})
    
    def test_delete_one_unsupported(self):
        with self.assertRaises(UnsupportedOperationError):
            self.coll.delete_one({"x": 1})
    
    def test_aggregate_unsupported(self):
        with self.assertRaises(UnsupportedOperationError):
            self.coll.aggregate([{"$match": {"x": 1}}])


class TestNativeSyncTransactions(unittest.TestCase):
    """Tests for transactions (requires replica set)."""
    
    @classmethod
    def setUpClass(cls):
        if not is_available():
            raise unittest.SkipTest("Native library not available")
        cls.client = NativeSyncMongoClient("localhost", 27017)
        # Check if replica set
        result = cls.client["admin"].command("hello")
        if not result.get("setName"):
            cls.client.close()
            raise unittest.SkipTest("Transactions require a replica set")
        cls.db = cls.client["test_native_txn"]
        cls.coll = cls.db["txn_test"]
    
    @classmethod
    def tearDownClass(cls):
        cls.coll.drop()
        cls.client.close()

    def setUp(self):
        self.coll.drop()

    def test_transaction_commit(self):
        """Test basic transaction commit."""
        with self.client.start_session() as session:
            session.start_transaction()

            self.coll.insert_one({"name": "Alice"}, session=session)
            self.coll.insert_one({"name": "Bob"}, session=session)

            # Should see data within transaction
            doc = self.coll.find_one({"name": "Alice"}, session=session)
            self.assertIsNotNone(doc)

            session.commit_transaction()

        # Data should be persisted after commit
        docs = list(self.coll.find())
        self.assertEqual(len(docs), 2)

    def test_transaction_abort(self):
        """Test transaction abort."""
        # Insert initial data
        self.coll.insert_one({"name": "Initial"})

        with self.client.start_session() as session:
            session.start_transaction()

            self.coll.insert_one({"name": "WillBeAborted"}, session=session)

            # Should see data within transaction
            docs = list(self.coll.find(session=session))
            self.assertEqual(len(docs), 2)

            session.abort_transaction()

        # Aborted data should not be persisted
        docs = list(self.coll.find())
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Initial")

    def test_transaction_insert_many(self):
        """Test insert_many in transaction."""
        with self.client.start_session() as session:
            session.start_transaction()

            result = self.coll.insert_many([
                {"x": 1},
                {"x": 2},
                {"x": 3},
            ], session=session)
            self.assertEqual(len(result.inserted_ids), 3)

            session.commit_transaction()

        docs = list(self.coll.find())
        self.assertEqual(len(docs), 3)

    def test_transaction_find_cursor(self):
        """Test cursor iteration within transaction."""
        with self.client.start_session() as session:
            session.start_transaction()

            self.coll.insert_many([{"i": i} for i in range(100)], session=session)

            # Iterate cursor within transaction
            count = 0
            for doc in self.coll.find(batch_size=10, session=session):
                count += 1
            self.assertEqual(count, 100)

            session.commit_transaction()

    def test_session_context_manager(self):
        """Test session as context manager."""
        with self.client.start_session() as session:
            self.assertIsNotNone(session.session_id)
        # Session should be ended after context exit


class TestNativeAsyncClient(unittest.TestCase):
    """Tests for NativeAsyncMongoClient."""

    @classmethod
    def setUpClass(cls):
        if not is_available():
            raise unittest.SkipTest("Native library not available")
        import asyncio
        from pymongo.native_bindings import NativeAsyncMongoClient
        cls.NativeAsyncMongoClient = NativeAsyncMongoClient
        cls.asyncio = asyncio

    def _run(self, coro):
        """Helper to run async code in sync tests."""
        return self.asyncio.get_event_loop().run_until_complete(coro)

    def test_insert_and_find(self):
        async def run():
            async with self.NativeAsyncMongoClient("localhost", 27017) as client:
                coll = client["test_native_async"]["test_coll"]
                await coll.drop()

                result = await coll.insert_one({"x": 1})
                self.assertIsInstance(result.inserted_id, ObjectId)

                doc = await coll.find_one({"x": 1})
                self.assertIsNotNone(doc)
                self.assertEqual(doc["x"], 1)

                await coll.drop()
        self._run(run())

    def test_insert_many_and_find_cursor(self):
        async def run():
            async with self.NativeAsyncMongoClient("localhost", 27017) as client:
                coll = client["test_native_async"]["test_coll"]
                await coll.drop()

                result = await coll.insert_many([{"i": i} for i in range(100)])
                self.assertEqual(len(result.inserted_ids), 100)

                count = 0
                async for doc in coll.find(batch_size=10):
                    count += 1
                self.assertEqual(count, 100)

                await coll.drop()
        self._run(run())

    def test_to_list(self):
        async def run():
            async with self.NativeAsyncMongoClient("localhost", 27017) as client:
                coll = client["test_native_async"]["test_coll"]
                await coll.drop()

                await coll.insert_many([{"x": i} for i in range(5)])
                docs = await coll.find().to_list()
                self.assertEqual(len(docs), 5)

                await coll.drop()
        self._run(run())


class TestNativeAsyncTransactions(unittest.TestCase):
    """Tests for async transactions (requires replica set)."""

    @classmethod
    def setUpClass(cls):
        if not is_available():
            raise unittest.SkipTest("Native library not available")
        import asyncio
        from pymongo.native_bindings import NativeAsyncMongoClient
        cls.NativeAsyncMongoClient = NativeAsyncMongoClient
        cls.asyncio = asyncio

        # Check if replica set
        client = NativeSyncMongoClient("localhost", 27017)
        result = client["admin"].command("hello")
        client.close()
        if not result.get("setName"):
            raise unittest.SkipTest("Transactions require a replica set")

    def _run(self, coro):
        return self.asyncio.get_event_loop().run_until_complete(coro)

    def test_async_transaction_commit(self):
        async def run():
            async with self.NativeAsyncMongoClient("localhost", 27017) as client:
                coll = client["test_native_async_txn"]["test_coll"]
                await coll.drop()

                async with client.start_session() as session:
                    await session.start_transaction()

                    await coll.insert_one({"name": "Alice"}, session=session)
                    await coll.insert_one({"name": "Bob"}, session=session)

                    await session.commit_transaction()

                docs = await coll.find().to_list()
                self.assertEqual(len(docs), 2)

                await coll.drop()
        self._run(run())

    def test_async_transaction_abort(self):
        async def run():
            async with self.NativeAsyncMongoClient("localhost", 27017) as client:
                coll = client["test_native_async_txn"]["test_coll"]
                await coll.drop()

                await coll.insert_one({"name": "Initial"})

                async with client.start_session() as session:
                    await session.start_transaction()
                    await coll.insert_one({"name": "WillBeAborted"}, session=session)
                    await session.abort_transaction()

                docs = await coll.find().to_list()
                self.assertEqual(len(docs), 1)

                await coll.drop()
        self._run(run())


if __name__ == "__main__":
    unittest.main()

