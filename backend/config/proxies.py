"""TRUSTED_PROXIES: the addresses whose X-Forwarded-For/-Proto count (settings, relay settings and gunicorn).

"auto" (the default) means loopback plus the networks the container is directly attached to: the Compose network,
from where the reverse proxy (or Docker's port forwarding for a proxy on the host) connects. Up to 0.8.4 the default
was all of 172.16.0.0/12, which also covers many office and VPN networks.
"""
import ipaddress
import socket
import struct

LOOPBACK = ["127.0.0.0/8", "::1/128"]
RTF_GATEWAY = 0x2  # a route via a gateway: not a network the container is attached to


def attached(route="/proc/net/route", route6="/proc/net/ipv6_route"):
    """The networks with a direct route (Linux), without the default route, loopback and link-local."""
    nets = []
    try:
        with open(route) as f:
            next(f)  # header
            for p in (line.split() for line in f):
                dest, flags, mask = int(p[1], 16), int(p[3], 16), int(p[7], 16)
                if mask and not flags & RTF_GATEWAY:
                    addr, netmask = (socket.inet_ntoa(struct.pack("<I", x)) for x in (dest, mask))
                    nets.append(str(ipaddress.ip_network(f"{addr}/{netmask}", strict=False)))
    except OSError:
        pass
    try:
        with open(route6) as f:
            for p in (line.split() for line in f):
                plen, flags, dev = int(p[1], 16), int(p[8], 16), p[9]
                net = ipaddress.ip_network((int(p[0], 16), plen), strict=False)
                if plen and dev != "lo" and not flags & RTF_GATEWAY and not (net.is_link_local or net.is_multicast):
                    nets.append(str(net))
    except OSError:
        pass
    return list(dict.fromkeys(nets))


def trusted(spec):
    """The comma-separated setting as a list of networks; "auto" stands for loopback plus the attached networks."""
    out = []
    for item in (x.strip() for x in spec.split(",")):
        if item == "auto":
            out += LOOPBACK + attached()
        elif item:
            out.append(item)
    return out
