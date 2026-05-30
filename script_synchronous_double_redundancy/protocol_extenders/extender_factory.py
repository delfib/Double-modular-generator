from protocol_extenders.r_extender import RExtender
from protocol_extenders.rr_extender import RRExtender
from protocol_extenders.rra_extender import RRAExtender

def create_extender(protocol_type):
    """Protocol Extender Factory that returns the correct protocol extender."""
    protocol_type = protocol_type.upper()

    if protocol_type == "R":
        return RExtender()

    if protocol_type == "RR":
        return RRExtender()

    if protocol_type == "RRA":
        return RRAExtender()

    raise ValueError(f"Unsupported protocol type '{protocol_type}'")