from abc import ABC, abstractmethod

class BaseExtender(ABC):

    def _get_redundancy(self, fault_model):
        client_cfg = fault_model.modules.get("Client")
        server_cfg = fault_model.modules.get("Server")
        n_clients = client_cfg.redundancy if client_cfg else 1
        n_servers = server_cfg.redundancy if server_cfg else 1
        return n_clients, n_servers

    def extend(self, modules, fault_model):
        modules["queue"] = self.extend_queue(modules["queue"], fault_model)
        modules["client"] = self.extend_client(modules["client"])
        modules["server"] = self.extend_server(modules["server"])
        modules["wrapper"] = self.extend_wrapper(modules["wrapper"], fault_model)
        modules["sync"] = self.build_sync_module()
        
        return modules

    @abstractmethod
    def extend_queue(self, text, fault_model):
        pass

    @abstractmethod
    def extend_client(self, text):
        pass

    @abstractmethod
    def extend_server(self, text):
        pass

    @abstractmethod
    def extend_wrapper(self, text, fault_model):
        pass

    def build_sync_module(self):
        return (
            'MODULE Sync()\n'
            'VAR\n'
            '    nominal  : Nominal();\n'
            '    extended : Extended();'
        )