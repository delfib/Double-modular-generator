import sys
import re

from xml_parser import parse_fault_model
from smv_utils  import load_smv, save_smv, find_module
from injectors  import create_injector
from builders   import build_extended_queues, build_extended_wrapper, build_sync_module


# ---------------------------------------------------------------------------
# SMV module helpers
# ---------------------------------------------------------------------------

def get_module_text(smv_content, module_name):
    """Extract the full text of a named MODULE from an SMV file."""
    start, end = find_module(smv_content, module_name)
    lines = smv_content.splitlines(keepends=True)
    return ''.join(lines[start:end])


def strip_main_module(smv_content):
    """
    Remove MODULE main from the nominal SMV content.
    """
    # Try to strip comment-headed MODULE main block
    result = re.sub(
        r'\n*--[^\n]*\n--[^\n]*[Mm]ain[^\n]*\n--[^\n]*\nMODULE main.*',
        '',
        smv_content,
        flags=re.DOTALL
    )
    # Fallback: bare MODULE main with no matching comment header
    if 'MODULE main' in result:
        result = re.sub(r'\n*MODULE main.*', '', result, flags=re.DOTALL)

    return result.rstrip()


# ---------------------------------------------------------------------------
# Fault injection engine
# ---------------------------------------------------------------------------
class FaultInjectionEngine:
    """
    Orchestrates the full fault injection pipeline:
      1. Extract original modules from the nominal SMV
      2. Build the extended (faulted) target module via the injector
      3. Build the extended queue(s) (array of toggle slots)
      4. Build the extended wrapper
      5. Build the Sync + main module with any SPEC properties
      6. Assemble and return the final SMV file content

    Supports both R (single-queue) and RR (two-queue) protocols, and both
    Server and Client as injection targets.
    """
    def __init__(self, fault_model):
        self.fault_model = fault_model
        self.injector    = create_injector(fault_model.faults)

    def generate(self, smv_content):
        n             = self.fault_model.redundancy
        target        = self.fault_model.target_module
        protocol_type = self.fault_model.protocol_type

        # --- 1. Extract original modules ---
        target_text  = get_module_text(smv_content, target)
        queue_text   = get_module_text(smv_content, 'Queue')
        wrapper_text = get_module_text(smv_content, 'Nominal')

        # --- 2. Build extended (faulted) target module ---
        extended_target = self.injector.build_extended_module_with_faults(
            target_text, target, f'{target}Extended', n
        )

        # --- 3. Build extended queue(s) ---
        # Returns a list: one element for R, two elements for RR
        extended_queues = build_extended_queues(
            queue_text, n, target, protocol_type
        )

        # --- 4. Build extended wrapper ---
        extended_wrapper = build_extended_wrapper(
            wrapper_text, target, n, protocol_type
        )

        # --- 5. Build Sync + main (with properties) ---
        sync_main = build_sync_module(target, n, properties=self.fault_model.properties)

        # --- 6. Assemble final SMV file ---
        nominal_base = strip_main_module(smv_content)

        parts = (
            [nominal_base]
            + [q.rstrip() for q in extended_queues]
            + [extended_target.rstrip(), extended_wrapper.rstrip(), sync_main]
        )

        return '\n\n\n'.join(parts)


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 fault_injector.py <input.smv> <faults.xml> <output.smv>")
        sys.exit(1)

    input_smv  = sys.argv[1]
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