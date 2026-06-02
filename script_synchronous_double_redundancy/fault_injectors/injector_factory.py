from fault_injectors.stuck_at_injector import StuckAtInjector
from fault_injectors.byzantine_injector import ByzantineInjector

def create_injector(faults):

    if not faults:
        raise ValueError("No faults provided")

    fault_type = faults[0].type

    if fault_type == "stuck-at":
        return StuckAtInjector(faults)

    if fault_type == "byzantine":
        return ByzantineInjector(faults)

    raise ValueError(f"Unsupported fault type '{fault_type}'")