from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import fault_service
from utils.mongo_indexes import run_index_initializers


class IndexBootstrapTests(unittest.TestCase):
    def test_failure_does_not_block_later_initializers(self):
        logger = MagicMock()
        first = MagicMock(side_effect=RuntimeError("duplicate legacy key"))
        second = MagicMock()

        summary = run_index_initializers(
            [("faults", first), ("vehicle_movements", second)],
            logger=logger,
        )

        first.assert_called_once_with()
        second.assert_called_once_with()
        logger.exception.assert_called_once_with(
            "[Flux Startup] Index checks failed for %s.", "faults"
        )
        self.assertEqual(summary["completed"], ["vehicle_movements"])
        self.assertEqual(summary["failed"], ["faults"])
        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(summary["failed_count"], 1)

    def test_fault_link_unique_index_ignores_missing_fault_ids(self):
        with (
            patch.object(fault_service, "faults_collection", return_value=MagicMock()),
            patch.object(fault_service, "fault_categories_collection", return_value=MagicMock()),
            patch.object(fault_service, "fault_components_collection", return_value=MagicMock()),
            patch.object(fault_service, "maintenance_jobs_collection", return_value=MagicMock()),
            patch.object(fault_service, "ensure_indexes_for_collection") as ensure_indexes,
        ):
            fault_service.ensure_fault_indexes()

        fault_link_spec = ensure_indexes.call_args_list[-1].args[1][0]
        self.assertEqual(fault_link_spec["keys"], [("fault_id", 1)])
        self.assertEqual(
            fault_link_spec["options"],
            {
                "name": "fault_id_unique_when_present",
                "unique": True,
                "partialFilterExpression": {"fault_id": {"$type": "objectId"}},
            },
        )


if __name__ == "__main__":
    unittest.main()
