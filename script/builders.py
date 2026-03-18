import re


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _array_bound(redundancy):
    return f"0..{redundancy - 1}"


def _replace_module_name(text, old_name, new_name):
    return re.sub(rf'MODULE\s+{re.escape(old_name)}\s*\(', f'MODULE {new_name}(', text)


def _strip_to_fairness(text):
    """Strip everything after FAIRNESS running (avoids picking up trailing modules)."""
    return re.sub(r'(FAIRNESS\s*\n\s*running\s*\n).*', r'\1', text, flags=re.DOTALL)


def build_extended_queue_R(queue_text, redundancy, target_module):
    """
    Clone the single Queue module, rename it to QueueExtended, and expand
    either the producer side (Client target) or the consumer side (Server
    target) into an array of toggle slots.
    """
    text = _strip_to_fairness(queue_text)

    is_server_target = target_module.lower() != 'client'

    # Decide which side becomes the array
    if is_server_target:
        # Rename module + replace the server_toggle param with an array param
        text = _replace_module_name(text, 'Queue', 'QueueExtended')
        text = re.sub(
            r'MODULE\s+QueueExtended\(([^,]+),\s*([^,]+),\s*([^)]+)\)',
            r'MODULE QueueExtended(\1, \2, server_toggles)',
            text
        )
        array_side   = 'server'
        scalar_param = 'server_toggle'
        array_param  = 'server_toggles'
    else:
        # Rename module + replace the client_toggle param with an array param
        text = _replace_module_name(text, 'Queue', 'QueueExtended')
        text = re.sub(
            r'MODULE\s+QueueExtended\(([^,]+),\s*([^,]+),\s*([^)]+)\)',
            r'MODULE QueueExtended(\1, client_toggles, \3)',
            text
        )
        array_side   = 'client'
        scalar_param = 'client_toggle'
        array_param  = 'client_toggles'

    n = redundancy
    array_bound = _array_bound(n)

    # Replace last_<side>_toggle boolean VAR with an array
    text = re.sub(
        rf'last_{array_side}_toggle\s*:\s*boolean;',
        f'last_{array_side}_toggle : array {array_bound} of boolean;',
        text
    )

    # Replace single init with per-slot inits
    init_slots = '\n'.join(
        f'    init(last_{array_side}_toggle[{i}]) := FALSE;' for i in range(n)
    )
    text = re.sub(
        rf'init\(last_{array_side}_toggle\)\s*:=\s*FALSE;',
        init_slots,
        text
    )

    # For the server side: replace next(head) with multi-slot case
    # For the client side: replace next(tail) with multi-slot case
    pointer = 'head' if is_server_target else 'tail'
    pointer_cases = '\n'.join(
        f'        ({array_param}[{i}] != last_{array_side}_toggle[{i}]) : ({pointer} + 1) mod Q_SIZE;'
        for i in range(n)
    )
    text = re.sub(
        rf'next\({pointer}\)\s*:=\s*case.*?esac;',
        f'next({pointer}) := case\n{pointer_cases}\n        TRUE : {pointer};\n    esac;',
        text,
        flags=re.DOTALL
    )

    # Replace next(last_<side>_toggle) with per-slot nexts
    next_slots = '\n\n'.join(
        f'    next(last_{array_side}_toggle[{i}]) := case\n'
        f'        ({array_param}[{i}] != last_{array_side}_toggle[{i}]) : {array_param}[{i}];\n'
        f'        TRUE : last_{array_side}_toggle[{i}];\n'
        f'    esac;'
        for i in range(n)
    )
    text = re.sub(
        rf'next\(last_{array_side}_toggle\)\s*:=\s*case.*?esac;',
        next_slots,
        text,
        flags=re.DOTALL
    )

    return text


