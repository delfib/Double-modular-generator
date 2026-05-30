import re
from protocol_extenders.base_extender import BaseExtender

def _array_bound(n):
    return f'0..{n - 1}'

def _init_set(n):
    return '{' + ','.join(str(i) for i in range(n)) + '}'


class RExtender(BaseExtender):
    def extend_queue(self, text, fault_model):
        client_cfg = fault_model.modules.get("Client")
        server_cfg = fault_model.modules.get("Server")

        n_clients = client_cfg.redundancy if client_cfg else 1
        n_servers = server_cfg.redundancy if server_cfg else 1

        MAX = 10

        text = re.sub(
            r'MODULE\s+Queue\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)',
            r'MODULE QueueExtended(\1, client_toggles, server_toggles)',
            text
        )

        # Expand VAR
        for side in ("client", "server"):
            text = re.sub(
                rf'last_{side}_toggle\s*:\s*boolean;',
                f'last_{side}_toggle : array {_array_bound(MAX)} of boolean;',
                text
            )

        text = text.replace(
            'ASSIGN',
            f'    next_client_turn : 0..{MAX - 1};\n'
            f'    next_server_turn : 0..{MAX - 1};\n\n'
            f'ASSIGN',
            1
        )

        # Replace single init(last_*_toggle) with per-slot inits 
        for side in ("client", "server"):
            inits = '\n'.join(
                f'    init(last_{side}_toggle[{i}]) := FALSE;'
                for i in range(MAX))

            text = re.sub(rf'init\(last_{side}_toggle\)\s*:=\s*FALSE;', inits, text)

        # Add init(next_client_turn) and init(next_server_turn)
        last_server_init = f'    init(last_server_toggle[{MAX - 1}]) := FALSE;'

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
                for i in range(MAX)
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
                for i in range(MAX)
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
                for i in range(MAX)
            )
            + ';\n'
        )

        text = re.sub(r'(DEFINE\s*\n)', r'\1' + consumed_def, text)

        return text         


    def extend_client(self, text, fault_model):
        return text

    def extend_server(self, text, fault_model):
        return text

    def extend_wrapper(self, text, fault_model):
        return text

    def build_sync_module(self, fault_model):
        return "syncccccc"