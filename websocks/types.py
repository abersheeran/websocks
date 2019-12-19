from abc import ABCMeta, abstractmethod


class Socket(metaclass=ABCMeta):
    @abstractmethod
    async def recv(self, num: int) -> bytes:
        raise NotImplementedError()

    @abstractmethod
    async def send(self, data: bytes) -> int:
        raise NotImplementedError()

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError()

    @property
    @abstractmethod
    def closed(self) -> bool:
        raise NotImplementedError()