def build_extended_queue_RR(queue_text, redundancy):
    """
    Build a single unified QueueExtended module for the RR protocol where
    BOTH the producer and consumer sides are extended to arrays of size n.
    """
    text = _strip_to_fairness(queue_text)

    n = redundancy
    array_bound = _array_bound(n)

    # Rename module and replace both scalar toggle params with array params
    text = _replace_module_name(text, 'Queue', 'QueueExtended')
    text = re.sub(
        r'MODULE\s+QueueExtended\(([^,]+),\s*([^,]+),\s*([^)]+)\)',
        r'MODULE QueueExtended(\1, producer_toggles, consumer_toggles)',
        text
    )

    # Replace both last_*_toggle boolean VARs with arrays
    for side in ('producer', 'consumer'):
        text = re.sub(
            rf'last_{side}_toggle\s*:\s*boolean;',
            f'last_{side}_toggle : array {array_bound} of boolean;',
            text
        )

    # Replace single inits with per-slot inits for both sides
    for side in ('producer', 'consumer'):
        init_slots = '\n'.join(
            f'    init(last_{side}_toggle[{i}]) := FALSE;' for i in range(n)
        )
        text = re.sub(
            rf'init\(last_{side}_toggle\)\s*:=\s*FALSE;',
            init_slots,
            text
        )

    # Replace next(tail) — driven by producer_toggles array
    tail_cases = '\n'.join(
        f'        (producer_toggles[{i}] != last_producer_toggle[{i}]) : (tail + 1) mod Q_SIZE;'
        for i in range(n)
    )
    text = re.sub(
        r'next\(tail\)\s*:=\s*case.*?esac;',
        f'next(tail) := case\n{tail_cases}\n        TRUE : tail;\n    esac;',
        text,
        flags=re.DOTALL
    )

    # Replace next(head) — driven by consumer_toggles array
    head_cases = '\n'.join(
        f'        (consumer_toggles[{i}] != last_consumer_toggle[{i}]) : (head + 1) mod Q_SIZE;'
        for i in range(n)
    )
    text = re.sub(
        r'next\(head\)\s*:=\s*case.*?esac;',
        f'next(head) := case\n{head_cases}\n        TRUE : head;\n    esac;',
        text,
        flags=re.DOTALL
    )

    # Replace next(last_producer_toggle) with per-slot nexts
    prod_next_slots = '\n\n'.join(
        f'    next(last_producer_toggle[{i}]) := case\n'
        f'        (producer_toggles[{i}] != last_producer_toggle[{i}]) : producer_toggles[{i}];\n'
        f'        TRUE : last_producer_toggle[{i}];\n'
        f'    esac;'
        for i in range(n)
    )
    text = re.sub(
        r'next\(last_producer_toggle\)\s*:=\s*case.*?esac;',
        prod_next_slots,
        text,
        flags=re.DOTALL
    )

    # Replace next(last_consumer_toggle) with per-slot nexts
    cons_next_slots = '\n\n'.join(
        f'    next(last_consumer_toggle[{i}]) := case\n'
        f'        (consumer_toggles[{i}] != last_consumer_toggle[{i}]) : consumer_toggles[{i}];\n'
        f'        TRUE : last_consumer_toggle[{i}];\n'
        f'    esac;'
        for i in range(n)
    )
    text = re.sub(
        r'next\(last_consumer_toggle\)\s*:=\s*case.*?esac;',
        cons_next_slots,
        text,
        flags=re.DOTALL
    )

    # Add the request_consumed DEFINE if not already present
    if 'request_consumed' not in text:
        consumed_def = (
            '    request_consumed := '
            + ' | '.join(
                f'last_consumer_toggle[{i}] != consumer_toggles[{i}]'
                for i in range(n)
            )
            + ';\n'
        )
        text = re.sub(
            r'(DEFINE\s*\n)',
            r'\1' + consumed_def,
            text
        )

    return text


