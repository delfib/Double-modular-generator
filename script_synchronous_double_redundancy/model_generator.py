from protocol_extenders.extender_factory import create_extender
from fault_injectors.injector_factory import create_injector

from smv_utils import (get_module_text, strip_main_module)

class ModelGenerator:
    """
    Coordinates the complete model generation pipeline.
        1. Extract nominal modules.
        2. Extend the protocol according to redundancy.
        3. Inject faults into the requested modules.
        4. Assemble the final SMV model.
    """
    def __init__(self, fault_model):
        self.fault_model = fault_model


    def generate(self, smv_content):
        """Receives the nominal SMV model and returns the fully generated model."""

        modules = self._extract_modules(smv_content)
        extender = create_extender(self.fault_model.protocol_type)
        modules = extender.extend(modules, self.fault_model)
        modules = self._inject_faults(modules)

        return self._assemble_model(smv_content, modules)


    def _extract_modules(self, smv_content):
        """Extract all nominal modules from the SMV file."""
        return {
            "queue": get_module_text(smv_content, "Queue"),
            "client": get_module_text(smv_content, "Client"),
            "server": get_module_text(smv_content, "Server"),
            "wrapper": get_module_text(smv_content, "Nominal")
        }


    def _inject_faults(self, modules):
        """Inject faults into ClientExtended and/or ServerExtended when requested."""
        client_cfg = self.fault_model.modules.get("Client")
        server_cfg = self.fault_model.modules.get("Server")

        if client_cfg and client_cfg.faults:
            injector = create_injector(client_cfg.faults)
            modules["client"] = injector.inject(module_text=modules["client"], module_name="Client", 
                                                redundancy=client_cfg.redundancy)
        
        if server_cfg and server_cfg.faults:
            injector = create_injector(server_cfg.faults)
            modules["server"] = injector.inject(module_text=modules["server"],
                module_name="Server", redundancy=server_cfg.redundancy)

        return modules


    def _assemble_model(self, original_smv, modules):
        """Assemble the final generated SMV model."""
        nominal_base = strip_main_module(original_smv)

        parts = [
            nominal_base,
            modules["queue"].rstrip(),
            modules["client"].rstrip(),
            modules["server"].rstrip(),
            modules["wrapper"].rstrip(),
            modules["sync"].rstrip()
        ]

        return "\n\n\n".join(parts)