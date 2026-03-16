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


# ---------------------------------------------------------------------------
# Extended Queue builder — R protocol
#
# The R protocol has a single Queue(Q_SIZE, client_toggle, server_toggle).
# Depending on the target:
#   - Server target  -> expand the server (consumer) side into an array
#   - Client target  -> expand the client (producer) side into an array
# ---------------------------------------------------------------------------

def build_extended_queue_R(queue_text, redundancy, target_module):
    """
    Clone the single Queue module, rename it to QueueExtended, and widen
    either the producer side (Client target) or the consumer side (Server
    target) into an array of toggle slots.
    """
    text = _strip_to_fairness(queue_text)

    is_server_target = target_module.lower() != 'client'

    # -----------------------------------------------------------------------
    # Decide which side becomes the array
    # producer side  = client_toggle / last_client_toggle
    # consumer side  = server_toggle / last_server_toggle
    # -----------------------------------------------------------------------
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

    n           = redundancy
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


# ---------------------------------------------------------------------------
# Extended Queue builder — RR protocol
#
# The RR protocol has two queues that share the same Queue module:
#   request_queue = Queue(Q_SIZE, producer_toggle, consumer_toggle)
#   ack_queue     = Queue(Q_SIZE, producer_toggle, consumer_toggle)
#
# In the extended version BOTH sides of the queue become arrays of size n,
# with a dummy FALSE slot for the non-redundant side.  This produces a single
# unified QueueExtended module reused for both request_queue and ack_queue:
#
#   MODULE QueueExtended(Q_SIZE, producer_toggles, consumer_toggles)
#       last_producer_toggle : array 0..n-1 of boolean;
#       last_consumer_toggle : array 0..n-1 of boolean;
#
# Wiring in the Extended wrapper (Server target, redundancy=2 example):
#   request_queue:
#       producer_toggles[0] = client.request_toggle   (real)
#       producer_toggles[1] = FALSE                   (dummy)
#       consumer_toggles[0] = server1.request_toggle  (real)
#       consumer_toggles[1] = server2.request_toggle  (real)
#   ack_queue:
#       producer_toggles[0] = server1.ack_toggle      (real)
#       producer_toggles[1] = server2.ack_toggle      (real)
#       consumer_toggles[0] = client.ack_toggle       (real)
#       consumer_toggles[1] = FALSE                   (dummy)
#
# For Client target the real/dummy assignments are mirrored.
# ---------------------------------------------------------------------------

def build_extended_queue_RR(queue_text, redundancy):
    """
    Build a single unified QueueExtended module for the RR protocol where
    BOTH the producer and consumer sides are widened to arrays of size n.

    The caller is responsible for wiring real vs dummy slots in the wrapper.
    """
    text = _strip_to_fairness(queue_text)

    n           = redundancy
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
    # (needed by Server modules to avoid double-consumption)
    if 'request_consumed' not in text:
        consumed_def = (
            '    request_consumed := '
            + ' | '.join(
                f'last_consumer_toggle[{i}] != consumer_toggles[{i}]'
                for i in range(n)
            )
            + '\n'
        )
        text = re.sub(
            r'(DEFINE\s*\n)',
            r'\1' + consumed_def,
            text
        )

    return text


# ---------------------------------------------------------------------------
# Extended Wrapper builder — R protocol
# ---------------------------------------------------------------------------

def build_extended_wrapper_R(nominal_wrapper_text, target_module, redundancy):
    """
    Clone the Nominal wrapper for the R protocol, rename it to Extended, and
    replace the single target instance with `redundancy` Extended instances
    plus the shared toggles array.

    Works for both Server target and Client target.
    """
    text = nominal_wrapper_text

    # Keep only up to the last ";" (drops any trailing MODULE main or comments)
    last_semi = text.rfind(';')
    if last_semi != -1:
        text = text[:last_semi + 1] + '\n'

    # Rename wrapper module
    text = re.sub(r'MODULE\s+Nominal\s*\(\)', 'MODULE Extended()', text)

    n        = redundancy
    id_param = f"{target_module.lower()}_id"

    # -----------------------------------------------------------------------
    # Locate the original target instance line
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Determine which queue side is widened and build toggle arrays accordingly
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Locate and update the Queue instance line
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Build ASSIGN block wiring toggle arrays to instance toggle fields
    # -----------------------------------------------------------------------
    assign_lines = '\n'.join(
        f"    {array_name}[{i}] := {target_module.lower()}{i+1}.{toggle_field};"
        for i in range(n)
    )

    # -----------------------------------------------------------------------
    # Splice everything together
    # -----------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Extended Wrapper builder — RR protocol
# ---------------------------------------------------------------------------

