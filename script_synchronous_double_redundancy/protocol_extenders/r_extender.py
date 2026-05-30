from protocol_extenders.base_extender import BaseExtender

class RExtender(BaseExtender):

    def extend_queue(self, text, fault_model):
        raise NotImplementedError

    def extend_client(self, text, fault_model):
        raise NotImplementedError

    def extend_server(self, text, fault_model):
        raise NotImplementedError

    def extend_wrapper(self, text, fault_model):
        raise NotImplementedError

    def build_sync_module(self, fault_model):
        raise NotImplementedError