def build_extended_wrapper_R(nominal_wrapper_text, target_module, redundancy):
    """
    Clone the Nominal wrapper for the R protocol, rename it to Extended, and
    replace the single target instance with `redundancy` Extended instances
    plus the shared toggles array.
    """
    text = nominal_wrapper_text

    # Keep only up to the last ";" (drops any trailing MODULE main or comments)
    last_semi = text.rfind(';')
    if last_semi != -1:
        text = text[:last_semi + 1] + '\n'

    # Rename wrapper module
    text = re.sub(r'MODULE\s+Nominal\s*\(\)', 'MODULE Extended()', text)

    n        = redundancy

    # Locate the original target instance line
    instance_pattern = rf'(\s*)(\w+)\s*:\s*process\s+{re.escape(target_module)}\(([^)]*)\);'
    match = re.search(instance_pattern, text)
    if not match:
        raise ValueError(f"Could not find instance of {target_module} in wrapper")

    indent = match.group(1)
    params = match.group(3)

    # Build Extended instances, passing their index as the last argument
    instance_lines = []
    for i in range(1, n + 1):
        instance_lines.append(
            f"{indent}{target_module.lower()}{i} : process {target_module}Extended({params}, {i-1});"
        )

    # Determine which queue side is widened and build toggle arrays accordingly
    is_server_target = target_module.lower() != 'client'

    if is_server_target:
        # server_toggles array fed from each server instance's request_toggle
        array_name   = 'server_toggles'
        toggle_field = 'request_toggle'
        queue_param  = 'server_toggles'   # replaces the last param in Queue(...)
    else:
        # client_toggles array fed from each client instance's request_toggle
        array_name   = 'client_toggles'
        toggle_field = 'request_toggle'
        queue_param  = 'client_toggles'   # replaces the first param in Queue(...)

    bridge_lines = [
        f"{indent}{array_name} : array 0..{n-1} of boolean;"
    ]

    # Locate and update the Queue instance line
    queue_pattern = r'(\s*)(\w+)\s*:\s*process\s+Queue\(([^)]*)\);'
    queue_match = re.search(queue_pattern, text)
    if not queue_match:
        raise ValueError("Could not find Queue instance in wrapper")

    q_indent    = queue_match.group(1)
    q_params    = queue_match.group(3)
    q_param_list = [p.strip() for p in q_params.split(',')]

    if is_server_target:
        q_param_list[-1] = queue_param   # replace server_toggle with server_toggles
    else:
        q_param_list[1]  = queue_param   # replace client_toggle with client_toggles

    new_queue_line = (
        f"{q_indent}queue : process QueueExtended("
        + ', '.join(q_param_list)
        + ");"
    )

    # Build ASSIGN block wiring toggle arrays to instance toggle fields
    assign_lines = '\n'.join(
        f"    {array_name}[{i}] := {target_module.lower()}{i+1}.{toggle_field};"
        for i in range(n)
    )

    # Splice everything together
    new_instance_block = '\n'.join(bridge_lines + instance_lines)

    # Replace original target instance with the new block
    text = text[:match.start()] + new_instance_block + text[match.end():]

    # Replace Queue with QueueExtended
    text = re.sub(queue_pattern, new_queue_line, text)

    # Add or extend ASSIGN block
    if 'ASSIGN' not in text:
        text = text.rstrip() + f'\n\nASSIGN\n{assign_lines}\n'
    else:
        text = re.sub(r'(ASSIGN\s*\n)', r'\1' + assign_lines + '\n', text)

    return text