def build_extended_wrapper_RR(nominal_wrapper_text, target_module, redundancy):
    """
    Clone the Nominal wrapper for the RR protocol, rename it to Extended, and
    replace the single target instance with `redundancy` Extended instances.

    Both queues are replaced with QueueExtended instances (the single unified
    module where both sides are arrays).  The non-redundant side in each queue
    gets dummy FALSE slots wired in the ASSIGN block.

    Server target wiring example (redundancy=2):
        request_prod_toggles[0] := client.request_toggle;
        request_prod_toggles[1] := FALSE;               -- dummy
        request_cons_toggles[0] := server1.request_toggle;
        request_cons_toggles[1] := server2.request_toggle;

        ack_prod_toggles[0] := server1.ack_toggle;
        ack_prod_toggles[1] := server2.ack_toggle;
        ack_cons_toggles[0] := client.ack_toggle;
        ack_cons_toggles[1] := FALSE;                   -- dummy

    Client target wiring is mirrored.

    ?? aca tendria que separar para los casos para crear las colas, porque aca
    deberia buscar por request_queue o ack_queue, no solo para queue.
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

    # -----------------------------------------------------------------------
    # Locate the original target instance line
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Declare the four bridge arrays (prod/cons for each queue)
    # -----------------------------------------------------------------------
    bridge_lines = [
        f"{indent}request_prod_toggles : array 0..{n-1} of boolean;",
        f"{indent}request_cons_toggles : array 0..{n-1} of boolean;",
        f"{indent}ack_prod_toggles     : array 0..{n-1} of boolean;",
        f"{indent}ack_cons_toggles     : array 0..{n-1} of boolean;",
    ]

    # -----------------------------------------------------------------------
    # Build ASSIGN wiring:
    # Server target:
    #   request_queue producer = 1 real client slot + (n-1) dummy FALSE slots
    #   request_queue consumer = n real server slots
    #   ack_queue     producer = n real server slots
    #   ack_queue     consumer = 1 real client slot + (n-1) dummy FALSE slots
    #
    # Client target (mirrored):
    #   request_queue producer = n real client slots
    #   request_queue consumer = 1 real server slot + (n-1) dummy FALSE slots
    #   ack_queue     producer = 1 real server slot + (n-1) dummy FALSE slots
    #   ack_queue     consumer = n real client slots
    # -----------------------------------------------------------------------
    assign_lines = []

    # Find the name of the non-target instance in the wrapper
    # (the single remaining client or server that stays as-is)
    non_target = 'client' if is_server_target else 'server'
    non_target_pattern = rf'(\w+)\s*:\s*process\s+{non_target.capitalize()}\('
    non_target_match = re.search(non_target_pattern, text, re.IGNORECASE)
    non_target_inst = non_target_match.group(1) if non_target_match else non_target

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

    # -----------------------------------------------------------------------
    # Replace both Queue instances with QueueExtended, passing the four arrays
    # ?? aca separamos por request_queue y ack_queue, no solo por queue
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Replace original target instance with expanded instances + bridge arrays
    # -----------------------------------------------------------------------
    # Re-find after queue substitutions shifted offsets
    match = re.search(instance_pattern, text)
    if not match:
        raise ValueError(
            f"Could not re-find instance of {target_module} in wrapper after queue substitution"
        )

    new_instance_block = '\n'.join(bridge_lines + instance_lines)
    text = text[:match.start()] + new_instance_block + text[match.end():]

    # -----------------------------------------------------------------------
    # Add or extend the ASSIGN block
    # -----------------------------------------------------------------------
    if 'ASSIGN' not in text:
        text = text.rstrip() + f'\n\nASSIGN\n{assign_block}\n'
    else:
        text = re.sub(r'(ASSIGN\s*\n)', r'\1' + assign_block + '\n', text)

    return text


# ---------------------------------------------------------------------------
# Dispatcher: pick the right queue / wrapper builders by protocol type
# ---------------------------------------------------------------------------

def build_extended_queues(queue_text, redundancy, target_module, protocol_type):
    """
    Dispatch to the correct queue-extension builder based on protocol type.

    Returns a list of module_text strings:
      - R  protocol: one item  (single QueueExtended, one side widened)
      - RR protocol: one item  (single unified QueueExtended, both sides widened)
    """
    if protocol_type == 'R':
        return [build_extended_queue_R(queue_text, redundancy, target_module)]
    elif protocol_type == 'RR':
        # Single unified QueueExtended reused for both request_queue and ack_queue
        return [build_extended_queue_RR(queue_text, redundancy)]
    else:
        raise ValueError(f"Unknown protocol type: '{protocol_type}'")


def build_extended_wrapper(nominal_wrapper_text, target_module, redundancy, protocol_type):
    """
    Dispatch to the correct wrapper builder based on protocol type.
    """
    if protocol_type == 'R':
        return build_extended_wrapper_R(nominal_wrapper_text, target_module, redundancy)
    elif protocol_type == 'RR':
        return build_extended_wrapper_RR(nominal_wrapper_text, target_module, redundancy)
    else:
        raise ValueError(f"Unknown protocol type: '{protocol_type}'")


# ---------------------------------------------------------------------------
# Sync + Main module builder
# ---------------------------------------------------------------------------

def build_sync_module(target_module, redundancy, properties=None):
    """
    Build the Sync module that instantiates both Nominal and Extended side
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