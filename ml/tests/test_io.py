import unittest
from pathlib import Path

from innothon_sim.io import load_network_definition


class LoadNetworkDefinitionTests(unittest.TestCase):
    def test_load_network_definition(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / "sample_data"
            / "simple_radial_network.json"
        )
        network = load_network_definition(path)

        self.assertEqual(network.network.name, "simple-radial-demo")
        self.assertEqual(len(network.buses), 2)
        self.assertEqual(network.lines[0].id, "line_1")
        self.assertEqual(network.loads[0].bus_id, "bus_load")


if __name__ == "__main__":
    unittest.main()
