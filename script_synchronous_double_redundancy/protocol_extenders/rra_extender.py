import re
from protocol_extenders.base_extender import MAX_REDUNDANCY, BaseExtender

class RRAExtender(BaseExtender):

    def extend_queue(self, text):
        n_clients, n_servers = self._get_redundancy(self._fault_model)
        return self._extend_queue_with_producer_id(text, n_clients, n_servers)


    def extend_client(self, text):
        n_clients, n_servers = self._get_redundancy(self._fault_model)

        text = re.sub(
            r'MODULE\s+Client\s*\(([^)]+)\)',
            r'MODULE ClientExtended(\1, ack_owners, client_id, reply_ack_sent_states, pending_reply_ack_states)',
            text
        )

        # Add new variables to VAR
        seen_vars = '\n'.join(f'    client_ack_srv{i}_seen    : boolean;' for i in range(MAX_REDUNDANCY))
        srv_enum = ', '.join([f'srv{i}' for i in range(MAX_REDUNDANCY)])
        
        new_vars = (
            f'    request_sent            : boolean;\n'
            f'    ack_source              : {{none, {srv_enum}}};\n'
            f'{seen_vars}'
        )
        text = text.replace(
            '    ack_received            : boolean;',
            f'    ack_received            : boolean;\n{new_vars}'
        )

        seen_inits = '\n'.join(f'    init(client_ack_srv{i}_seen)   := FALSE;' for i in range(MAX_REDUNDANCY))
        new_inits = (
            f'    init(request_sent)            := FALSE;\n'
            f'    init(ack_source)              := none;\n'
            f'{seen_inits}'
        )
        text = text.replace(
            '    init(ack_received)           := FALSE;',
            f'    init(ack_received)           := FALSE;\n{new_inits}'
        )

        pending_states_guard = ' & '.join(f'pending_reply_ack_states[{i}] = FALSE' for i in range(n_clients))
        sent_states_guard = ' & '.join(f'reply_ack_sent_states[{i}] = TRUE' for i in range(n_clients))
        
        sending_guard = (
            f' & request_queue.next_producer_turn = client_id &\n'
            f'        ({pending_states_guard}) &\n'
            f'        ({sent_states_guard})'
        )
        
        ack_owners_guard = ' | '.join(f'ack_owners[{i}] = self_id' for i in range(n_servers))

        nominal_send_cond = 'client_request_state = sending & !request_queue.queue_full & reply_ack_sent & !pending_reply_ack'
        text = text.replace(nominal_send_cond, f'{nominal_send_cond}{sending_guard}')

        nominal_ack_cond = 'client_ack_state = receiving & !ack_queue.queue_empty'
        text = text.replace(nominal_ack_cond, f'{nominal_ack_cond} & request_sent & ({ack_owners_guard})')

        request_sent_block = (
            f'    next(request_sent) := case\n'
            f'        {nominal_send_cond}{sending_guard} : TRUE;\n'
            f'        {nominal_ack_cond} & request_sent & ({ack_owners_guard}) : FALSE;\n'
            f'        TRUE : request_sent;\n'
            f'    esac;\n\n'
        )
        text = text.replace('    next(pending_reply_ack) := case', request_sent_block + '    next(pending_reply_ack) := case')

        ack_source_cases = '\n'.join(
            f'        client_ack_state = receiving & ack_queue.last_producer_toggle[{i}] != client_ack_srv{i}_seen : srv{i};'
            for i in range(n_servers)
        )
        ack_source_block = (
            f'    next(ack_source) := case\n'
            f'{ack_source_cases}\n'
            f'        {nominal_send_cond}{sending_guard} : none;\n'
            f'        TRUE : ack_source;\n'
            f'    esac;\n\n'
        )
        text = text.replace('    next(pending_reply_ack) := case', ack_source_block + '    next(pending_reply_ack) := case')

        pending_ack_loops = ' |\n'.join(
            f'            (ack_source = srv{i} & reply_ack_queue.last_consumer_toggle[{i}] != reply_ack_consume_marker)'
            for i in range(n_servers)
        )
        text = re.sub(
            r'pending_reply_ack\s*&\s*\(\s*\(reply_ack_queue\.last_consumer_toggle\s*!=\s*reply_ack_consume_marker\)\s*\)',
            f'pending_reply_ack & (\n{pending_ack_loops}\n        )',
            text
        )

        consume_marker_cases = '\n'.join(
            f'        client_reply_ack_state = sending & !reply_ack_queue.queue_full & ack_received & ack_source = srv{i} : reply_ack_queue.last_consumer_toggle[{i}];'
            for i in range(n_servers)
        )
        text = re.sub(
            r'next\(reply_ack_consume_marker\)\s*:=\s*case.*?esac;',
            f'next(reply_ack_consume_marker) := case\n{consume_marker_cases}\n        TRUE : reply_ack_consume_marker;\n    esac;',
            text, flags=re.DOTALL
        )

        seen_nexts_blocks = ""
        for i in range(MAX_REDUNDANCY):
            seen_nexts_blocks += (
                f'    next(client_ack_srv{i}_seen) := case\n'
                f'        client_ack_state = receiving & !ack_queue.queue_empty & ack_queue.last_producer_toggle[{i}] != client_ack_srv{i}_seen : ack_queue.last_producer_toggle[{i}];\n'
                f'        TRUE : client_ack_srv{i}_seen;\n'
                f'    esac;\n\n'
            )
        text = text.replace('    next(num_requests_sent) := case', seen_nexts_blocks + '    next(num_requests_sent) := case')

        self_id_cases = '\n'.join(f'        client_id = {i} : clt{i};' for i in range(MAX_REDUNDANCY))
        text = text.rstrip() + (
            f'\n\nDEFINE\n'
            f'    self_id := case\n'
            f'{self_id_cases}\n'
            f'    esac;'
        )

        return text


    def extend_server(self, text):
        n_clients, n_servers = self._get_redundancy(self._fault_model)

        text = re.sub(
            r'MODULE\s+Server\s*\(([^)]+)\)',
            r'MODULE ServerExtended(\1, reply_ack_owners, server_id)',
            text
        )

        # Add new variables to VAR
        clt_enum = ', '.join(['none'] + [f'clt{i}' for i in range(MAX_REDUNDANCY)])
        new_vars = (
            f'    request_source          : {{{clt_enum}}};\n'
            f'    pending_ack             : boolean;\n'
            f'    ack_consume_marker      : boolean;'
        )
        text = text.replace(
            '    reply_ack_received      : boolean;',
            f'    reply_ack_received      : boolean;\n{new_vars}'
        )

        # Add new initializations to ASSIGN
        new_inits = (
            f'    init(request_source)         := none;\n'
            f'    init(pending_ack)            := FALSE;\n'
            f'    init(ack_consume_marker)     := FALSE;'
        )
        text = text.replace(
            '    init(reply_ack_received)     := TRUE;',
            f'    init(reply_ack_received)     := TRUE;\n{new_inits}'
        )

        rra_receive_guard = '& !pending_ack & !request_queue.request_consumed & request_queue.next_consumer_turn = server_id'
        
        reply_ack_owners_guard = ' | '.join(f'reply_ack_owners[{i}] = self_id' for i in range(n_clients))

        nominal_receive_cond = 'server_request_state = receiving & !request_queue.queue_empty & reply_ack_received'
        text = text.replace(nominal_receive_cond, f'{nominal_receive_cond} {rra_receive_guard}')

        nominal_reply_ack_cond = 'server_reply_ack_state = receiving & !reply_ack_queue.queue_empty'
        text = text.replace(nominal_reply_ack_cond, f'{nominal_reply_ack_cond} & ({reply_ack_owners_guard})')

        request_source_block = (
            f'    next(request_source) := case\n'
            f'        {nominal_receive_cond} {rra_receive_guard} : request_queue.producer_id[request_queue.head];\n'
            f'        TRUE : request_source;\n'
            f'    esac;\n\n'
        )
        text = text.replace('    next(num_requests_received)', request_source_block + '    next(num_requests_received)')

        nominal_ack_sent_cond = 'server_ack_state = sending & !ack_queue.queue_full & request_received'
        pending_ack_loops = ' |\n'.join(
            f'            (request_source = clt{i} & ack_queue.last_consumer_toggle[{i}] != ack_consume_marker)'
            for i in range(n_clients)
        )
        pending_ack_block = (
            f'    next(pending_ack) := case\n'
            f'        {nominal_ack_sent_cond} : TRUE;\n'
            f'        pending_ack & (\n'
            f'{pending_ack_loops}\n'
            f'        ) : FALSE;\n'
            f'        TRUE : pending_ack;\n'
            f'    esac;\n\n'
        )
        text = text.replace('    next(num_requests_received)', pending_ack_block + '    next(num_requests_received)')

        consume_marker_cases = '\n'.join(
            f'        {nominal_ack_sent_cond} & request_source = clt{i} : ack_queue.last_consumer_toggle[{i}];'
            for i in range(n_clients)
        )
        ack_consume_marker_block = (
            f'    next(ack_consume_marker) := case\n'
            f'{consume_marker_cases}\n'
            f'        TRUE : ack_consume_marker;\n'
            f'    esac;\n\n'
        )
        text = text.replace('    next(num_requests_received)', ack_consume_marker_block + '    next(num_requests_received)')

        self_id_cases = '\n'.join(f'        server_id = {i} : srv{i};' for i in range(MAX_REDUNDANCY))
        text = text.rstrip() + (
            f'\n\nDEFINE\n'
            f'    self_id := case\n'
            f'{self_id_cases}\n'
            f'    esac;'
        )

        return text


    def extend_wrapper(self):
        n_clients, n_servers = self._get_redundancy(self._fault_model)

        full_clt_enum = ', '.join(['none'] + [f'clt{i}' for i in range(MAX_REDUNDANCY)])
        full_srv_enum = ', '.join(['none'] + [f'srv{i}' for i in range(MAX_REDUNDANCY)])

        var_arrays = (
            f'    request_prod_toggles     : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    request_cons_toggles     : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    ack_prod_toggles         : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    ack_cons_toggles         : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    reply_ack_prod_toggles   : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    reply_ack_cons_toggles   : array 0..{MAX_REDUNDANCY - 1} of boolean;\n\n'
            f'    reply_ack_sent_states    : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    pending_reply_ack_states : array 0..{MAX_REDUNDANCY - 1} of boolean;\n'
            f'    ack_owners               : array 0..{MAX_REDUNDANCY - 1} of {{{full_clt_enum}}};\n'
            f'    reply_ack_owners         : array 0..{MAX_REDUNDANCY - 1} of {{{full_srv_enum}}};\n\n'
        )

        var_clients = ''.join(
            f'    client{i + 1} : ClientExtended(request_queue, ack_queue, reply_ack_queue, '
            f'ack_owners, {i}, reply_ack_sent_states, pending_reply_ack_states);\n'
            for i in range(n_clients)
        ) + '\n'

        var_servers = ''.join(
            f'    server{i + 1} : ServerExtended(request_queue, ack_queue, reply_ack_queue, reply_ack_owners, {i});\n'
            for i in range(n_servers)
        ) + '\n'

        var_queues = (
            f'    request_queue   : QueueExtended(Q_SIZE, request_prod_toggles, request_cons_toggles);\n'
            f'    ack_queue       : QueueExtended(Q_SIZE, ack_prod_toggles, ack_cons_toggles);\n'
            f'    reply_ack_queue : QueueExtended(Q_SIZE, reply_ack_prod_toggles, reply_ack_cons_toggles);\n'
        )

        assign_sections = (
            self._assign_array_from_modules('request_prod_toggles', 'client', 'request_toggle', n_clients, MAX_REDUNDANCY) +
            self._assign_array_from_modules('request_cons_toggles', 'server', 'request_toggle', n_servers, MAX_REDUNDANCY) +
            self._assign_array_from_modules('ack_prod_toggles', 'server', 'ack_toggle', n_servers, MAX_REDUNDANCY) +
            self._assign_array_from_modules('ack_cons_toggles', 'client', 'ack_toggle', n_clients, MAX_REDUNDANCY) +
            self._assign_array_from_modules('reply_ack_prod_toggles', 'client', 'reply_ack_toggle', n_clients, MAX_REDUNDANCY) +
            self._assign_array_from_modules('reply_ack_cons_toggles', 'server', 'reply_ack_toggle', n_servers, MAX_REDUNDANCY) +
            self._assign_array_from_modules('reply_ack_sent_states', 'client', 'reply_ack_sent', n_clients, MAX_REDUNDANCY, 'FALSE') +
            self._assign_array_from_modules('pending_reply_ack_states', 'client', 'pending_reply_ack', n_clients, MAX_REDUNDANCY, 'FALSE') +
            self._assign_array_from_modules('ack_owners', 'server', 'request_source', n_servers, MAX_REDUNDANCY, 'none') +
            self._assign_array_from_modules('reply_ack_owners', 'client', 'ack_source', n_clients, MAX_REDUNDANCY, 'none')
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