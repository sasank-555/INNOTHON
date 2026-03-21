import unittest

from innothon_sim.compare import compare_readings
from innothon_sim.io import load_network_definition


class CompareReadingsTests(unittest.TestCase):
    def test_compare_readings_flags_matches_and_deviations(self) -> None:
        definition = load_network_definition(
            "C:\\Users\\Lenovo\\OneDrive\\Documents\\INNOTHON\\ml\\sample_data\\simple_radial_network.json"
        )
        snapshot = {
            "buses": {"bus_slack": {"vm_pu": 1.0}},
            "lines": {"line_1": {"loading_percent": 41.5}},
            "loads": {"load_1": {"p_mw": 0.6}},
            "transformers": {},
            "static_generators": {},
            "storage": {},
            "external_grids": {},
        }
        readings = {
            "sensor_bus_slack_voltage": 1.0,
            "sensor_load_line_loading": 45.0,
        }

        comparisons = compare_readings(definition, snapshot, readings)

        self.assertEqual(comparisons[0]["status"], "match")
        self.assertEqual(comparisons[1]["status"], "deviation")
        self.assertEqual(comparisons[2]["status"], "missing_actual")


if __name__ == "__main__":
    unittest.main()
