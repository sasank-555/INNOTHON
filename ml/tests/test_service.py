import unittest
from unittest.mock import patch

from innothon_sim.service import compare_network_payload, simulate_network_payload


NETWORK_PAYLOAD = {
    "network": {
        "name": "service-test-network",
    },
    "buses": [
        {
            "id": "bus_1",
            "vn_kv": 11.0,
        }
    ],
}


SIMULATION_SNAPSHOT = {
    "network": {
        "meta": {
            "name": "service-test-network",
            "converged": True,
        }
    },
    "buses": {},
    "external_grids": {},
    "lines": {},
    "transformers": {},
    "loads": {},
    "static_generators": {},
    "storage": {},
}


class SimulateNetworkPayloadTests(unittest.TestCase):
    @patch("innothon_sim.service.run_simulation")
    def test_simulate_network_payload_returns_stable_shape(self, mock_run_simulation) -> None:
        mock_run_simulation.return_value.snapshot = SIMULATION_SNAPSHOT

        response = simulate_network_payload(NETWORK_PAYLOAD)

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["network_name"], "service-test-network")
        self.assertTrue(response["converged"])
        self.assertEqual(response["snapshot"], SIMULATION_SNAPSHOT)

    @patch("innothon_sim.service.run_simulation")
    def test_compare_network_payload_returns_comparisons(self, mock_run_simulation) -> None:
        mock_run_simulation.return_value.snapshot = {
            **SIMULATION_SNAPSHOT,
            "buses": {"bus_1": {"vm_pu": 1.0}},
        }
        network_payload = {
            **NETWORK_PAYLOAD,
            "external_grids": [
                {
                    "id": "grid_1",
                    "bus_id": "bus_1",
                    "name": "Grid",
                }
            ],
            "sensor_links": [
                {
                    "sensor_id": "sensor_1",
                    "element_type": "bus",
                    "element_id": "bus_1",
                    "measurement": "vm_pu",
                }
            ],
        }

        response = compare_network_payload(network_payload, {"sensor_1": 1.02})

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["comparisons"][0]["sensor_id"], "sensor_1")
        self.assertEqual(response["comparisons"][0]["status"], "deviation")

    @patch("innothon_sim.service.run_simulation")
    def test_compare_network_payload_uses_reasonable_tolerance_for_power(self, mock_run_simulation) -> None:
        mock_run_simulation.return_value.snapshot = {
            **SIMULATION_SNAPSHOT,
            "loads": {"load_1": {"p_mw": 0.2}},
        }
        network_payload = {
            **NETWORK_PAYLOAD,
            "external_grids": [
                {
                    "id": "grid_1",
                    "bus_id": "bus_1",
                    "name": "Grid",
                }
            ],
            "loads": [
                {
                    "id": "load_1",
                    "bus_id": "bus_1",
                    "p_mw": 0.2,
                    "q_mvar": 0.05,
                }
            ],
            "sensor_links": [
                {
                    "sensor_id": "sensor_load_1",
                    "element_type": "load",
                    "element_id": "load_1",
                    "measurement": "p_mw",
                }
            ],
        }

        response = compare_network_payload(network_payload, {"sensor_load_1": 0.204})

        self.assertEqual(response["comparisons"][0]["status"], "match")

    @patch("innothon_sim.service.run_simulation")
    def test_compare_network_payload_flags_disconnected_loads_as_topology_issue(self, mock_run_simulation) -> None:
        mock_run_simulation.return_value.snapshot = {
            **SIMULATION_SNAPSHOT,
            "loads": {"load_1": {"p_mw": 0.0}},
        }
        network_payload = {
            **NETWORK_PAYLOAD,
            "buses": [
                {"id": "bus_1", "vn_kv": 11.0},
                {"id": "bus_2", "vn_kv": 11.0},
            ],
            "external_grids": [
                {
                    "id": "grid_1",
                    "bus_id": "bus_1",
                    "name": "Grid",
                }
            ],
            "loads": [
                {
                    "id": "load_1",
                    "bus_id": "bus_2",
                    "p_mw": 0.3,
                    "q_mvar": 0.1,
                }
            ],
            "sensor_links": [
                {
                    "sensor_id": "sensor_load_1",
                    "element_type": "load",
                    "element_id": "load_1",
                    "measurement": "p_mw",
                }
            ],
        }

        response = compare_network_payload(network_payload, {"sensor_load_1": 0.35})

        self.assertEqual(response["comparisons"][0]["status"], "topology_issue")
        self.assertIsNone(response["comparisons"][0]["expected"])


if __name__ == "__main__":
    unittest.main()
