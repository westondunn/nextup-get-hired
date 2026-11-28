"""The single HTTPS origin an authenticated staging gateway may present."""

import re
from dataclasses import dataclass

DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


@dataclass(frozen=True)
class GatewayOrigin:
    authorities: frozenset[str]

    @classmethod
    def parse(cls, value: str) -> "GatewayOrigin":
        if not isinstance(value, str) or not value.isascii():
            raise ValueError
        scheme, separator, authority = value.lower().partition("://")
        if scheme != "https" or not separator:
            raise ValueError
        host, colon, port_text = authority.partition(":")
        labels = host.split(".")
        if len(host) > 253 or not all(DNS_LABEL.fullmatch(label) for label in labels):
            raise ValueError
        # A browser interprets a numeric final label (including hexadecimal) as IPv4.
        if re.fullmatch(r"[0-9]+|0x[0-9a-f]*", labels[-1]):
            raise ValueError
        if colon and not re.fullmatch(r"[1-9][0-9]{0,4}", port_text):
            raise ValueError
        port = int(port_text) if colon else 443
        if port > 65535:
            raise ValueError
        authorities = {f"{host}:{port}"}
        if port == 443:
            authorities.add(host)
        return cls(frozenset(authorities))

    def matches_authority(self, authority: str) -> bool:
        return authority.isascii() and authority.lower() in self.authorities

    def matches_origin(self, origin: str) -> bool:
        scheme, separator, authority = origin.partition("://")
        return scheme.lower() == "https" and bool(separator) and self.matches_authority(authority)
