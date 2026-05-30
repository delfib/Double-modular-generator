import re
from protocol_extenders.base_extender import BaseExtender, MAX_REDUNDANCY

class RRExtender(BaseExtender):

    def extend_queue(self, text, fault_model):
        n_clients, n_servers = self._get_redundancy(fault_model)
        text = self._extend_queue_base(text, n_clients, n_servers, 'producer', 'consumer')

        # Add producer_id VAR (insert after 'VAR\n')
        producer_id_enum = ', '.join(['none'] + [f'clt{i}' for i in range(MAX_REDUNDANCY)])
        text = re.sub(
            r'(VAR\n)',
            f'\\1    producer_id : array 0..3 of {{{producer_id_enum}}};\n', text)

        # Add producer_id inits (insert before first last_producer_toggle init)
        producer_id_inits = '\n'.join(f'    init(producer_id[{i}]) := none;' for i in range(4))

        text = re.sub(r'(    init\(last_producer_toggle\[0\]\) := FALSE;)', producer_id_inits + r'\n    \1', text)

        # Insert next(producer_id[N]) blocks after next(tail)
        producer_id_nexts = '\n'.join(
            '    next(producer_id[{slot}]) := case\n'.format(slot=slot)
            + '\n'.join(
                f'        tail = {slot} & producer_toggles[{i}] != last_producer_toggle[{i}] : clt{i};'
                for i in range(MAX_REDUNDANCY)
            )
            + f'\n        TRUE : producer_id[{slot}];\n    esac;'
            for slot in range(4))

        text = re.sub(r'(next\(tail\)\s*:=\s*case.*?esac;)', r'\1\n' + producer_id_nexts, text, flags=re.DOTALL)

        return text

    def extend_client(self, text):
        return text

    def extend_server(self, text):
        return text

    def extend_wrapper(self, text, fault_model):
        return text