def build_extended_wrapper_RR(nominal_wrapper_text, target_module, redundancy):
    """
    Clone the Nominal wrapper for the RR protocol, rename it to Extended, and
    replace the single target instance with `redundancy` Extended instances.
    """
    text = nominal_wrapper_text

    # Keep only up to the last ";" (drops any trailing MODULE main or comments)
    last_semi = text.rfind(';')
    if last_semi != -1:
        text = text[:last_semi + 1] + '\n'

    # Rename wrapper module
    text = re.sub(r'MODULE\s+Nominal\s*\(\)', 'MODULE Extended()', text)

    n                = redundancy
    is_server_target = target_module.lower() != 'client'
    
    # Locate the original target instance line
    instance_pattern = rf'(\s*)(\w+)\s*:\s*process\s+{re.escape(target_module)}\(([^)]*)\);'
    match = re.search(instance_pattern, text)
    if not match:
        raise ValueError(f"Could not find instance of {target_module} in wrapper")

    indent = match.group(1)
    params = match.group(3)   # e.g. "request_queue, ack_queue"

    # Build Extended instances — each gets its index as the last argument
    instance_lines = []
    for i in range(1, n + 1):
        instance_lines.append(
            f"{indent}{target_module.lower()}{i} : process {target_module}Extended({params}, {i-1});"
        )

    
    # Declare the four bridge arrays (prod/cons for each queue)
    bridge_lines = [
        f"{indent}request_prod_toggles : array 0..{n-1} of boolean;",
        f"{indent}request_cons_toggles : array 0..{n-1} of boolean;",
        f"{indent}ack_prod_toggles     : array 0..{n-1} of boolean;",
        f"{indent}ack_cons_toggles     : array 0..{n-1} of boolean;",
    ]

    
    # Build ASSIGN wiring
    assign_lines = []

    # Find the non-target instance in the wrapper and replace its module type
    # with the patched renamed version (ClientExtended).
    non_target       = 'client' if is_server_target else 'server'
    non_target_ext   = f'{non_target.capitalize()}Extended'
    non_target_pattern = rf'(\s*\w+\s*:\s*process\s+){re.escape(non_target.capitalize())}\(([^)]*)\);'
    non_target_match   = re.search(non_target_pattern, text, re.IGNORECASE)
    if non_target_match:
        non_target_inst = re.search(rf'(\w+)\s*:\s*process\s+{re.escape(non_target.capitalize())}\(', text, re.IGNORECASE).group(1)
        new_non_target_line = non_target_match.group(1) + non_target_ext + '(' + non_target_match.group(2) + ');'
        text = text[:non_target_match.start()] + new_non_target_line + text[non_target_match.end():]
    else:
        non_target_inst = non_target

    if is_server_target:
        # request_prod: slot 0 = client.request_toggle, rest = FALSE (dummy)
        assign_lines.append(f"    request_prod_toggles[0] := {non_target_inst}.request_toggle;")
        for i in range(1, n):
            assign_lines.append(f"    request_prod_toggles[{i}] := FALSE;   -- dummy, stays FALSE forever")
        # request_cons: one slot per server
        for i in range(n):
            assign_lines.append(f"    request_cons_toggles[{i}] := server{i+1}.request_toggle;")
        # ack_prod: one slot per server
        for i in range(n):
            assign_lines.append(f"    ack_prod_toggles[{i}] := server{i+1}.ack_toggle;")
        # ack_cons: slot 0 = client.ack_toggle, rest = FALSE (dummy)
        assign_lines.append(f"    ack_cons_toggles[0] := {non_target_inst}.ack_toggle;")
        for i in range(1, n):
            assign_lines.append(f"    ack_cons_toggles[{i}] := FALSE;   -- dummy, stays FALSE forever")
    else:
        # request_prod: one slot per client
        for i in range(n):
            assign_lines.append(f"    request_prod_toggles[{i}] := client{i+1}.request_toggle;")
        # request_cons: slot 0 = server.request_toggle, rest = FALSE (dummy)
        assign_lines.append(f"    request_cons_toggles[0] := {non_target_inst}.request_toggle;")
        for i in range(1, n):
            assign_lines.append(f"    request_cons_toggles[{i}] := FALSE;   -- dummy, stays FALSE forever")
        # ack_prod: slot 0 = server.ack_toggle, rest = FALSE (dummy)
        assign_lines.append(f"    ack_prod_toggles[0] := {non_target_inst}.ack_toggle;")
        for i in range(1, n):
            assign_lines.append(f"    ack_prod_toggles[{i}] := FALSE;   -- dummy, stays FALSE forever")
        # ack_cons: one slot per client
        for i in range(n):
            assign_lines.append(f"    ack_cons_toggles[{i}] := client{i+1}.ack_toggle;")

    assign_block = '\n'.join(assign_lines)

    # Replace both Queue instances with QueueExtended, passing the four arrays
    req_queue_pattern = r'(\s*\w+\s*:\s*process\s+Queue\(([^)]*)\);)'
    queue_matches = list(re.finditer(req_queue_pattern, text))
    if len(queue_matches) < 2:
        raise ValueError("Could not find two Queue instances in RR wrapper")

    # First match = request_queue, second match = ack_queue
    req_match = queue_matches[0]
    ack_match = queue_matches[1]

    new_req_queue = (
        req_match.group(0).split(':')[0]
        + ': process QueueExtended(Q_SIZE, request_prod_toggles, request_cons_toggles);'
    )
    new_ack_queue = (
        ack_match.group(0).split(':')[0]
        + ': process QueueExtended(Q_SIZE, ack_prod_toggles, ack_cons_toggles);'
    )

    # Apply back-to-front to preserve string offsets
    text = text[:ack_match.start()] + new_ack_queue + text[ack_match.end():]
    text = text[:req_match.start()] + new_req_queue + text[req_match.end():]

    match = re.search(instance_pattern, text)
    if not match:
        raise ValueError(
            f"Could not re-find instance of {target_module} in wrapper after queue substitution"
        )

    new_instance_block = '\n'.join(bridge_lines + instance_lines)
    text = text[:match.start()] + new_instance_block + text[match.end():]

    # Add or extend the ASSIGN block
    if 'ASSIGN' not in text:
        text = text.rstrip() + f'\n\nASSIGN\n{assign_block}\n'
    else:
        text = re.sub(r'(ASSIGN\s*\n)', r'\1' + assign_block + '\n', text)

    return text

