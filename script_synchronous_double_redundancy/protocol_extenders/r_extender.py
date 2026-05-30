import re
from protocol_extenders.base_extender import BaseExtender, MAX_REDUNDANCY

class RExtender(BaseExtender):

    def extend_queue(self, text, fault_model):
        n_clients, n_servers = self._get_redundancy(fault_model)
        return self._extend_queue_base(text, n_clients, n_servers, 'client', 'server')

    def extend_client(self, text):
        text = re.sub(
            r'MODULE\s+Client\s*\(([^)]+)\)',
            r'MODULE ClientExtended(\1, client_id, client_states)', text)

        # Build the all-sending guard (same for all 3 replacements)
        all_sending = (' & '.join(f'client_states[{i}] = sending' for i in range(MAX_REDUNDANCY)))
        turn_guard = (
            f' & queue.next_client_turn = client_id &\n'
            f'                ({all_sending})')

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