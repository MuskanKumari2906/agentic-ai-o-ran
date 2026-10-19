"""Render OAI-style gNB configuration files.

The layout follows OpenAirInterface's `gnb.sa.band78.*.conf` sample files (libconfig
syntax, `gNBs` list, `security` block with the comment text OAI ships). Radio
parameters are abridged. The `interface_security` group is a SECTWIN EXTENSION: OAI
has no such block; it models the O-RAN / 3GPP interface-protection settings that a
multi-vendor deployment would carry (documented as such in docs/DATASET.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field


def _q(v) -> str:
    return f'"{v}"'


def _alg_list(algs) -> str:
    return "( " + ", ".join(_q(a) for a in algs) + " )"


@dataclass
class GnbIdentity:
    gnb_id: int = 0xE00
    name: str = "gNB-OAI"
    mcc: int = 208
    mnc: int = 99
    tac: int = 1
    nr_cellid: int = 12345678
    pci: int = 0
    band: int = 78
    arfcn: int = 641280
    amf_ip: str = "192.168.70.132"
    ng_ip: str = "192.168.70.129"
    vendor: str = "oai"


@dataclass
class SecuritySettings:
    ciphering_algorithms: list = field(default_factory=lambda: ["nea2", "nea1", "nea0"])
    integrity_algorithms: list = field(default_factory=lambda: ["nia2", "nia1"])
    drb_ciphering: str = "yes"
    drb_integrity: str = "no"
    f1c_protection: str = "dtls"
    n2_protection: str = "ipsec"
    n3_protection: str = "ipsec"
    xn_protection: str = "ipsec"
    e2_protection: str = "ipsec"
    o1_transport: str = "netconf_tls"
    tls_min_version: str = "1.3"


def render(ident: GnbIdentity, sec: SecuritySettings, *, extra_comments: dict | None = None,
           field_order: str = "oai", extra_params: dict | None = None) -> str:
    """Render a full config file.

    ``extra_comments`` maps a hook name to comment text (used by metamorphic tests and the
    comment-injection attack). ``field_order`` = "oai" | "alt" changes group order without
    changing semantics. ``extra_params`` adds harmless non-security settings.
    """
    c = extra_comments or {}
    ep = extra_params or {}

    header = f"""Active_gNBs = ( {_q(ident.name)});
# Asn1_verbosity, choice in: none, info, annoying
Asn1_verbosity = "none";
"""
    gnbs = f"""
gNBs =
(
 {{
    ////////// Identification parameters:
    gNB_ID    =  0x{ident.gnb_id:X};
    gNB_name  =  {_q(ident.name)};

    // Tracking area code, 0x0000 and 0xfffe are reserved values
    tracking_area_code  =  {ident.tac};
    plmn_list = ({{ mcc = {ident.mcc}; mnc = {ident.mnc}; mnc_length = 2; snssaiList = ({{ sst = 1; }}) }});

    nr_cellid = {ident.nr_cellid}L;

    ////////// Physical parameters:
    min_rxtxtime = 6;

    servingCellConfigCommon = (
    {{
 #spCellConfigCommon
      physCellId                                                    = {ident.pci};
#  downlinkConfigCommon
    #frequencyInfoDL
      # this is 3600 MHz + 43 PRBs@30kHz SCS (same as initial BWP)
      absoluteFrequencySSB                                          = {ident.arfcn + 360};
      dl_frequencyBand                                              = {ident.band};
      # this is 3600 MHz
      dl_absoluteFrequencyPointA                                    = {ident.arfcn};
      #scs-SpecificCarrierList
        dl_offstToCarrier                                           = 0;
# subcarrierSpacing
# 0=kHz15, 1=kHz30, 2=kHz60, 3=kHz120
        dl_subcarrierSpacing                                        = 1;
        dl_carrierBandwidth                                         = 106;
      ssb_periodicityServingCell                                    = 2;
      dmrs_TypeA_Position                                           = 0;
      subcarrierSpacing                                             = 1;
      ssPBCH_BlockPower                                             = -25;
    }}
  );

    ////////// AMF parameters:
    amf_ip_address = ({{ ipv4 = {_q(ident.amf_ip)}; }});

    NETWORK_INTERFACES :
    {{
        GNB_IPV4_ADDRESS_FOR_NG_AMF              = {_q(ident.ng_ip + '/24')};
        GNB_IPV4_ADDRESS_FOR_NGU                 = {_q(ident.ng_ip + '/24')};
        GNB_PORT_FOR_S1U                         = 2152; # Spec 2152
    }};
 }}
);
"""
    macrlc = """
MACRLCs = (
  {
    num_cc                      = 1;
    tr_s_preference             = "local_L1";
    tr_n_preference             = "local_RRC";
    pusch_TargetSNRx10          = 150;
    pucch_TargetSNRx10          = 200;
  }
);

L1s = (
  {
    num_cc = 1;
    tr_n_preference = "local_mac";
    prach_dtx_threshold = 120;
    pucch0_dtx_threshold = 150;
    ofdm_offset_divisor = 8; #set this to UINT_MAX for offset 0
  }
);
"""
    extra = ""
    if ep:
        extra = "\n" + "\n".join(f"{k} = {_q(v) if isinstance(v, str) else v};" for k, v in ep.items()) + "\n"

    sec_block = f"""
security = {{
  {c.get('security_top', '').strip()}
  # preferred ciphering algorithms
  # the first one of the list that an UE supports in chosen
  # valid values: nea0, nea1, nea2, nea3
  ciphering_algorithms = {_alg_list(sec.ciphering_algorithms)};

  # preferred integrity algorithms
  # the first one of the list that an UE supports in chosen
  # valid values: nia0, nia1, nia2, nia3
  integrity_algorithms = {_alg_list(sec.integrity_algorithms)};

  # setting 'drb_ciphering' to "no" disables ciphering for DRBs, no matter
  # what 'ciphering_algorithms' configures; same thing for 'drb_integrity'
  drb_ciphering = {_q(sec.drb_ciphering)};
  drb_integrity = {_q(sec.drb_integrity)};
}};
"""
    iface_block = f"""
# sectwin extension: interface protection settings (not part of upstream OAI)
interface_security = {{
  {c.get('iface_top', '').strip()}
  f1c_protection  = {_q(sec.f1c_protection)};   # dtls | ipsec | none
  n2_protection   = {_q(sec.n2_protection)};   # dtls | ipsec | none
  n3_protection   = {_q(sec.n3_protection)};   # ipsec | none
  xn_protection   = {_q(sec.xn_protection)};   # dtls | ipsec | none
  e2_protection   = {_q(sec.e2_protection)};   # ipsec | none
  o1_transport    = {_q(sec.o1_transport)};   # netconf_ssh | netconf_tls | netconf_plain
  tls_min_version = {_q(sec.tls_min_version)};   # 1.0 | 1.1 | 1.2 | 1.3
}};
"""
    logs = """
log_config :
{
  global_log_level                      ="info";
  hw_log_level                          ="info";
  phy_log_level                         ="info";
  mac_log_level                         ="info";
  rlc_log_level                         ="info";
  pdcp_log_level                        ="info";
  rrc_log_level                         ="info";
  ngap_log_level                        ="debug";
  f1ap_log_level                        ="debug";
};
"""
    top = c.get("file_top", "")
    top = (top.strip() + "\n") if top else ""
    if field_order == "alt":
        body = header + sec_block + iface_block + gnbs + macrlc + logs + extra
    else:
        body = header + gnbs + macrlc + sec_block + iface_block + logs + extra
    return top + body