# ------------------------------------------------
# Non-target module patcher — RR protocol only
# ------------------------------------------------
def patch_non_target_module_RR(module_text, original_name, new_name):
    """Produce a renamed copy of the non-target module to use inside Extended()"""
    # Rename the MODULE declaration
    text = re.sub(
        rf'MODULE\s+{re.escape(original_name)}\s*\(',
        f'MODULE {new_name}(',
        module_text
    )

    # Index all unindexed toggle references to slot [0]
    text = re.sub(
        r'(\w+\.last_\w+_toggle)(?!\[)',
        r'\1[0]',
        text
    )

    return text


def build_extended_queue(queue_text, redundancy, target_module, protocol_type):
    """Invoke the correct queue-extension builder based on protocol type."""
    if protocol_type == 'R':
        return [build_extended_queue_R(queue_text, redundancy, target_module)]
    elif protocol_type == 'RR':
        return [build_extended_queue_RR(queue_text, redundancy)]
    else:
        raise ValueError(f"Unknown protocol type: '{protocol_type}'")


def build_extended_wrapper(nominal_wrapper_text, target_module, redundancy, protocol_type):
    """Invoke the correct wrapper builder based on protocol type."""
    if protocol_type == 'R':
        return build_extended_wrapper_R(nominal_wrapper_text, target_module, redundancy)
    elif protocol_type == 'RR':
        return build_extended_wrapper_RR(nominal_wrapper_text, target_module, redundancy)
    else:
        raise ValueError(f"Unknown protocol type: '{protocol_type}'")


def build_sync_module(target_module, redundancy, properties=None):
    """
    Build the Sync module followed by the top-level MODULE main.
    Any properties from the fault spec are injected into Sync as SPEC statements.
    """
    properties_block = ""
    if properties:
        lines = []
        for prop in properties:
            if prop.comment:
                lines.append(f"-- {prop.comment}")
            lines.append(f"SPEC AG {prop.spec}\n")
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