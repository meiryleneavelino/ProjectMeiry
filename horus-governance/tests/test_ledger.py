import json
import tempfile
import unittest

from app.ledger import SQLiteLedger
from app.storage import IntegrityError, Store


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name)
        self.ledger = SQLiteLedger(self.store)

    def event(self):
        return self.ledger.append("CodeSubmitted", {
            "code_hash": "a" * 64, "researcher_id": "opaque-001", "researcher_org": "TUDELFT"})

    def test_chain_links_and_filters(self):
        first = self.event()
        second = self.event()
        self.assertEqual(second["previous_hash"], first["record_hash"])
        self.assertTrue(self.ledger.verify()["valid"])
        self.assertEqual(self.ledger.events(code_hash="a" * 64)["total"], 2)
        self.assertEqual(self.ledger.events(event_type="TrainingStarted")["total"], 0)
        self.assertEqual(len(self.ledger.events(limit=1)["items"]), 1)
        self.assertEqual(self.ledger.get(first["tx_id"]), first)

    def test_record_tampering_blocks_writes(self):
        event = self.event()
        event["payload"]["researcher_org"] = "UVA"
        with self.store.transaction() as connection:
            connection.execute("UPDATE events SET envelope=?", (json.dumps(event),))
        self.assertFalse(self.ledger.verify()["valid"])
        with self.assertRaises(IntegrityError):
            self.event()

    def test_deletion_is_detected_by_anchor(self):
        self.event()
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM events")
        self.assertFalse(self.ledger.verify()["valid"])

    def test_code_and_names_cannot_be_event_fields(self):
        with self.assertRaises(ValueError):
            self.ledger.append("CodeSubmitted", {"code": "print(1)", "name": "Person"})
        self.assertEqual(self.ledger.events()["total"], 0)


if __name__ == "__main__":
    unittest.main()