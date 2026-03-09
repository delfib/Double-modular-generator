import sys
import re
from xml_parser import parse_fault_model
from smv_utils import load_smv, save_smv, find_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_module_text(smv_content, module_name):
    start, end = find_module(smv_content, module_name)
    lines = smv_content.splitlines(keepends=True)
    return ''.join(lines[start:end])


def replace_module_text(smv_content, module_name, new_text):
    start, end = find_module(smv_content, module_name)
    lines = smv_content.splitlines(keepends=True)
    return ''.join(lines[:start]) + new_text + ''.join(lines[end:])

class StuckAtInjector:
    """Handles 'stuck-at' fault injection into a module."""    
    def __init__(self, faults):
        self.faults = faults

    def get_fault_mode_enum(self):
        """Generate the fault_mode enum values"""
        modes = ['none']
        for fault in self.faults:
            mode_name = f"stuck_{fault.value}"
            if mode_name not in modes:
                modes.append(mode_name)
        return ', '.join(modes)

    def build_extended_module(self, module_text, original_name, new_name, redundancy):
        """
        Clone the target module, rename it, inject faults, add server_id param.
        For redundancy > 1 the server needs a server_id to index its queue slot.
        """
        text = module_text

        # Rename module declaration
        text = re.sub(
            rf'MODULE\s+{re.escape(original_name)}\s*\(',
            f'MODULE {new_name}(',
            text
        )

        # Add server_id parameter to module signature if redundancy > 1
        if redundancy > 1:
            text = re.sub(
                rf'MODULE\s+{re.escape(new_name)}\(([^)]*)\)',
                lambda m: f'MODULE {new_name}({m.group(1)}, server_id)',
                text
            )

        # Inject fault_mode VAR
        text = self._inject_fault_mode_var(text)

        # Inject fault_mode ASSIGN (init + next)
        text = self._inject_fault_mode_assign(text)

        # Inject fault conditions into next(server_state)
        text = self._inject_fault_conditions(text)

        # Protect toggle logic
        text = self._protect_toggle_logic(text)

        # If redundancy > 1, update the queue reference to use server_id slot
        if redundancy > 1:
            text = self._update_queue_references(text)

        return text

    def _inject_fault_mode_var(self, text):
        enum_vals = self.get_fault_mode_enum()
        fault_decl = f"    fault_mode : {{{enum_vals}}};\n"
        # Insert after VAR line
        return re.sub(r'(VAR\s*\n)', r'\1' + fault_decl, text)

    def _inject_fault_mode_assign(self, text):
        enum_vals = self.get_fault_mode_enum()
        init_line = "    init(fault_mode) := none;\n\n"
        next_block = (
            f"    next(fault_mode) :=\n"
            f"        case\n"
            f"            fault_mode = none : {{{enum_vals}}};\n"
            f"            TRUE              : fault_mode;\n"
            f"        esac;\n\n"
        )
        # Insert init after ASSIGN line
        text = re.sub(r'(ASSIGN\s*\n)', r'\1' + init_line, text)
        # Insert next(fault_mode) before the first next() assignment
        text = re.sub(r'(    next\()', next_block + r'    next(', text, count=1)
        return text

    def _inject_fault_conditions(self, text):
        faults_by_var = {}
        for fault in self.faults:
            faults_by_var.setdefault(fault.variable, []).append(fault)

        for variable, var_faults in faults_by_var.items():
            pattern = rf'(next\({re.escape(variable)}\)\s*:=\s*case)'
            match = re.search(pattern, text)
            if not match:
                raise ValueError(f"Could not find next({variable}) assignment")

            fault_lines = "\n"
            for fault in var_faults:
                mode_name = f"stuck_{fault.value}"
                fault_lines += f"        fault_mode = {mode_name} : {fault.value};\n"

            insert_pos = match.end()
            text = text[:insert_pos] + fault_lines + text[insert_pos:]

        return text

    def _protect_toggle_logic(self, text):
        """Add fault_mode = none guard to the toggle condition."""
        pattern = r'(next\(request_toggle\)\s*:=\s*case)(.*?)(esac;)'
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            return text

        cases = match.group(2)
        new_cases = []
        for line in cases.split('\n'):
            if '!request_toggle' in line and ':' in line:
                parts = line.split(':', 1)
                condition = parts[0].strip()
                action = parts[1].strip()
                new_cases.append(
                    f"        fault_mode = none &\n"
                    f"        {condition} : {action}\n"
                )
            else:
                new_cases.append(line + '\n')

        new_block = match.group(1) + ''.join(new_cases) + '    ' + match.group(3)
        return text[:match.start()] + new_block + text[match.end():]

    def _update_queue_references(self, text):
        """
        Replace queue.last_server_toggle with queue.last_server_toggle[server_id]
        so each server checks its own slot.
        """
        text = re.sub(
            r'queue\.last_server_toggle(?!\[)',
            'queue.last_server_toggle[server_id]',
            text
        )
        return text

