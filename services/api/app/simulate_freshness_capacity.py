"""Run offline: python -m app.simulate_freshness_capacity > report.json"""

import json
from app.services.freshness_capacity import CapacityAssumptions, simulate_capacity


def main():
    scenarios = (
        CapacityAssumptions(name="Yuyu assumed serial capacity", seconds_per_capture=6),
        CapacityAssumptions(
            name="SNKRDUNK assumed singleton capacity",
            seconds_per_capture=20,
            source_request_limit_per_day=20000,
        ),
        CapacityAssumptions(
            name="Yuyu assumed constrained source budget",
            seconds_per_capture=6,
            source_request_limit_per_day=10000,
        ),
    )
    print(
        json.dumps(
            [simulate_capacity(scenario) for scenario in scenarios],
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
