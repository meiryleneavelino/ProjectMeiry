import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from model import aggregate, export_model, generate_dataset, initial_model, prepare_dataset, train_local


class FederatedModelTests(unittest.TestCase):
    def test_seed_retry_preserves_existing_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "dataset.csv"
            prepare_dataset("VU", dataset)
            original = dataset.read_bytes()
            prepare_dataset("VU", dataset)
            self.assertEqual(original, dataset.read_bytes())
            dataset.write_text("feature_1,feature_2,feature_3,feature_4,target\n1,2,3,4,0\n")
            incomplete = dataset.read_bytes()
            with self.assertRaises(ValueError):
                prepare_dataset("VU", dataset)
            self.assertEqual(incomplete, dataset.read_bytes())

    def test_weighted_aggregation(self):
        updates = [
            {"coefficients": [1.0] * 4, "intercept": 1.0, "samples": 1},
            {"coefficients": [3.0] * 4, "intercept": 3.0, "samples": 3},
        ]
        self.assertEqual(aggregate(updates), {"coefficients": [2.5] * 4, "intercept": 2.5})

    def test_nonfinite_updates_are_rejected(self):
        with self.assertRaises(ValueError):
            aggregate([{"coefficients": [float("nan")] * 4, "intercept": 0.0, "samples": 1}])

    def test_training_distinct_local_data_exports_only_model(self):
        with tempfile.TemporaryDirectory() as directory:
            datasets = []
            global_model = initial_model()
            for organization in ("UVA", "VU", "TUDELFT"):
                dataset = Path(directory) / organization / "dataset.csv"
                generate_dataset(organization, dataset)
                datasets.append(dataset)
            self.assertFalse(np.array_equal(np.loadtxt(datasets[0], delimiter=",", skiprows=1),
                                            np.loadtxt(datasets[1], delimiter=",", skiprows=1)))
            for round_number in range(1, 4):
                updates = [train_local(dataset, global_model, 2, round_number) for dataset in datasets]
                global_model = aggregate(updates)
            self.assertGreater(min(update["accuracy"] for update in updates), 0.75)
            artifact = Path(directory) / "model.json"
            export_model(artifact, global_model, ["UVA", "VU", "TUDELFT"], 3)
            result = json.loads(artifact.read_text())
            self.assertEqual(len(result["coefficients"]), 4)
            self.assertNotIn("dataset", result)
            self.assertNotIn("samples", result)
            with self.assertRaises(ValueError):
                generate_dataset("UVA", datasets[0])


if __name__ == "__main__":
    unittest.main()