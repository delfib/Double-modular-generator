from abc import ABC, abstractmethod

class BaseExtender(ABC):

    def extend(self, modules, fault_model):
        modules["queue"] = self.extend_queue(modules["queue"], fault_model)
        modules["client"] = self.extend_client(modules["client"], fault_model)
        modules["server"] = self.extend_server(modules["server"], fault_model)
        modules["wrapper"] = self.extend_wrapper(modules["wrapper"], fault_model)
        modules["sync"] = self.build_sync_module(fault_model)
        
        return modules

    @abstractmethod
    def extend_queue(self, text, fault_model):
        pass

    @abstractmethod
    def extend_client(self, text, fault_model):
        pass

    @abstractmethod
    def extend_server(self, text, fault_model):
        pass

    @abstractmethod
    def extend_wrapper(self, text, fault_model):
        pass

    def build_sync_module(self, fault_model):
        return (
            'MODULE Sync()\n'
            'VAR\n'
            '    nominal  : Nominal();\n'
            '    extended : Extended();'
        )