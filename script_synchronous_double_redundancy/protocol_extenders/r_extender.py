from extenders.base_extender import BaseProtocolExtender


class RExtender(BaseProtocolExtender):

    def extend_queue(self, queue_text, redundancy):
        pass

    def extend_client(self, client_text, redundancy):
        pass

    def extend_server(self, server_text, redundancy):
        pass

    def extend_wrapper(self, wrapper_text, redundancy):
        pass

    def build_non_target_module(self, smv_content, redundancy):
        return None