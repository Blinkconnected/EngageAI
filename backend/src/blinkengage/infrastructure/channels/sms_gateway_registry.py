"""Process-wide registry mapping a gateway name (``"twilio"``, ...) to an
``SmsGateway`` subclass — mirrors ``ChannelRegistry`` one level down. See
``docs/architecture/sms.md``.
"""

from collections.abc import Callable

from blinkengage.domain.sms_gateway import SmsGateway


class SmsGatewayRegistry:
    _gateways: dict[str, type[SmsGateway]] = {}

    @classmethod
    def register(cls, gateway_name: str) -> Callable[[type[SmsGateway]], type[SmsGateway]]:
        def _decorator(gateway_cls: type[SmsGateway]) -> type[SmsGateway]:
            existing = cls._gateways.get(gateway_name)
            if existing is not None and existing is not gateway_cls:
                raise ValueError(
                    f"SMS gateway {gateway_name!r} is already registered to {existing!r}"
                )
            cls._gateways[gateway_name] = gateway_cls
            return gateway_cls

        return _decorator

    @classmethod
    def get(cls, gateway_name: str) -> type[SmsGateway] | None:
        return cls._gateways.get(gateway_name)

    @classmethod
    def known_gateways(cls) -> frozenset[str]:
        return frozenset(cls._gateways.keys())
