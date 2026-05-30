import re
from protocol_extenders.base_extender import BaseExtender

def _array_bound(n):
    return f'0..{n - 1}'

def _init_set(n):
    return '{' + ','.join(str(i) for i in range(n)) + '}'


class RExtender(BaseExtender):
    def extend_queue(self, text, fault_model):
        MAX = 10
 
        # --- Rename module and expand both parameter names ---
        text = re.sub(
            r'MODULE\s+Queue\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)',
            r'MODULE QueueExtended(\1, client_toggles, server_toggles)',
            text
        )
 
        # --- Expand VAR: last_client_toggle boolean -> array ---
        text = re.sub(
            r'last_client_toggle\s*:\s*boolean;',
            f'last_client_toggle : array {_array_bound(MAX)} of boolean;',
            text
        )
 
        # --- Expand VAR: last_server_toggle boolean -> array ---
        text = re.sub(
            r'last_server_toggle\s*:\s*boolean;',
            f'last_server_toggle : array {_array_bound(MAX)} of boolean;',
            text
        )
 
        # --- Add next_client_turn and next_server_turn to VAR ---
        text = text.replace(
            'ASSIGN',
            f'    next_client_turn : 0..{MAX - 1};\n'
            f'    next_server_turn : 0..{MAX - 1};\n\n'
            f'ASSIGN',
            1
        )
 
        # --- Replace single init(last_client_toggle) with per-slot inits ---
        client_inits = '\n'.join(
            f'    init(last_client_toggle[{i}]) := FALSE;' for i in range(MAX)
        )
        text = re.sub(
            r'init\(last_client_toggle\)\s*:=\s*FALSE;',
            client_inits,
            text
        )
 
        # --- Replace single init(last_server_toggle) with per-slot inits ---
        server_inits = '\n'.join(
            f'    init(last_server_toggle[{i}]) := FALSE;' for i in range(MAX)
        )
        text = re.sub(
            r'init\(last_server_toggle\)\s*:=\s*FALSE;',
            server_inits,
            text
        )
 
        # --- Add init(next_client_turn) and init(next_server_turn) ---
        last_server_init = f'    init(last_server_toggle[{MAX - 1}]) := FALSE;'
        text = text.replace(
            last_server_init,
            last_server_init
            + f'\n    init(next_client_turn) := {_init_set(MAX)};'
            + f'\n    init(next_server_turn) := {_init_set(MAX)};',
            1
        )
 
        # --- Replace next(tail) with multi-slot client case ---
        tail_cases = '\n'.join(
            f'        (client_toggles[{i}] != last_client_toggle[{i}]) : (tail + 1) mod Q_SIZE;'
            for i in range(MAX)
        )
        text = re.sub(
            r'next\(tail\)\s*:=\s*case.*?esac;',
            f'next(tail) := case\n{tail_cases}\n        TRUE : tail;\n    esac;',
            text,
            flags=re.DOTALL
        )
 
        # --- Replace next(head) with multi-slot server case ---
        head_cases = '\n'.join(
            f'        (server_toggles[{i}] != last_server_toggle[{i}]) : (head + 1) mod Q_SIZE;'
            for i in range(MAX)
        )
        text = re.sub(
            r'next\(head\)\s*:=\s*case.*?esac;',
            f'next(head) := case\n{head_cases}\n        TRUE : head;\n    esac;',
            text,
            flags=re.DOTALL
        )
 
        # --- Replace next(last_client_toggle) with per-slot nexts ---
        client_nexts = '\n\n'.join(
            f'    next(last_client_toggle[{i}]) := case\n'
            f'        (client_toggles[{i}] != last_client_toggle[{i}]) : client_toggles[{i}];\n'
            f'        TRUE : last_client_toggle[{i}];\n'
            f'    esac;'
            for i in range(MAX)
        )
        text = re.sub(
            r'next\(last_client_toggle\)\s*:=\s*case.*?esac;',
            client_nexts,
            text,
            flags=re.DOTALL
        )
 
        # --- Replace next(last_server_toggle) with per-slot nexts ---
        server_nexts = '\n\n'.join(
            f'    next(last_server_toggle[{i}]) := case\n'
            f'        (server_toggles[{i}] != last_server_toggle[{i}]) : server_toggles[{i}];\n'
            f'        TRUE : last_server_toggle[{i}];\n'
            f'    esac;'
            for i in range(MAX)
        )
        text = re.sub(
            r'next\(last_server_toggle\)\s*:=\s*case.*?esac;',
            server_nexts,
            text,
            flags=re.DOTALL
        )
 
        # --- Add next(next_client_turn) and next(next_server_turn) before DEFINE ---
        client_turn_next = (
            f'    next(next_client_turn) := {_init_set(MAX)};\n\n'
        )
        server_turn_next = (
            f'    next(next_server_turn) := {_init_set(MAX)};\n\n'
        )
        text = re.sub(
            r'(DEFINE)',
            client_turn_next + server_turn_next + r'\1',
            text
        )
 
        # --- Add request_consumed DEFINE ---
        consumed_def = (
            '    request_consumed := '
            + ' | '.join(
                f'last_server_toggle[{i}] != server_toggles[{i}]'
                for i in range(MAX)
            )
            + ';\n'
        )
        text = re.sub(
            r'(DEFINE\s*\n)',
            r'\1' + consumed_def,
            text
        )
 
        return text


    def extend_client(self, text, fault_model):
        return text

    def extend_server(self, text, fault_model):
        return text

    def extend_wrapper(self, text, fault_model):
        return text

    def build_sync_module(self, fault_model):
        return "syncccccc"