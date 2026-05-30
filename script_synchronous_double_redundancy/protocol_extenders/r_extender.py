import re
from protocol_extenders.base_extender import BaseExtender

MAX_REDUNDANCY = 10

def _array_bound(n):
    return f'0..{n - 1}'

def _init_set(n):
    return '{' + ','.join(str(i) for i in range(n)) + '}'

class RExtender(BaseExtender):
    def extend_queue(self, text, fault_model):
        n_clients, n_servers = self._get_redundancy(fault_model)

        text = re.sub(
            r'MODULE\s+Queue\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)',
            r'MODULE QueueExtended(\1, client_toggles, server_toggles)',
            text
        )

        # Expand VAR
        for side in ("client", "server"):
            text = re.sub(
                rf'last_{side}_toggle\s*:\s*boolean;',
                f'last_{side}_toggle : array {_array_bound(MAX_REDUNDANCY)} of boolean;',
                text
            )

        text = text.replace(
            'ASSIGN',
            f'    next_client_turn : 0..{MAX_REDUNDANCY - 1};\n'
            f'    next_server_turn : 0..{MAX_REDUNDANCY - 1};\n\n'
            f'ASSIGN',
            1
        )

        # Replace single init(last_*_toggle) with per-slot inits 
        for side in ("client", "server"):
            inits = '\n'.join(
                f'    init(last_{side}_toggle[{i}]) := FALSE;'
                for i in range(MAX_REDUNDANCY))

            text = re.sub(rf'init\(last_{side}_toggle\)\s*:=\s*FALSE;', inits, text)

        # Add init(next_client_turn) and init(next_server_turn)
        last_server_init = f'    init(last_server_toggle[{MAX_REDUNDANCY - 1}]) := FALSE;'

        text = text.replace(
            last_server_init,
            last_server_init
            + f'\n    init(next_client_turn) := {_init_set(n_clients)};'
            + f'\n    init(next_server_turn) := {_init_set(n_servers)};', 1)

        # Replace next(tail) and next(head)
        for pointer, side, toggles in (
            ("tail", "client", "client_toggles"),
            ("head", "server", "server_toggles"),
        ):
            cases = '\n'.join(
                f'        ({toggles}[{i}] != last_{side}_toggle[{i}]) : ({pointer} + 1) mod Q_SIZE;'
                for i in range(MAX_REDUNDANCY)
            )
            text = re.sub(
                rf'next\({pointer}\)\s*:=\s*case.*?esac;',
                f'next({pointer}) := case\n{cases}\n        TRUE : {pointer};\n    esac;',
                text, flags=re.DOTALL)

        # Replace next(last_*_toggle) blocks
        for side, toggles in (
            ("client", "client_toggles"),
            ("server", "server_toggles"),
        ):
            nexts = '\n\n'.join(
                f'    next(last_{side}_toggle[{i}]) := case\n'
                f'        ({toggles}[{i}] != last_{side}_toggle[{i}]) : {toggles}[{i}];\n'
                f'        TRUE : last_{side}_toggle[{i}];\n'
                f'    esac;'
                for i in range(MAX_REDUNDANCY)
            )

            text = re.sub(rf'next\(last_{side}_toggle\)\s*:=\s*case.*?esac;', nexts, text, flags=re.DOTALL)

        # Add next(next_client_turn) and next(next_server_turn)
        text = re.sub(
            r'(DEFINE)',
            f'    next(next_client_turn) := {_init_set(n_clients)};\n\n'
            f'    next(next_server_turn) := {_init_set(n_servers)};\n\n'
            r'\1',
            text
        )

        # Add request_consumed DEFINE
        consumed_def = (
            '    request_consumed := '
            + ' | '.join(
                f'last_server_toggle[{i}] != server_toggles[{i}]'
                for i in range(MAX_REDUNDANCY)
            )
            + ';\n'
        )

        text = re.sub(r'(DEFINE\s*\n)', r'\1' + consumed_def, text)

        return text         


    def extend_client(self, text):
        text = re.sub(
            r'MODULE\s+Client\s*\(([^)]+)\)',
            r'MODULE ClientExtended(\1, client_id, client_states)', text)

        # Build the all-sending guard (same for all 3 replacements)
        all_sending = (
            ' & '.join(f'client_states[{i}] = sending' for i in range(MAX_REDUNDANCY))
        )
        turn_guard = (
            f' & queue.next_client_turn = client_id &\n'
            f'                ({all_sending})'
        )

        # Extend the 3 occurrences of the sending condition
        text = text.replace(
            'client_state = sending & !queue.full',
            f'client_state = sending & !queue.full{turn_guard}',
        )

        return text

    def extend_server(self, text):
        text = re.sub(
            r'MODULE\s+Server\s*\(([^)]+)\)',
            r'MODULE ServerExtended(\1, server_id)', text)

        text = text.replace(
            'server_state = receiving & !queue.empty',
            'server_state = receiving & !queue.empty & !queue.request_consumed & queue.next_server_turn = server_id',
        )

        return text

    def extend_wrapper(self, text, fault_model):
        n_clients, n_servers = self._get_redundancy(fault_model)

        var_arrays = (
            f'    client_toggles : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    server_toggles : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    client_states : array 0..{MAX_REDUNDANCY - 1} of {{sending, sent}};\n'
        )
        var_clients = ''.join(
            f'    client{i + 1} : ClientExtended(queue, {i}, client_states);\n'
            for i in range(n_clients)
        )
        var_servers = ''.join(
            f'    server{i + 1} : ServerExtended(queue, {i});\n'
            for i in range(n_servers)
        )

        assign_client_toggles = ''.join(
            f'    client_toggles[{i}] := client{i + 1}.request_toggle;\n'
            for i in range(n_clients)
        ) + ''.join(
            f'    client_toggles[{i}] := FALSE;\n'
            for i in range(n_clients, MAX_REDUNDANCY)
        )

        assign_server_toggles = ''.join(
            f'    server_toggles[{i}] := server{i + 1}.request_toggle;\n'
            for i in range(n_servers)
        ) + ''.join(
            f'    server_toggles[{i}] := FALSE;\n'
            for i in range(n_servers, MAX_REDUNDANCY)
        )

        assign_client_states = ''.join(
            f'    client_states[{i}] := client{i + 1}.client_state;\n'
            for i in range(n_clients)
        ) + ''.join(
            f'    client_states[{i}] := sending;\n'
            for i in range(n_clients, MAX_REDUNDANCY)
        )

        return (
            f'MODULE Extended()\n'
            f'DEFINE\n'
            f'    Q_SIZE := 4;\n'
            f'VAR\n'
            f'{var_arrays}'
            f'{var_clients}'
            f'{var_servers}'
            f'    queue : QueueExtended(Q_SIZE, client_toggles, server_toggles);\n'
            f'ASSIGN\n'
            f'{assign_client_toggles}'
            f'{assign_server_toggles}'
            f'{assign_client_states}'
        )