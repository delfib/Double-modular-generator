import sys

from xml_parser import parse_fault_model
from smv_utils import get_module_text, strip_main_module, load_smv, save_smv

from injectors import create_injector

from builders import (build_extended_queue, build_extended_wrapper, build_sync_module, 
                      transform_R_client, transform_R_server, transform_RR_client, transform_RR_server, transform_RRA_client, transform_RRA_server)


class FaultInjectionEngine:
    """
    Handles the full fault injection pipeline:

    1. Extract nominal modules
    2. Build QueueExtended
    3. Build ClientExtended
    4. Build ServerExtended
    5. Inject faults where requested
    6. Build Extended wrapper
    7. Build Sync module
    8. Assemble final model
    """
    def __init__(self, fault_model):
        self.fault_model = fault_model

    def _apply_protocol_transform(self, module_text, module_name, redundancy, protocol_type):
        if redundancy <= 1:
            return module_text

        if protocol_type == "R":
            if module_name == "Client":
                return transform_R_client(module_text, redundancy)

            return transform_R_server(module_text)

        elif protocol_type == "RR":

            if module_name == "Client":
                return transform_RR_client(module_text, redundancy)

            return transform_RR_server(module_text)

        elif protocol_type == "RRA":

            if module_name == "Client":
                return transform_RRA_client(module_text, redundancy)

            return transform_RRA_server(module_text, redundancy)

        return module_text

    def generate(self, smv_content):

        protocol_type = self.fault_model.protocol_type

        client_cfg = self.fault_model.modules.get("Client")
        server_cfg = self.fault_model.modules.get("Server")

        client_n = (
            client_cfg.redundancy
            if client_cfg
            else 1
        )

        server_n = (
            server_cfg.redundancy
            if server_cfg
            else 1
        )

        #
        # Extract nominal modules
        #

        client_text = get_module_text(
            smv_content,
            "Client",
        )

        server_text = get_module_text(
            smv_content,
            "Server",
        )

        queue_text = get_module_text(
            smv_content,
            "Queue",
        )

        wrapper_text = get_module_text(
            smv_content,
            "Nominal",
        )

        #
        # Build extended queue
        #

        extended_queue = build_extended_queue(
            queue_text,
            client_n,
            server_n,
            protocol_type,
        )

        #
        # Build ClientExtended
        #

        extended_client = client_text

        if client_n > 1:

            extended_client = self._apply_protocol_transform(
                extended_client,
                "Client",
                client_n,
                protocol_type,
            )

        #
        # Inject client faults
        #

        if client_cfg and client_cfg.faults:

            client_injector = create_injector(
                client_cfg.faults
            )

            extended_client = (
                client_injector
                .build_extended_module_with_faults(
                    extended_client,
                    "Client",
                    "ClientExtended",
                    client_n,
                )
            )

        #
        # Build ServerExtended
        #

        extended_server = server_text

        if server_n > 1:

            extended_server = self._apply_protocol_transform(
                extended_server,
                "Server",
                server_n,
                protocol_type,
            )

        #
        # Inject server faults
        #

        if server_cfg and server_cfg.faults:

            server_injector = create_injector(
                server_cfg.faults
            )

            extended_server = (
                server_injector
                .build_extended_module_with_faults(
                    extended_server,
                    "Server",
                    "ServerExtended",
                    server_n,
                )
            )

        # Build wrapper
        extended_wrapper = (build_extended_wrapper(wrapper_text, client_n, server_n, protocol_type))
        
        # 5. Build Sync + main (with properties) modules 
        sync_main = build_sync_module(client_n, server_n, properties=self.fault_model.properties)

        # 6. Assemble final SMV file
        nominal_base = strip_main_module(smv_content)

        parts = [nominal_base, extended_queue.rstrip(), extended_client.rstrip(), extended_server.rstrip(), extended_wrapper.rstrip(), sync_main]

        return "\n\n\n".join(parts)


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 fault_injector.py <input.smv> <faults.xml> <output.smv>")
        sys.exit(1)

    input_smv = sys.argv[1]
    faults_xml = sys.argv[2]
    output_smv = sys.argv[3]

    print("=" * 60)
    print("SMV Fault Injection Tool")
    print("=" * 60)

    print(f"\n[1] Parsing fault specification: {faults_xml}")
    fault_model = parse_fault_model(faults_xml)

    print(f"\n[2] Loading SMV model: {input_smv}")
    smv_content = load_smv(input_smv)

    print(f"\n[3] Initializing fault injection engine")
    engine = FaultInjectionEngine(fault_model)

    print(f"\n[4] Generating extended + sync model")
    result = engine.generate(smv_content)

    print(f"\n[5] Saving output: {output_smv}")
    save_smv(output_smv, result)

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()