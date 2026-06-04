import re
from protocol_extenders.base_extender import BaseExtender, MAX_REDUNDANCY

class RRExtender(BaseExtender):

    def extend_queue(self, text):
        n_clients, n_servers = self._get_redundancy(self._fault_model)
        return self._extend_queue_with_producer_id(text, n_clients, n_servers)


    def extend_client(self, text):
        n_clients, n_servers = self._get_redundancy(self._fault_model)

        text = re.sub(
            r'MODULE\s+Client\s*\(([^)]+)\)',
            r'MODULE ClientExtended(\1, ack_owners, client_id, client_states)',
            text
        )
        
        text = text.replace(
            '    ack_received : boolean;',
            '    ack_received : boolean;\n    request_sent : boolean;'
        )
        text = text.replace(
            '    init(ack_received) := TRUE;',
            '    init(ack_received) := TRUE;\n    init(request_sent) := FALSE;'
        )

        # Build guards
        all_ready = ' & '.join(f'client_states[{i}] = TRUE' for i in range(n_clients))
        turn_guard = (
            f' & request_queue.next_producer_turn = client_id &\n'
            f'            ({all_ready})'
        )
        ack_owners_guard = (
            '(' + ' | '.join(f'ack_owners[{i}] = self_id' for i in range(n_servers)) + ')'
        )

        # Extend the sending condition 
        text = text.replace(
            'client_request_state = sending & !request_queue.full & ack_received',
            f'client_request_state = sending & !request_queue.full & ack_received{turn_guard}',
        )

        # Extend the ack condition
        text = text.replace(
            'client_ack_state = receiving & !ack_queue.empty',
            f'client_ack_state = receiving & !ack_queue.empty & request_sent & {ack_owners_guard}',
        )

        # Add next(request_sent) block before next(num_requests_sent)
        request_sent_block = (
            f'    next(request_sent) := case\n'
            f'        client_request_state = sending & !request_queue.full & ack_received{turn_guard} : TRUE;\n'
            f'        client_ack_state = receiving & !ack_queue.empty & request_sent & {ack_owners_guard} : FALSE;\n'
            f'        TRUE : request_sent;\n'
            f'    esac;\n'
        )
        text = text.replace(
            '    next(num_requests_sent)',
            request_sent_block + '    next(num_requests_sent)'
        )

        # Add DEFINE self_id block
        self_id_cases = '\n'.join(
            f'        client_id = {i} : clt{i};' for i in range(MAX_REDUNDANCY)
        )
        text = text.rstrip() + (
            f'\nDEFINE\n'
            f'    self_id := case\n'
            f'{self_id_cases}\n'
            f'    esac;'
        )

        return text


    def extend_server(self, text):
        n_clients, n_servers = self._get_redundancy(self._fault_model)

        text = re.sub(
            r'MODULE\s+Server\s*\(([^)]+)\)',
            r'MODULE ServerExtended(\1, server_id)', text)

        # Add new VARs
        text = text.replace(
            '    request_received : boolean;',
            '    request_received : boolean;\n'
            '    request_source : {' + ', '.join(['none'] + [f'clt{i}' for i in range(MAX_REDUNDANCY)]) + '};\n'
            '    pending_ack : boolean;\n'
            '    ack_consume_marker : boolean;'
        )

        # Add new inits
        text = text.replace(
            '    init(request_received) := FALSE;',
            '    init(request_received) := FALSE;\n'
            '    init(request_source) := none;\n'
            '    init(pending_ack) := FALSE;\n'
            '    init(ack_consume_marker) := FALSE;'
        )

        # Extend the receiving condition 
        rr_guard = '& !pending_ack & !request_queue.request_consumed & request_queue.next_consumer_turn = server_id'
        text = text.replace(
            'server_request_state = receiving & !request_queue.empty',
            f'server_request_state = receiving & !request_queue.empty {rr_guard}',
        )

        # Add next(request_source), next(pending_ack), next(ack_consume_marker)
        pending_ack_cases = ' |\n'.join(
            f'            (request_source = clt{i} & ack_queue.last_consumer_toggle[{i}] != ack_consume_marker)'
            for i in range(n_clients)
        )
        ack_consume_cases = '\n'.join(
            f'        server_ack_state = sending & !ack_queue.full & request_received & request_source = clt{i} : ack_queue.last_consumer_toggle[{i}];'
            for i in range(n_clients)
        )

        new_blocks = (
            f'    next(request_source) := case\n'
            f'        server_request_state = receiving & !request_queue.empty {rr_guard} : request_queue.producer_id[request_queue.head];\n'
            f'        TRUE : request_source;\n'
            f'    esac;\n\n'
            f'    next(pending_ack) := case\n'
            f'        server_ack_state = sending & !ack_queue.full & request_received : TRUE;\n'
            f'        pending_ack & (\n'
            f'{pending_ack_cases}\n'
            f'        ) : FALSE;\n'
            f'        TRUE : pending_ack;\n'
            f'    esac;\n\n'
            f'    next(ack_consume_marker) := case\n'
            f'{ack_consume_cases}\n'
            f'        TRUE : ack_consume_marker;\n'
            f'    esac;\n\n'
        )
        text = text.replace(
            '    next(num_requests_received)',
            new_blocks + '    next(num_requests_received)'
        )

        return text


    def extend_wrapper(self):
        n_clients, n_servers = self._get_redundancy(self._fault_model)

        full_clt_enum = ', '.join(['none'] + [f'clt{i}' for i in range(MAX_REDUNDANCY)])

        var_arrays = (
            f'    request_prod_toggles : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    request_cons_toggles : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    ack_prod_toggles : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    ack_cons_toggles : array 0..{MAX_REDUNDANCY - 1} of boolean;\n\n'
            f'    client_states : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    ack_owners : array 0..{MAX_REDUNDANCY - 1} of {{{full_clt_enum}}};\n'
        )

        var_clients = ''.join(
            f'    client{i + 1} : ClientExtended(request_queue, ack_queue, ack_owners, {i}, client_states);\n'
            for i in range(n_clients)
        )

        var_servers = ''.join(
            f'    server{i + 1} : ServerExtended(request_queue, ack_queue, {i});\n'
            for i in range(n_servers)
        )

        var_queues = (
            f'    request_queue : QueueExtended(Q_SIZE, request_prod_toggles, request_cons_toggles);\n'
            f'    ack_queue : QueueExtended(Q_SIZE, ack_prod_toggles, ack_cons_toggles);\n'
        )

        assign_sections = (
            self._assign_array_from_modules('request_prod_toggles', 'client', 'request_toggle', n_clients, MAX_REDUNDANCY)
            + self._assign_array_from_modules('request_cons_toggles', 'server', 'request_toggle', n_servers, MAX_REDUNDANCY)
            + self._assign_array_from_modules('ack_prod_toggles', 'server', 'ack_toggle', n_servers, MAX_REDUNDANCY)
            + self._assign_array_from_modules('ack_cons_toggles', 'client', 'ack_toggle', n_clients, MAX_REDUNDANCY)
            + self._assign_array_from_modules('client_states', 'client', 'ack_received', n_clients, MAX_REDUNDANCY, 'TRUE')
            + ''.join(
                f'    ack_owners[{i}] := server{i + 1}.request_source;\n'
                for i in range(n_servers)
            )
            + ''.join(
                f'    ack_owners[{i}] := none;\n'
                for i in range(n_servers, MAX_REDUNDANCY)
            )
        )

        return (
            f'MODULE Extended()\n'
            f'DEFINE\n'
            f'    Q_SIZE := 4;\n'
            f'VAR\n'
            f'{var_arrays}'
            f'{var_clients}'
            f'{var_servers}'
            f'{var_queues}'
            f'ASSIGN\n'
            f'{assign_sections}'
        )