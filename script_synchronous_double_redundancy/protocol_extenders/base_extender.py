import re
from abc import ABC, abstractmethod

MAX_REDUNDANCY = 10

def _array_bound(n):
    return f'0..{n - 1}'

def _init_set(n):
    return '{' + ','.join(str(i) for i in range(n)) + '}'

class BaseExtender(ABC):

    def _get_redundancy(self, fault_model):
        client_cfg = fault_model.modules.get("Client")
        server_cfg = fault_model.modules.get("Server")
        n_clients = client_cfg.redundancy if client_cfg else 1
        n_servers = server_cfg.redundancy if server_cfg else 1
        return n_clients, n_servers


    def _extend_queue_base(self, text, n_producers, n_consumers, producer_name, consumer_name):
        """Shared queue extension logic for all protocols."""
        prod, cons = producer_name, consumer_name

        # Rename module and parameters
        text = re.sub(
            r'MODULE\s+Queue\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)',
            rf'MODULE QueueExtended(\1, {prod}_toggles, {cons}_toggles)', text)

        # Expand VAR toggle arrays
        for side in (prod, cons):
            text = re.sub(
                rf'last_{side}_toggle\s*:\s*boolean;',
                f'last_{side}_toggle : array {_array_bound(MAX_REDUNDANCY)} of boolean;', text)

        # Add turn vars to VAR
        text = text.replace(
            'ASSIGN',
            f'    next_{prod}_turn : 0..{MAX_REDUNDANCY - 1};\n'
            f'    next_{cons}_turn : 0..{MAX_REDUNDANCY - 1};\n\n'
            f'ASSIGN', 1)

        # Replace single inits with per-slot inits
        for side in (prod, cons):
            inits = '\n'.join(
                f'    init(last_{side}_toggle[{i}]) := FALSE;' for i in range(MAX_REDUNDANCY)
            )
            text = re.sub(rf'init\(last_{side}_toggle\)\s*:=\s*FALSE;', inits, text)

        # Add init(next_*_turn) after last consumer init
        last_cons_init = f'    init(last_{cons}_toggle[{MAX_REDUNDANCY - 1}]) := FALSE;'
        text = text.replace(
            last_cons_init,
            last_cons_init
            + f'\n    init(next_{prod}_turn) := {_init_set(n_producers)};'
            + f'\n    init(next_{cons}_turn) := {_init_set(n_consumers)};', 1)

        # Replace next(tail) and next(head)
        for pointer, side in (("tail", prod), ("head", cons)):
            cases = '\n'.join(
                f'        ({side}_toggles[{i}] != last_{side}_toggle[{i}]) : ({pointer} + 1) mod Q_SIZE;'
                for i in range(MAX_REDUNDANCY))
            text = re.sub(
                rf'next\({pointer}\)\s*:=\s*case.*?esac;',
                f'next({pointer}) := case\n{cases}\n        TRUE : {pointer};\n    esac;',
                text, flags=re.DOTALL)

        # Replace next(last_*_toggle) blocks
        for side in (prod, cons):
            nexts = '\n\n'.join(
                f'    next(last_{side}_toggle[{i}]) := case\n'
                f'        ({side}_toggles[{i}] != last_{side}_toggle[{i}]) : {side}_toggles[{i}];\n'
                f'        TRUE : last_{side}_toggle[{i}];\n'
                f'    esac;'
                for i in range(MAX_REDUNDANCY))
            text = re.sub(
                rf'next\(last_{side}_toggle\)\s*:=\s*case.*?esac;',
                nexts, text, flags=re.DOTALL)

        # Add next(next_*_turn) before DEFINE
        text = re.sub(
            r'(DEFINE)',
            f'    next(next_{prod}_turn) := {_init_set(n_producers)};\n\n'
            f'    next(next_{cons}_turn) := {_init_set(n_consumers)};\n\n'
            r'\1', text)

        # Add request_consumed DEFINE
        consumed_def = (
            '    request_consumed := '
            + ' | '.join(
                f'last_{cons}_toggle[{i}] != {cons}_toggles[{i}]'
                for i in range(MAX_REDUNDANCY)
            )
            + ';\n')
        text = re.sub(r'(DEFINE\s*\n)', r'\1' + consumed_def, text)

        return text
    

    def _extend_queue_with_producer_id(self, text, n_clients, n_servers):
        text = self._extend_queue_base(text, n_clients, n_servers, 'producer', 'consumer')

        producer_id_enum = ', '.join(['none'] + [f'clt{i}' for i in range(MAX_REDUNDANCY)])
        text = re.sub(
            r'(VAR\n)',
            f'\\1    producer_id : array 0..3 of {{{producer_id_enum}}};\n', text)

        producer_id_inits = '\n'.join(f'    init(producer_id[{i}]) := none;' for i in range(4))
        text = re.sub(r'(    init\(last_producer_toggle\[0\]\) := FALSE;)', producer_id_inits + r'\n    \1', text)

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


    def _assign_array_from_modules(self, array_name, source, field, n, n_max, default_value='FALSE'):
        active = ''.join(
            f'    {array_name}[{i}] := {source}{i + 1}.{field};\n'
            for i in range(n)
        )

        padding = ''.join(
            f'    {array_name}[{i}] := {default_value};\n'
            for i in range(n, n_max)
        )

        return active + padding


    def extend(self, modules, fault_model):
        self._fault_model = fault_model
        modules["queue"] = self.extend_queue(modules["queue"])
        modules["client"] = self.extend_client(modules["client"])
        modules["server"] = self.extend_server(modules["server"])
        modules["wrapper"] = self.extend_wrapper()
        modules["sync"] = self.build_sync_module()
        modules["main"] = self.build_main_module()
        
        return modules

    @abstractmethod
    def extend_queue(self, text):
        pass

    @abstractmethod
    def extend_client(self, text):
        pass

    @abstractmethod
    def extend_server(self, text):
        pass

    @abstractmethod
    def extend_wrapper(self):
        pass

    def build_sync_module(self):
        return (
            'MODULE Sync()\n'
            'VAR\n'
            '    nominal  : Nominal();\n'
            '    extended : Extended();'
        )

    def build_main_module(self):
        return (
            'MODULE main\n'
            'VAR\n'
            '    sync : Sync();'
        )