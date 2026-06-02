from protocol_extenders.base_extender import BaseExtender

class RRAExtender(BaseExtender):

    def extend_queue(self, text):
        n_clients, n_servers = self._get_redundancy(self._fault_model)
        return self._extend_queue_with_producer_id(text, n_clients, n_servers)

    def extend_client(self, text):
        return text

    def extend_server(self, text):
        return text

    def extend_wrapper(self):
        return "WRAPPER"