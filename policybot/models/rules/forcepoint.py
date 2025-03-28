from models.rules.base_rule import BaseRuleSet, ActionsEnum
from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Union, Tuple, Dict
from pydantic.networks import IPvAnyAddress, IPvAnyNetwork
from ipaddress import _BaseAddress as IPAddress
from ipaddress import _BaseNetwork as IPNetwork


class ForcepointActions(ActionsEnum):
    ALLOW = "allow"
    CONTINUE = "continue"
    DISCARD = "discard"
    REFUSE = "refuse"

class NetworksEnum(Enum):
    EXTERNAL = "External"
    ANY = "Any"

class PortsEnum(Enum):
    ANY = ("Any", 0)

ExternalNetwork = NetworksEnum.EXTERNAL
AnyNetwork = NetworksEnum.ANY
AnyPort = PortsEnum.ANY

class ForcepointRule(BaseModel):
    src_addrs: List[Union[IPvAnyAddress, IPvAnyNetwork, NetworksEnum]] = Field(alias="Source")
    dst_addrs: List[Union[IPvAnyAddress, IPvAnyNetwork, NetworksEnum]] = Field(alias="Destination")
    # first element is the service name (DNS, HTTPS, TCP, etc.)
    # second element is the destination port number
    services: List[Union[Tuple[str, int], PortsEnum]] = Field(alias="Service", min_length=1)
    action: ForcepointActions = Field(alias="Action")

    class Config:  
        use_enum_values = True

    def get_addresses(self):
        for addr in (self.src_addrs + self.dst_addrs):
            if isinstance(addr, IPAddress):
                yield addr
            elif isinstance(addr, IPNetwork):
                continue
            elif addr in ("External", "Any"):
                continue
            else:
                raise TypeError("source address can be either an ip or a network")
        
    def get_networks(self):
        for addr in (self.src_addrs + self.dst_addrs):
            if isinstance(addr, IPAddress):
                continue
            elif isinstance(addr, IPNetwork):
                yield addr
            elif addr in ("External", "Any"):
                continue
            else:
                raise TypeError("source address can be either an ip or a network")

    def get_services(self):
        for service in self.services:
            if service != ("Any", 0):
                yield service

    def to_xml(self, name: str, rank: int, addr_refs: Dict[Union[IPvAnyAddress, IPvAnyNetwork], str], service_refs: Dict[Tuple[str, int], str]) -> str:
        sources = []
        destinations = []
        services = []
        preamble = ["  "*3+f"<rule_entry name=\"{name}\" is_disabled=\"false\" parent_rule_ref=\"Access rule: insert point\" rank=\"{rank}\">", "  "*4+"<access_rule>", "          <match_part>"]
        postamble = ["  "*4+"</access_rule>", "  "*3+"</rule_entry>"]

        for addr in self.src_addrs:
            if addr == "External":
                sources.append("  "*7+f"<match_source_ref type=\"network_element\" value=\"External\" ref_key=\"111\"/>")
            elif addr == "Any":
                sources.append("  "*7+f"<match_source_ref type=\"network_element\" value=\"ANY\"/>")
            else:
                sources.append("  "*7+f"<match_source_ref type=\"network_element\" value=\"{addr_refs[addr]}\"/>")
        for addr in self.dst_addrs:
            if addr == "External":
                destinations.append("  "*7+f"<match_destination_ref type=\"network_element\" value=\"External\" ref_key=\"111\"/>")
            elif addr == "Any":
                destinations.append("  "*7+f"<match_destination_ref type=\"network_element\" value=\"ANY\"/>")
            else:
                destinations.append("  "*7+f"<match_destination_ref type=\"network_element\" value=\"{addr_refs[addr]}\"/>")
        for service in self.services:
            if service == ("Any", 0):
                services.append("  "*7+f"<match_service_ref type=\"service\" value=\"ANY\"/>")
            else:
                services.append("  "*7+f"<match_service_ref type=\"service\" value=\"{service_refs[service]}\"/>")

        sources = ["  "*6+"<match_sources>"] + sources + ["  "*6+"</match_sources>"]
        destinations = ["  "*6+"<match_destinations>"] + destinations + ["  "*6+"</match_destinations>"]
        services = ["  "*6+"<match_services>"] + services + ["  "*6+"</match_services>\n"+"  "*5+"</match_part>"]
        actions = ["  "*5+f"<action type=\"{self.action}\" />"]

        return "\n".join(preamble+sources+destinations+services+actions+postamble)


class ForcePointRuleSet(BaseRuleSet):
    root: List[ForcepointRule]


    def get_all_addr_refs(self) -> Dict[Union[IPvAnyAddress, IPvAnyNetwork], str]:
        addrs = set()
        addr_refs = dict()

        for rule in self.root:
            addrs.update(rule.get_addresses())
            addrs.update(rule.get_networks())

        for addr in addrs:
            if isinstance(addr, IPAddress):
                addr_refs[addr] = f"{addr}"
            elif isinstance(addr, IPNetwork):
                addr_refs[addr] = f"network-{addr}"
            elif addr in ("External", "Any"):
                continue
            else:
                raise TypeError(f"{addr} is not a valid address")
            
        return addr_refs

    def get_all_service_refs(self) -> Dict[Tuple[str, int], str]:
        services = set()
        service_refs = dict()

        for rule in self.root:
            services.update(rule.get_services())

        for service in services:
            service_refs[service] = "/".join(map(str, service))

        return service_refs

    def to_xml(self, rule_name="test_policy") -> str:
        hosts = []
        networks = []
        services = []
        rules = []
        policy = []

        preamble = ["<?xml version='1.0' encoding='UTF-8' ?>",
               "<!DOCTYPE generic_import_export SYSTEM \"generic_import_export_v7.0.dtd\">",
               "<generic_import_export build=\"11323\" update_package_version=\"1568\">",
               ]
        postamble = ["</generic_import_export>"]

        addr_refs = self.get_all_addr_refs()
        service_refs = self.get_all_service_refs()
        
        for addr, name in addr_refs.items():
            if isinstance(addr, IPAddress):
                hosts.append(f"  <host name=\"{name}\">\n    <mvia_address address=\"{addr}\" />\n  </host>")
            elif isinstance(addr, IPNetwork):
                networks.append(f"  <network ipv{addr.version}_network=\"{addr}\" name=\"{name}\"/>")
            elif addr in ("External", "Any"):
                continue
            else:
                raise TypeError(f"{addr} is not a valid address")
            
        for service, name in service_refs.items():
            services.append(f"  <service_tcp name=\"{name}\" min_dst_port=\"{service[1]}\" />")

        for i, rule in enumerate(self.root, start=1):
            rules.append(rule.to_xml(name=f"{rule_name}-{i}", rank=i, addr_refs=addr_refs, service_refs=service_refs))
        
        policy.append("  "+f"<fw_policy name=\"{rule_name}\" template_policy_ref=\"Firewall Template 1\">")
        policy.append("  "*2+"<access_entry>")
        policy += rules
        policy.append("  "*2+"</access_entry>")
        policy.append("  "+"</fw_policy>")

        rule_xml = preamble + policy + networks + hosts + services + postamble

        return "\n".join(rule_xml)



