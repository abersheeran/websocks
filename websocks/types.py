from abc import ABCMeta, abstractmethod


class Socket(metaclass=ABCMeta):

    @abstractmethod
    async def recv(self) -> bytes:
        raise NotImplementedError()

    @abstractmethod
    async def send(self, data: bytes) -> int:
        raise NotImplementedError()

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError()

    @abstractmethod
    def closed(self) -> bool:
        raise NotImplementedError()
