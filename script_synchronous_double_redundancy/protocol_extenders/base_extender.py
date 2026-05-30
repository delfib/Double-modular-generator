from abc import ABC, abstractmethod


class BaseProtocolExtender(ABC):

    @abstractmethod
    def extend_queue(self, queue_text, redundancy):
        pass

    @abstractmethod
    def extend_client(self, client_text, redundancy):
        pass

    @abstractmethod
    def extend_server(self, server_text, redundancy):
        pass

    @abstractmethod
    def extend_wrapper(self, wrapper_text, redundancy):
        pass

    @abstractmethod
    def build_non_target_module(self, smv_content, redundancy):
        pass