import re

# ---------------------------------------------------------------------------
# Extended Queue builder
# ---------------------------------------------------------------------------
def build_extended_queue(queue_text, redundancy):
    """
    Clone the Queue module, rename it to QueueExtended, and replace the single
    server_toggle boolean with an array of toggles.
    """
    # Strip everything after FAIRNESS running (avoids picking up trailing modules)
    text = re.sub(r'(FAIRNESS\s*\n\s*running\s*\n).*', r'\1', queue_text, flags=re.DOTALL)

    # Rename module and replace server_toggle param with server_toggles array param
    text = re.sub(r'MODULE\s+Queue\s*\(', 'MODULE QueueExtended(', text)
    text = re.sub(
        r'MODULE\s+QueueExtended\(([^,]+),\s*([^,]+),\s*([^)]+)\)',
        r'MODULE QueueExtended(\1, \2, server_toggles)',
        text
    )

    n           = redundancy
    array_bound = f"0..{n - 1}"

    # Replace last_server_toggle boolean VAR with an array
    text = re.sub(
        r'last_server_toggle\s*:\s*boolean;',
        f'last_server_toggle : array {array_bound} of boolean;',
        text
    )

    # Replace single init with per-slot inits
    init_slots = '\n'.join(
        f'    init(last_server_toggle[{i}]) := FALSE;' for i in range(n)
    )
    text = re.sub(
        r'init\(last_server_toggle\)\s*:=\s*FALSE;',
        init_slots,
        text
    )

    # Replace next(head) with a case that checks each server's toggle slot
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

# ---------------------------------------------------------------------------
# Extended Wrapper builder
# ---------------------------------------------------------------------------
def build_extended_wrapper(nominal_wrapper_text, target_module, redundancy, n_values):
    """
    Clone the Nominal wrapper, rename it to Extended, and replace the single
    server instance with `redundancy` ServerExtended instances plus the shared
    server_toggles array.
    """
    text = nominal_wrapper_text

    # Keep only up to the last ";" (drops any trailing MODULE main or comments)
    last_semi = text.rfind(';')
    if last_semi != -1:
        text = text[:last_semi + 1] + '\n'

    # Rename wrapper module
    text = re.sub(r'MODULE\s+Nominal\s*\(\)', 'MODULE Extended()', text)

    # Add N-value DEFINEs if provided (used for parameterised N-modular redundancy)
    if n_values:
        define_lines = '\n'.join(
            f'    N{i+1} := {n_values[i]};' for i in range(redundancy)
        )
        text = re.sub(r'(DEFINE\s*\n)', r'\1' + define_lines + '\n', text)

    # Locate the original server instance line  e.g. "    server : process Server(queue);"
    server_pattern = rf'(\s*)(\w+)\s*:\s*process\s+{re.escape(target_module)}\(([^)]*)\);'
    match = re.search(server_pattern, text)
    if not match:
        raise ValueError(f"Could not find instance of {target_module} in wrapper")

    indent = match.group(1)
    params = match.group(3)  # e.g. "queue"

    # Build one ServerExtended instance per redundancy slot
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

    # Declare the server_toggles bridge array
    bridge_lines = [
        f"{indent}server_toggles : array 0..{redundancy-1} of boolean;"
    ]

    # Locate the Queue instance and replace it with QueueExtended(server_toggles)
    queue_pattern = r'(\s*)(\w+)\s*:\s*process\s+Queue\(([^)]*)\);'
    queue_match   = re.search(queue_pattern, text)
    if not queue_match:
        raise ValueError("Could not find Queue instance in wrapper")

    q_indent     = queue_match.group(1)
    q_params     = queue_match.group(3)
    q_param_list = [p.strip() for p in q_params.split(',')]
    q_param_list[-1] = 'server_toggles'   # replace single toggle with array
    new_queue_line = (
        f"{q_indent}queue : process QueueExtended("
        + ', '.join(q_param_list)
        + ");"
    )

    # Build the ASSIGN block that wires each server's toggle into the array
    assign_lines = '\n'.join(
        f"    server_toggles[{i}] := server{i+1}.request_toggle;"
        for i in range(redundancy)
    )
    assign_block = f"\nASSIGN\n{assign_lines}\n"

    # Apply substitutions to the module text
    new_server_block = '\n'.join(bridge_lines + server_lines)
    text = text[:match.start()] + new_server_block + text[match.end():]
    text = re.sub(queue_pattern, new_queue_line, text)

    # Append ASSIGN block if not already present
    if 'ASSIGN' not in text:
        text = text.rstrip() + '\n' + assign_block + '\n'
    else:
        text = re.sub(r'(ASSIGN\s*\n)', r'\1' + assign_lines + '\n', text)

    return text


# ---------------------------------------------------------------------------
# Sync + Main module builder
# ---------------------------------------------------------------------------
def build_sync_module(target_module, redundancy, properties=None):
    """
    Build the Sync module that instantiates both NominalR and ExtendedR side
    by side, followed by the top-level MODULE main.
    Any properties from the fault spec are injected into Sync as SPEC statements.
    """
    # Render property SPEC statements if provided
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
        f"    nominal  : Nominal();\n"
        f"    extended : Extended();\n"
        f"{properties_block}\n"
        f"\n"
        f"-- =========================================================\n"
        f"--  Main Module\n"
        f"-- =========================================================\n"
        f"MODULE main\n"
        f"VAR\n"
        f"    sync : Sync();\n"
    )
    return sync