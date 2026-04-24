import re

from smv_utils import get_module_text


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


def build_extended_queue_RR(queue_text, redundancy, target_module):
    """
    Build a single unified QueueExtended module for the RR protocol where
    BOTH the producer and consumer sides are extended to arrays of size n.
    """
    text = _strip_to_fairness(queue_text)
    is_client_target = target_module.lower() == 'client'

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

    if is_client_target and n > 1:
        # Add producer_id array
        producer_enum = ', '.join([f'clt{i}' for i in range(n)])
        text = re.sub(
            r'(VAR\s*\n)',
            r'\1' + f'    producer_id : array 0..{3} of {{none, {producer_enum}}};\n',
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

    if is_client_target and n > 1:
        # Initialize producer_id
        init_pid = '\n'.join(
            f'    init(producer_id[{i}]) := none;' for i in range(4)
        )
        text = re.sub(
            r'(init\(tail\)\s*:=\s*0;)',
            r'\1\n' + init_pid,
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

    if is_client_target and n > 1:
        # Add next(producer_id[i])
        pid_cases = []
        for q in range(4):  # Q_SIZE
            cases = '\n'.join(
                f'        tail = {q} & producer_toggles[{i}] != last_producer_toggle[{i}] : clt{i};'
                for i in range(n)
            )
            pid_cases.append(
                f'    next(producer_id[{q}]) := case\n{cases}\n        TRUE : producer_id[{q}];\n    esac;'
            )

        pid_block = '\n\n'.join(pid_cases)
        text = re.sub(
            r'(next\(tail\)\s*:=\s*case.*?esac;)',
            r'\1\n\n' + pid_block,
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
    if is_client_target and n > 1:
        # Add the request_consumed DEFINE if not already present
        produced_def = (
            '    request_produced := '
            + ' | '.join(
                f'last_producer_toggle[{i}] != producer_toggles[{i}]'
                for i in range(n)
            )
            + ';\n'
        )

        text = re.sub(
            r'(DEFINE\s*\n)',
            r'\1' + produced_def,
            text
        )
    else :
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
    
    if redundancy == 1:
        # Replace ONLY the target instance with Extended version
        text = re.sub(
            rf'process\s+{target_module}\(',
            f'process {target_module}Extended(',
            text
        )

        return text

    n = redundancy

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

    if redundancy == 1:
        # Replace ONLY the target instance
        text = re.sub(
            rf'process\s+{target_module}\(',
            f'process {target_module}Extended(',
            text
        )

        return text

    n = redundancy
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
        if target_module.lower() == 'client':
            instance_lines.append(
                f"{indent}client{i} : process ClientExtended({params}, server.request_source, {i-1});"
            )
        else:
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

def build_extended_wrapper_RRA(nominal_wrapper_text, target_module, redundancy):
    text = nominal_wrapper_text

    # Trim trailing modules
    last_semi = text.rfind(';')
    if last_semi != -1:
        text = text[:last_semi + 1] + '\n'

    # Rename wrapper
    text = re.sub(r'MODULE\s+Nominal\s*\(\)', 'MODULE Extended()', text)

    if redundancy == 1:
        text = re.sub(
            rf'process\s+{target_module}\(',
            f'process {target_module}Extended(',
            text
        )
        return text

    n = redundancy
    is_server_target = target_module.lower() != 'client'

    channels = ["request", "ack", "reply_ack"]

    # Find target instance
    instance_pattern = rf'(\s*)(\w+\s*:\s*process\s+{re.escape(target_module)}\([^)]*\);)'
    match = re.search(instance_pattern, text)
    if not match:
        raise ValueError(f"Could not find instance of {target_module}")

    indent = match.group(1)
    full_line = match.group(2)

    # Extract params safely
    params_match = re.search(r'\(([^)]*)\)', full_line)
    params = params_match.group(1)

    #Replace non-target module with Extended version
    non_target = 'client' if is_server_target else 'server'
    non_target_ext = f'{non_target.capitalize()}Extended'

    non_target_pattern = rf'(\s*\w+\s*:\s*process\s+){non_target.capitalize()}\(([^)]*)\);'

    non_target_match = re.search(non_target_pattern, text, re.IGNORECASE)

    if non_target_match:
        new_line = (
            non_target_match.group(1)
            + non_target_ext
            + '('
            + non_target_match.group(2)
            + ');'
        )
        text = text[:non_target_match.start()] + new_line + text[non_target_match.end():]

    # Build instances
    instance_lines = []
    for i in range(n):
        if target_module.lower() == 'client':
            instance_lines.append(
                f"{indent}client{i+1} : process ClientExtended({params}, {i}, server.request_source);"
            )
        else:
            instance_lines.append(
                f"{indent}server{i+1} : process ServerExtended({params}, {i}, client.ack_source);"
            )

    # Bridge arrays
    bridge_lines = []
    for ch in channels:
        bridge_lines.append(f"{indent}{ch}_prod_toggles : array 0..{n-1} of boolean;")
        bridge_lines.append(f"{indent}{ch}_cons_toggles : array 0..{n-1} of boolean;")

    # Replace Queue instances
    queue_pattern = r'(\s*\w+\s*:\s*process\s+Queue\(([^)]*)\);)'
    queue_matches = list(re.finditer(queue_pattern, text))

    if len(queue_matches) < len(channels):
        raise ValueError("Not enough Queue instances")

    # Build new queue lines first
    new_queue_lines = []
    for ch in channels:
        new_queue_lines.append(
            f": process QueueExtended(Q_SIZE, {ch}_prod_toggles, {ch}_cons_toggles);"
        )

    # Apply replacements BACKWARDS
    for i in reversed(range(len(channels))):
        q_match = queue_matches[i]
        prefix = q_match.group(0).split(':')[0]
        new_line = prefix + new_queue_lines[i]
        text = text[:q_match.start()] + new_line + text[q_match.end():]

    # ASSIGN wiring
    assign_lines = []

    def dummy(i):
        return f"{i} := FALSE;   -- dummy, stays FALSE forever"

    if is_server_target:
        # client is single
        client_name = "client"

        for ch in channels:
            if ch == "request":
                assign_lines.append(f"    {ch}_prod_toggles[0] := {client_name}.request_toggle;")
                for i in range(1, n):
                    assign_lines.append(f"    {ch}_prod_toggles[{i}] := FALSE;   -- dummy, stays FALSE forever")
                for i in range(n):
                    assign_lines.append(f"    {ch}_cons_toggles[{i}] := server{i+1}.request_toggle;")

            elif ch == "ack":
                for i in range(n):
                    assign_lines.append(f"    {ch}_prod_toggles[{i}] := server{i+1}.ack_toggle;")
                assign_lines.append(f"    {ch}_cons_toggles[0] := {client_name}.ack_toggle;")
                for i in range(1, n):
                    assign_lines.append(f"    {ch}_cons_toggles[{i}] := FALSE;   -- dummy, stays FALSE forever")

            elif ch == "reply_ack":
                assign_lines.append(f"    {ch}_prod_toggles[0] := {client_name}.reply_ack_toggle;")
                for i in range(1, n):
                    assign_lines.append(f"    {ch}_prod_toggles[{i}] := FALSE;")
                for i in range(n):
                    assign_lines.append(f"    {ch}_cons_toggles[{i}] := server{i+1}.reply_ack_toggle;")

    else:
        # clients replicated
        for ch in channels:
            if ch == "request":
                for i in range(n):
                    assign_lines.append(f"    {ch}_prod_toggles[{i}] := client{i+1}.request_toggle;")
                assign_lines.append(f"    {ch}_cons_toggles[0] := server.request_toggle;")
                for i in range(1, n):
                    assign_lines.append(f"    {ch}_cons_toggles[{i}] := FALSE;")

            elif ch == "ack":
                assign_lines.append(f"    {ch}_prod_toggles[0] := server.ack_toggle;")
                for i in range(1, n):
                    assign_lines.append(f"    {ch}_prod_toggles[{i}] := FALSE;")
                for i in range(n):
                    assign_lines.append(f"    {ch}_cons_toggles[{i}] := client{i+1}.ack_toggle;")

            elif ch == "reply_ack":
                for i in range(n):
                    assign_lines.append(f"    {ch}_prod_toggles[{i}] := client{i+1}.reply_ack_toggle;")
                assign_lines.append(f"    {ch}_cons_toggles[0] := server.reply_ack_toggle;")
                for i in range(1, n):
                    assign_lines.append(f"    {ch}_cons_toggles[{i}] := FALSE;")

    assign_block = "\n".join(assign_lines)

    # Inject instances
    new_instance_block = "\n".join(bridge_lines + instance_lines)
    text = text.replace(full_line, new_instance_block)

    # ASSIGN block
    if 'ASSIGN' not in text:
        text += f"\nASSIGN\n{assign_block}\n"
    else:
        text = re.sub(r'(ASSIGN\s*\n)', r'\1' + assign_block + '\n', text)

    return text


""" Apply RR-specific transformation to ClientExtended when: target = Client and redundancy > 1 """
def transform_RR_client(text, n):
    # 1. Add ack_owner + client_id parameters
    text = re.sub(
        r'MODULE\s+ClientExtended\(([^)]*)\)',
        r'MODULE ClientExtended(\1, ack_owner)',
        text
    )

    # 2. Add request_sent variable
    text = re.sub(
        r'(ack_received\s*:\s*boolean;)',
        r'\1\n    request_sent : boolean;',
        text
    )
    
    # 3. Initialize request_sent
    text = re.sub(
        r'(init\(ack_received\)\s*:=\s*TRUE;)',
        r'\1\n    init(request_sent) := FALSE;',
        text
    )

    # 4. Inject request_produced guard
    text = text.replace(
        '!request_queue.full & ack_received',
        '!request_queue.full & ack_received & !request_queue.request_produced'
    )

    # 5. Fix ACK transitions using self_id (safe replace)
    ack_condition = (
        'client_ack_state = receiving & !ack_queue.empty '
        '& request_sent & ack_owner = self_id'
    )

    text = re.sub(
        r'client_ack_state = receiving & !ack_queue\.empty(?!\s*& request_sent)',
        ack_condition,
        text
    )

    # 6. Fix ack_toggle transition
    text = re.sub(
        r'(next\(ack_toggle\)\s*:=\s*case.*?)(client_ack_state = receiving[^\n]*: !ack_toggle;)',
        lambda m: m.group(1) + f'        {ack_condition} : !ack_toggle;',
        text,
        flags=re.DOTALL
    )

    # 7. Fix ack_received transition
    text = re.sub(
        r'(next\(ack_received\)\s*:=\s*case.*?)(client_ack_state = receiving[^\n]*: TRUE;)',
        lambda m: m.group(1) + f'        {ack_condition} : TRUE;',
        text,
        flags=re.DOTALL
    )

    # 8. Add request_sent transition
    request_sent_block = f"""
    next(request_sent) := case
        client_request_state = sending & !request_queue.full & ack_received & !request_queue.request_produced : TRUE;
        {ack_condition} : FALSE;
        TRUE : request_sent;
    esac;
    """

    text = re.sub(
        r'(FAIRNESS)',
        request_sent_block + '\nFAIRNESS',
        text
    )

    # 9. Add self_id DEFINE (scalable identity mapping)
    self_id_def = "DEFINE\n" + _build_self_id_define(n) + "\n"

    if 'DEFINE' not in text:
        text = re.sub(
            r'(FAIRNESS)',
            self_id_def + r'\1',
            text
        )

    return text

""" Apply RRA-specific transformation to ClientExtended when: target = Client and redundancy > 1 """
def transform_RRA_client(text, n):

    # 1. Add ack_owner parameter 
    if 'ack_owner' not in text:
        text = re.sub(
            r'MODULE\s+ClientExtended\(([^)]*)\)',
            r'MODULE ClientExtended(\1, ack_owner)',
            text
        )

    # 2. Add missing RRA variables 
    text = re.sub(
        r'(ack_received\s*:\s*boolean;)',
        r'\1\n'
        r'    request_sent : boolean;\n'
        r'    pending_reply_ack : boolean;\n'
        r'    reply_ack_consume_marker : boolean;',
        text
    )

    # 3. Initialize missing variables 
    text = re.sub(
        r'(init\(ack_received\)\s*:=\s*FALSE;)',
        r'\1\n'
        r'    init(request_sent) := FALSE;\n'
        r'    init(pending_reply_ack) := FALSE;\n'
        r'    init(reply_ack_consume_marker) := FALSE;',
        text
    )

    # ------------------------------------------------------------
    # 4. Strengthen request sending condition 
    # ------------------------------------------------------------
    text = text.replace(
        '!request_queue.queue_full & reply_ack_sent',
        '!request_queue.queue_full & reply_ack_sent & !pending_reply_ack & !request_queue.request_produced'
    )

    # 5. ACK condition 
    ack_condition = (
        'client_ack_state = receiving & !ack_queue.queue_empty '
        '& request_sent & ack_owner = self_id'
    )

    text = re.sub(
        r'client_ack_state = receiving & !ack_queue\.queue_empty(?!\s*& request_sent)',
        ack_condition,
        text
    )

    # 6. Fix ack_toggle transition
    text = re.sub(
        r'(next\(ack_toggle\)\s*:=\s*case.*?)(client_ack_state = receiving[^\n]*: !ack_toggle;)',
        lambda m: m.group(1) + f'        {ack_condition} : !ack_toggle;',
        text,
        flags=re.DOTALL
    )

    # 7. Fix ack_received transition
    text = re.sub(
        r'(next\(ack_received\)\s*:=\s*case.*?)(client_ack_state = receiving[^\n]*: TRUE;)',
        lambda m: m.group(1) + f'        {ack_condition} : TRUE;',
        text,
        flags=re.DOTALL
    )

    # 8. Add request_sent transition 
    if 'next(request_sent)' not in text:
        request_sent_block = f"""
        next(request_sent) := case
            client_request_state = sending & !request_queue.queue_full & reply_ack_sent & !pending_reply_ack & !request_queue.request_produced : TRUE;
            {ack_condition} : FALSE;
            TRUE : request_sent;
        esac;
        """

        text = re.sub(
            r'(FAIRNESS)',
            request_sent_block + '\nFAIRNESS',
            text
        )
    
    # 9. Add pending_reply_ack + consume marker transitions
    if 'next(pending_reply_ack)' not in text:
        pending_block = """
        next(pending_reply_ack) := case
            client_reply_ack_state = sending & !reply_ack_queue.queue_full & ack_received : TRUE;
            pending_reply_ack & (
                (reply_ack_queue.last_consumer_toggle[0] != reply_ack_consume_marker)
            ) : FALSE;
            TRUE : pending_reply_ack;
        esac;

        next(reply_ack_consume_marker) := case
            client_reply_ack_state = sending & !reply_ack_queue.queue_full & ack_received : reply_ack_queue.last_consumer_toggle[0];
            TRUE : reply_ack_consume_marker;
        esac;
        """

        text = re.sub(
            r'(FAIRNESS)',
            pending_block + '\nFAIRNESS',
            text
        )

    # 10. Add self_id DEFINE (scalable)
    if 'self_id :=' not in text:
        self_id_def = "DEFINE\n" + _build_self_id_define(n) + "\n"
        text = re.sub(r'(FAIRNESS)', self_id_def + r'\1', text)

    return text

""" Apply RRA-specific transformation to ServerExtended when: target = Server and redundancy > 1 """
def transform_RRA_server(text, n):
    # 1. Add reply_ack_owner parameter
    if 'reply_ack_owner' not in text:
        text = re.sub(
            r'MODULE\s+ServerExtended\(([^)]*)\)',
            r'MODULE ServerExtended(\1, reply_ack_owner)',
            text
        )

    # 2. Strengthen server_request_state condition
    text = text.replace(
        'server_request_state = receiving & !request_queue.queue_empty & reply_ack_received',
        'server_request_state = receiving & !request_queue.queue_empty & reply_ack_received & !request_queue.request_consumed'
    )

    # Restrict ALL reply_ack-related guards with ownership (single pass)
    text = re.sub(
        r'(server_reply_ack_state\s*=\s*receiving\s*&\s*!reply_ack_queue\.queue_empty)(\s*:[^;]*;)',
        r'\1 & reply_ack_owner = self_id\2',
        text
    )

    # 9. Add DEFINE self_id (scales with redundancy)
    if 'self_id :=' not in text:
        lines = ["    self_id := case"]
        for i in range(n):
            lines.append(f"        server_id = {i} : srv{i};")
        lines.append("    esac;")

        define_block = "DEFINE\n" + "\n".join(lines) + "\n"

        text = re.sub(r'(FAIRNESS)', define_block + r'\1', text)

    return text


def _build_self_id_define(n):
    cases = '\n'.join(
        f'            client_id = {i} : clt{i};'
        for i in range(n)
    )
    return (
        "    self_id :=\n"
        "        case\n"
        f"{cases}\n"
        "        esac;\n"
    )


def build_RR_non_target_client(smv_content):
    """Returns the non target extended client module"""
    text = get_module_text(smv_content, 'Client')

    text = re.sub(
        r'MODULE\s+Client\s*\(',
        'MODULE ClientExtended(',
        text
    )

    text = re.sub(
        r'(\w+\.last_(?!producer_id)\w+_toggle)(?!\[)',
        r'\1[0]',
        text
    )

    return text

def build_RR_non_target_server(smv_content, n):
    """Returns the non targer extended server module"""
    text = get_module_text(smv_content, 'Server')

    # 1. Rename module
    text = re.sub(
        r'MODULE\s+Server\s*\(',
        'MODULE ServerExtended(',
        text
    )

    # 2. Index queue toggle accesses → [0]
    text = re.sub(
        r'(\w+\.last_(?:producer|consumer)_toggle)(?!\[)',
        r'\1[0]',
        text
    )

    # 3. Add new VAR fields
    new_vars = (
        "    request_source : {none, " + ", ".join(f"clt{i}" for i in range(n)) + "};\n"
        "    pending_ack : boolean;\n"
        "    ack_consume_marker : boolean;"
    )

    text = re.sub(
        r'(request_received\s*:\s*boolean;)',
        r'\1\n' + new_vars,
        text
    )

    # 4. Initialize new vars
    init_block = (
        "    init(request_source) := none;\n"
        "    init(pending_ack) := FALSE;\n"
        "    init(ack_consume_marker) := FALSE;"
    )

    text = re.sub(
        r'(init\(request_received\)\s*:=\s*FALSE;)',
        r'\1\n' + init_block,
        text
    )

    # 5. Strengthen request receive condition
    text = text.replace(
        'server_request_state = receiving & !request_queue.empty',
        'server_request_state = receiving & !request_queue.empty & !pending_ack'
    )

    # 6. Add request_source logic
    request_source_block = """
    next(request_source) := case
        server_request_state = receiving & !request_queue.empty & !pending_ack :
            request_queue.producer_id[request_queue.head];
        TRUE : request_source;
    esac;
    """

    # 7. Add pending_ack logic (dynamic over n)
    consume_cases = " |\n            ".join(
        f"(request_source = clt{i} & ack_queue.last_consumer_toggle[{i}] != ack_consume_marker)"
        for i in range(n)
    )

    pending_block = f"""
    next(pending_ack) := case
        server_ack_state = sending & !ack_queue.full & request_received : TRUE;
        pending_ack & (
            {consume_cases}
        ) : FALSE;
        TRUE : pending_ack;
    esac;
    """

    # 8. Add ack_consume_marker logic
    marker_cases = "\n".join(
        f"        server_ack_state = sending & !ack_queue.full & request_received & request_source = clt{i} : ack_queue.last_consumer_toggle[{i}];"
        for i in range(n)
    )

    marker_block = f"""
    next(ack_consume_marker) := case
    {marker_cases}
        TRUE : ack_consume_marker;
    esac;
    """

    # 9. Inject new blocks before FAIRNESS
    injection = request_source_block + "\n" + pending_block + "\n" + marker_block + "\n"

    text = re.sub(
        r'(FAIRNESS)',
        injection + r'\1',
        text
    )

    return text

def build_RRA_non_target_client(smv_content, n):
    text = get_module_text(smv_content, 'Client')

    # 1. Rename module
    text = re.sub(
        r'MODULE\s+Client\s*\(',
        'MODULE ClientExtended(',
        text
    )

    # 2. Index queue toggle accesses → [0]
    text = re.sub(
        r'(\w+\.last_(?:producer|consumer)_toggle)(?!\[)',
        r'\1[0]',
        text
    )

    # 3. Add new VAR fields
    servers = ', '.join(f'srv{i}' for i in range(n))
    new_vars = (
        f"    ack_source : {{none, {servers}}};\n"
        "    pending_reply_ack : boolean;\n"
        "    reply_ack_consume_marker : boolean;\n"
    )

    # per-server seen flags
    seen_flags = '\n'.join(
        f"    client_ack_srv{i}_seen : boolean;"
        for i in range(n)
    )

    text = re.sub(
        r'(ack_received\s*:\s*boolean;)',
        r'\1\n' + new_vars + seen_flags,
        text
    )

    # 4. Initialize new vars
    init_block = (
        "    init(ack_source) := none;\n"
        "    init(pending_reply_ack) := FALSE;\n"
        "    init(reply_ack_consume_marker) := FALSE;\n"
    )

    seen_init = '\n'.join(
        f"    init(client_ack_srv{i}_seen) := FALSE;"
        for i in range(n)
    )

    text = re.sub(
        r'(init\(ack_received\)\s*:=\s*FALSE;)',
        r'\1\n' + init_block + seen_init,
        text
    )

    # 5. Strengthen request send condition
    text = text.replace(
        '!request_queue.queue_full & reply_ack_sent',
        '!request_queue.queue_full & reply_ack_sent & !pending_reply_ack'
    )

    # 7. ack_source logic
    ack_source_cases = '\n'.join(
        f"        client_ack_state = receiving & ack_queue.last_producer_toggle[{i}] != client_ack_srv{i}_seen : srv{i};"
        for i in range(n)
    )

    ack_source_block = f"""
    next(ack_source) := case
    {ack_source_cases}
        client_request_state = sending & !request_queue.queue_full & reply_ack_sent & !pending_reply_ack : none;
        TRUE : ack_source;
    esac;
    """

    # 8. pending_reply_ack logic
    consume_cases = " |\n            ".join(
        f"(ack_source = srv{i} & reply_ack_queue.last_consumer_toggle[{i}] != reply_ack_consume_marker)"
        for i in range(n)
    )

    pending_block = f"""
    next(pending_reply_ack) := case
        client_reply_ack_state = sending & !reply_ack_queue.queue_full & ack_received : TRUE;
        pending_reply_ack & (
            {consume_cases}
        ) : FALSE;
        TRUE : pending_reply_ack;
    esac;
    """

    # 9. reply_ack_consume_marker logic
    marker_cases = '\n'.join(
        f"        client_reply_ack_state = sending & !reply_ack_queue.queue_full & ack_received & ack_source = srv{i} : reply_ack_queue.last_consumer_toggle[{i}];"
        for i in range(n)
    )

    marker_block = f"""
    next(reply_ack_consume_marker) := case
    {marker_cases}
        TRUE : reply_ack_consume_marker;
    esac;
    """

    # 10. per-server seen tracking
    seen_blocks = '\n\n'.join(
        f"""
    next(client_ack_srv{i}_seen) := case
        client_ack_state = receiving & !ack_queue.queue_empty &
        ack_queue.last_producer_toggle[{i}] != client_ack_srv{i}_seen :
            ack_queue.last_producer_toggle[{i}];
        TRUE : client_ack_srv{i}_seen;
    esac;
    """
        for i in range(n)
    )

    # 11. Inject everything before FAIRNESS
    injection = (
        ack_source_block
        + pending_block
        + marker_block
        + seen_blocks
        + "\n"
    )

    text = re.sub(
        r'(FAIRNESS)',
        injection + r'\1',
        text
    )

    return text

def build_RRA_non_target_server(smv_content, n):
    """Build the extended non-target Server for RRA protocol."""
    text = get_module_text(smv_content, 'Server')

    # 1. Rename module
    text = re.sub(
        r'MODULE\s+Server\s*\(',
        'MODULE ServerExtended(',
        text
    )

    text = re.sub(
        r'(\w+\.last_(?:producer|consumer)_toggle)(?!\[)',
        r'\1[0]',
        text
    )

    # ------------------------------------------------------------
    # 3. VAR injection (dynamic clients)
    # ------------------------------------------------------------
    clients = ', '.join(f'clt{i}' for i in range(n))

    var_block = (
        f"    request_source : {{none, {clients}}};\n"
        "    pending_ack : boolean;\n"
        "    ack_consume_marker : boolean;"
    )

    text = re.sub(
        r'(server_ack_state\s*:\s*\{[^}]+\};)',
        r'\1\n' + var_block,
        text
    )

    # 4. Inject INIT block
    text = re.sub(
        r'(init\(ack_toggle\)\s*:=\s*FALSE;)',
        r'\1\n'
        r'    init(request_source) := none;\n'
        r'    init(pending_ack) := FALSE;\n'
        r'    init(ack_consume_marker) := FALSE;',
        text
    )

    # 5. Strengthen request transition (RRA semantics)
    text = text.replace(
        'server_request_state = receiving & !request_queue.queue_empty & reply_ack_received',
        'server_request_state = receiving & !request_queue.queue_empty & reply_ack_received & !pending_ack'
    )

    # 6. Add new transitions
    request_source_block = """
    next(request_source) := case
        server_request_state = receiving & !request_queue.queue_empty & reply_ack_received & !pending_ack :
            request_queue.producer_id[request_queue.head];
        TRUE : request_source;
    esac;
    """

    # pending_ack (dynamic OR over clients)
    consume_cases = " |\n            ".join(
        f"(request_source = clt{i} & ack_queue.last_consumer_toggle[{i}] != ack_consume_marker)"
        for i in range(n)
    )

    pending_block = f"""
    next(pending_ack) := case
        server_ack_state = sending & !ack_queue.queue_full & request_received : TRUE;
        pending_ack & (
            {consume_cases}
        ) : FALSE;
        TRUE : pending_ack;
    esac;
    """

    # ack_consume_marker (one case per client)
    marker_cases = '\n'.join(
        f"        server_ack_state = sending & !ack_queue.queue_full & request_received & request_source = clt{i} : ack_queue.last_consumer_toggle[{i}];"
        for i in range(n)
    )

    marker_block = f"""
    next(ack_consume_marker) := case
    {marker_cases}
        TRUE : ack_consume_marker;
    esac;
    """

    extra_block = request_source_block + pending_block + marker_block

    text = re.sub(
        r'(next\(memory_cache\)\s*:=\s*case)',
        extra_block + r'\n\1',
        text
    )

    return text

def build_non_target_module(smv_content, protocol, target, n):
    """Returns the extended non-target module when needed and None if no transformation is required."""
    if protocol == 'RR':
        if target == 'Server':
            return build_RR_non_target_client(smv_content)
        elif target == 'Client':
            return build_RR_non_target_server(smv_content, n)

    if protocol == 'RRA':
        if target == 'Server':
            return build_RRA_non_target_client(smv_content, n)
        elif target == 'Client':
            return build_RRA_non_target_server(smv_content, n)

    return None

def build_extended_queue(queue_text, redundancy, target_module, protocol_type):
    """Invoke the correct queue-extension builder based on protocol type."""
    if protocol_type == 'R':
        return [build_extended_queue_R(queue_text, redundancy, target_module)]
    elif protocol_type in ('RR', 'RRA'):            # goback
        return [build_extended_queue_RR(queue_text, redundancy, target_module)]
    else:
        raise ValueError(f"Unknown protocol type: '{protocol_type}'")


def build_extended_wrapper(nominal_wrapper_text, target_module, redundancy, protocol_type):
    """Invoke the correct wrapper builder based on protocol type."""
    if protocol_type == 'R':
        return build_extended_wrapper_R(nominal_wrapper_text, target_module, redundancy)
    elif protocol_type == 'RR':
        return build_extended_wrapper_RR(nominal_wrapper_text, target_module, redundancy)
    elif protocol_type == 'RRA':
        return build_extended_wrapper_RRA(nominal_wrapper_text, target_module, redundancy)
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