def build_extended_queue(queue_text, redundancy):
    """
    Clone Queue module, rename to QueueExtended, replace last_server_toggle
    with array 0..(redundancy-1), add server_toggles param.
    """
    # Strip everything after FAIRNESS running to avoid picking up trailing comments
    text = re.sub(r'(FAIRNESS\s*\n\s*running\s*\n).*', r'\1', queue_text, flags=re.DOTALL)

    # Rename
    text = re.sub(r'MODULE\s+Queue\s*\(', 'MODULE QueueExtended(', text)

    # Replace server_toggle param with server_toggles in signature
    text = re.sub(
        r'MODULE\s+QueueExtended\(([^,]+),\s*([^,]+),\s*([^)]+)\)',
        r'MODULE QueueExtended(\1, \2, server_toggles)',
        text
    )

    n = redundancy
    array_bound = f"0..{n - 1}"

    # Replace last_server_toggle VAR with array
    text = re.sub(
        r'last_server_toggle\s*:\s*boolean;',
        f'last_server_toggle : array {array_bound} of boolean;',
        text
    )

    # Replace init(last_server_toggle) with per-slot inits
    init_slots = '\n'.join(
        f'    init(last_server_toggle[{i}]) := FALSE;' for i in range(n)
    )
    text = re.sub(
        r'init\(last_server_toggle\)\s*:=\s*FALSE;',
        init_slots,
        text
    )

    # Replace next(head) case block with array checks
    head_cases = '\n'.join(
        f'        (server_toggles[{i}] != last_server_toggle[{i}]) : (head + 1) mod Q_SIZE;'
        for i in range(n)
    )
    text = re.sub(
        r'next\(head\)\s*:=\s*case.*?esac;',
        f'next(head) := case\n{head_cases}\n        TRUE : head;\n    esac;',
        text,
        flags=re.DOTALL
    )

    # Replace next(last_server_toggle) with per-slot nexts
    next_slots = '\n\n'.join(
        f'    next(last_server_toggle[{i}]) := case\n'
        f'        (server_toggles[{i}] != last_server_toggle[{i}]) : server_toggles[{i}];\n'
        f'        TRUE : last_server_toggle[{i}];\n'
        f'    esac;'
        for i in range(n)
    )
    text = re.sub(
        r'next\(last_server_toggle\)\s*:=\s*case.*?esac;',
        next_slots,
        text,
        flags=re.DOTALL
    )

    return text


def build_extended_wrapper(nominal_wrapper_text, target_module, redundancy, n_values):
    """
    Clone NominalR wrapper, rename to ExtendedR
    """
    # Strip trailing content after the last semicolon in the VAR block
    # (removes any MODULE main or comments that follow NominalR)
    text = nominal_wrapper_text

    # Keep only up to and including the last ";" that closes the queue declaration
    last_semi = text.rfind(';')
    if last_semi != -1:
        text = text[:last_semi + 1] + '\n'

    # Rename
    text = re.sub(r'MODULE\s+NominalR\s*\(\)', 'MODULE ExtendedR()', text)

    # Add N-value DEFINEs if provided
    if n_values:
        define_lines = '\n'.join(
            f'    N{i+1} := {n_values[i]};' for i in range(redundancy)
        )
        text = re.sub(r'(DEFINE\s*\n)', r'\1' + define_lines + '\n', text)

    # Find and replace the server instance line
    # Match: "    server : process Server(queue);"
    server_pattern = rf'(\s*)(\w+)\s*:\s*process\s+{re.escape(target_module)}\(([^)]*)\);'
    match = re.search(server_pattern, text)

    if not match:
        raise ValueError(f"Could not find instance of {target_module} in wrapper")

    indent = match.group(1)
    params = match.group(3)  # e.g. "queue"

    # Build server instances
    server_lines = []
    for i in range(1, redundancy + 1):
        if n_values:
            server_lines.append(
                f"{indent}server{i} : process ServerExtended({params}, {i-1}, N{i});"
            )
        else:
            server_lines.append(
                f"{indent}server{i} : process ServerExtended({params}, {i-1});"
            )

    # Build array declaration
    bridge_lines = [
        f"{indent}server_toggles : array 0..{redundancy-1} of boolean;"
    ]

    # Build queue replacement (QueueExtended with server_toggles)
    queue_pattern = r'(\s*)(\w+)\s*:\s*process\s+Queue\(([^)]*)\);'
    queue_match = re.search(queue_pattern, text)
    if not queue_match:
        raise ValueError("Could not find Queue instance in wrapper")

    q_indent = queue_match.group(1)
    q_params = queue_match.group(3)

    # Replace last param (server toggle) with server_toggles array
    q_param_list = [p.strip() for p in q_params.split(',')]
    q_param_list[-1] = 'server_toggles'
    new_queue_line = (
        f"{q_indent}queue : process QueueExtended("
        + ', '.join(q_param_list)
        + ");"
    )

    # Build ASSIGN block for array
    assign_lines = '\n'.join(
        f"    server_toggles[{i}] := server{i+1}.request_toggle;"
        for i in range(redundancy)
    )
    assign_block = f"\nASSIGN\n{assign_lines}\n"

    # Replace server instance in text
    new_server_block = '\n'.join(bridge_lines + server_lines)
    text = text[:match.start()] + new_server_block + text[match.end():]

    # Replace queue instance in text
    text = re.sub(queue_pattern, new_queue_line, text)

    # Append ASSIGN block if not already present
    if 'ASSIGN' not in text:
        text = text.rstrip() + '\n' + assign_block + '\n'
    else:
        text = re.sub(r'(ASSIGN\s*\n)', r'\1' + assign_lines + '\n', text)

    return text


def build_sync_module(target_module, redundancy, properties=None):
    """
    Build the Sync module that instantiates both NominalR and ExtendedR.
    """
    properties_block = ""
    if properties:
        lines = []
        for prop in properties:
            if prop.comment:
                lines.append(f"-- {prop.comment}")
            lines.append(f"SPEC {prop.spec}\n")
        properties_block = "\n" + "\n".join(lines)


    sync = (
        f"-- =========================================================\n"
        f"--  Synchronization Module\n"
        f"-- =========================================================\n"
        f"MODULE Sync()\n"
        f"VAR\n"
        f"    nominal  : NominalR();\n"
        f"    extended : ExtendedR();\n"
        f"\n"
        f"\n"
        f"{properties_block}\n"
        f"\n"
        f"\n"
        f"-- =========================================================\n"
        f"--  Main Module\n"
        f"-- =========================================================\n"
        f"MODULE main\n"
        f"VAR\n"
        f"    sync : Sync();\n"
    )
    return sync


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class FaultInjectionEngine:
    def __init__(self, fault_model):
        self.fault_model = fault_model
        self.injector = self._create_injector()

    def _create_injector(self):
        fault_types = set(f.type for f in self.fault_model.faults)
        if fault_types == {'stuck-at'}:
            return StuckAtInjector(self.fault_model.faults)
        raise ValueError(f"Unsupported fault type(s): {fault_types}")

    def generate(self, smv_content):
        n = self.fault_model.redundancy
        target = self.fault_model.target_module

        # --- 1. Get original modules ---
        server_text = get_module_text(smv_content, target)
        queue_text  = get_module_text(smv_content, 'Queue')
        wrapper_text = get_module_text(smv_content, 'NominalR')

        # --- 2. Build extended server ---
        extended_server = self.injector.build_extended_module(
            server_text, target, f'{target}Extended', n
        )

        # --- 3. Build extended queue ---
        extended_queue = build_extended_queue(queue_text, n)

        # --- 4. Build extended wrapper ---
        extended_wrapper = build_extended_wrapper(wrapper_text, target, n, n_values=None)

        # --- 5. Build sync + main ---
        sync_main = build_sync_module(target, n, properties=self.fault_model.properties)

        # --- 6. Assemble final file ---
        # Strip MODULE main from nominal content — Sync provides the only main.
        # Try with comment header first, fall back to bare MODULE main.
        nominal_without_main = re.sub(
            r'\n*--[^\n]*\n--[^\n]*[Mm]ain[^\n]*\n--[^\n]*\nMODULE main.*',
            '',
            smv_content,
            flags=re.DOTALL
        )
        if 'MODULE main' in nominal_without_main:
            # Fallback: no matching comment header, strip bare MODULE main
            nominal_without_main = re.sub(
                r'\n*MODULE main.*',
                '',
                nominal_without_main,
                flags=re.DOTALL
            )
        nominal_without_main = nominal_without_main.rstrip()

        result = (
            nominal_without_main
            + "\n\n\n"
            + extended_queue.rstrip()
            + "\n\n\n"
            + extended_server.rstrip()
            + "\n\n\n"
            + extended_wrapper.rstrip()
            + "\n\n\n"
            + sync_main
        )

        return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
    print(f"    Target module : {fault_model.target_module}")
    print(f"    Redundancy    : {fault_model.redundancy}")
    print(f"    Faults        : {len(fault_model.faults)}")
    for f in fault_model.faults:
        print(f"      - {f.type} on {f.variable} = {f.value}")

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