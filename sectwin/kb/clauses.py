"""Clause knowledge base.

IMPORTANT - provenance of the text below
* ``TS33.501-*``: paraphrases of 3GPP TS 33.501 requirements written for this project
  from a reading of a third-party mirror. They are NOT verbatim 3GPP text. Status
  ``paraphrase-unverified``. Before any result is published, each must be replaced by
  the exact sentence from the official specification (the quote check C3 then works on
  the official text unchanged).
* ``ORAN-WG11-*``: requirement-level paraphrases of O-RAN WG11 security requirements.
  Identifiers are project-local, not official requirement numbers. ``paraphrase-unverified``.
* ``OSB-*``: the project's synthetic Operator Security Baseline. ``synthetic-policy``.
* Distractor clauses (UE, AMF, NAS, key hierarchy) are included so retrieval has to
  discriminate, as in the proposal's Appendix B.

Every chunk is hashed; the manifest of hashes is the trusted corpus that the
provenance defence (E3) checks against.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict

NORMATIVE_RE = re.compile(r"\b(shall not|shall|should not|should|may|is optional|optional to use)\b", re.I)


@dataclass
class Clause:
    clause_id: str
    doc: str
    title: str
    text: str
    status: str
    version: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(f"{self.clause_id}\n{self.text}".encode()).hexdigest()

    def sentences(self) -> list[str]:
        return [s.strip() for s in re.split(r"(?<=[.;])\s+", self.text) if s.strip()]

    def to_dict(self):
        d = asdict(self)
        d["sha256"] = self.sha256
        return d


P = "paraphrase-unverified"
S = "synthetic-policy"
V33 = "V18.x (mirror reading)"
VOR = "R003-v09 family (requirement-level paraphrase)"
VOSB = "OSB v1.0 (project)"

CLAUSES: list[Clause] = [
    # ---------------------------------------------------------------- gNB, AS security
    Clause("TS33.501-5.3.2", "3GPP TS 33.501", "User data and signalling data confidentiality (gNB)",
           "The gNB shall support ciphering of user data between the UE and the gNB. "
           "The gNB shall support ciphering of RRC signalling. "
           "Confidentiality protection of user data and of RRC signalling is optional to use, and the decision to activate it is taken by the operator. "
           "Selecting NEA0 results in no confidentiality protection.", P, V33),
    Clause("TS33.501-5.3.3", "3GPP TS 33.501", "User data and signalling data integrity (gNB)",
           "The gNB shall support integrity protection and replay protection of user data between the UE and the gNB. "
           "The gNB shall support integrity protection and replay protection of RRC signalling. "
           "Integrity protection of user data is optional to use. "
           "When integrity protection of user data is used, NIA0 shall not be used. "
           "RRC signalling shall use an integrity protection algorithm other than NIA0, except for unauthenticated emergency calls. "
           "NIA0 shall be disabled in a gNB in deployments where support of unauthenticated emergency sessions is not a regulatory requirement.",
           P, V33),
    Clause("TS33.501-5.3.4", "3GPP TS 33.501", "Requirements for the gNB setup and configuration",
           "Setting up and configuring gNBs shall be authenticated and authorized so that attackers are not able to modify the gNB settings and software configurations via local or remote access. "
           "Security associations shall be required between the 5G core and the gNB. "
           "The gNB shall support secure storage of keys and sensitive configuration data.", P, V33),
    Clause("TS33.501-6.7.3", "3GPP TS 33.501", "AS security mode command procedure and algorithm selection",
           "Each gNB shall be configured via network management with lists of algorithms which are allowed for usage, one list for integrity algorithms and one for ciphering algorithms, ordered by priority. "
           "When AS security context is established, the gNB shall choose a ciphering algorithm which has the highest priority in its configured list and is also present in the UE security capabilities. "
           "The gNB shall choose an integrity algorithm which has the highest priority in its configured list and is also present in the UE security capabilities. "
           "The chosen algorithms shall be indicated to the UE in the AS security mode command message.", P, V33),
    Clause("TS33.501-6.7.3.1", "3GPP TS 33.501", "Algorithm selection at handover",
           "At handover the target gNB shall select the algorithm with the highest priority from its own locally configured list that is also present in the UE security capabilities. "
           "If the target gNB selects different algorithms than the source gNB, the selected algorithms shall be indicated to the UE in the handover command.", P, V33),
    Clause("TS33.501-10.2.2", "3GPP TS 33.501", "Unauthenticated emergency sessions",
           "For unauthenticated emergency sessions the network may use NEA0 and NIA0. "
           "The use of the null algorithms for emergency sessions shall be restricted to cases where the UE cannot be authenticated. "
           "Whether unauthenticated emergency sessions are supported is subject to regional regulatory requirements.", P, V33),
    Clause("TS33.501-D.1", "3GPP TS 33.501", "Null ciphering and integrity algorithms",
           "NEA0 and NIA0 provide no security. "
           "NIA0 shall not be used for signalling radio bearers except for unauthenticated emergency sessions. "
           "NIA0 shall not be used for data radio bearers. "
           "A UE that is not in limited service mode shall not accept a security mode command that selects NIA0.", P, V33),
    Clause("TS33.501-D.2", "3GPP TS 33.501", "Ciphering algorithms",
           "128-NEA1 is based on SNOW 3G, 128-NEA2 is based on AES in counter mode, and 128-NEA3 is based on ZUC. "
           "The UE and gNB shall implement NEA0, 128-NEA1 and 128-NEA2. "
           "The UE and gNB may implement 128-NEA3.", P, V33),
    Clause("TS33.501-D.3", "3GPP TS 33.501", "Integrity algorithms",
           "128-NIA1 is based on SNOW 3G, 128-NIA2 is based on AES in CMAC mode, and 128-NIA3 is based on ZUC. "
           "The UE and gNB shall implement 128-NIA1 and 128-NIA2. "
           "The UE and gNB may implement 128-NIA3.", P, V33),
    Clause("TS33.501-6.6.1", "3GPP TS 33.501", "UP security policy",
           "The SMF shall provide the user plane security policy for a PDU session to the gNB. "
           "The policy indicates whether user plane integrity protection and ciphering are required, preferred or not needed. "
           "The gNB shall activate user plane protection according to the received policy.", P, V33),
    # ---------------------------------------------------------------- interfaces
    Clause("TS33.501-9.2", "3GPP TS 33.501", "Security mechanisms for the N2 interface",
           "In order to protect the N2 reference point, it is required to implement IPsec ESP and IKEv2 certificate-based authentication. "
           "In addition DTLS shall be supported. "
           "For interfaces between 5G AN and 5GC that are in a trusted environment, protection may be omitted by operator decision.", P, V33),
    Clause("TS33.501-9.3", "3GPP TS 33.501", "Security mechanisms for the N3 interface",
           "In order to protect the N3 reference point, it is required to implement IPsec ESP and IKEv2 certificate-based authentication. "
           "The use of cryptographic protection on N3 is subject to operator policy.", P, V33),
    Clause("TS33.501-9.4", "3GPP TS 33.501", "Security mechanisms for the Xn interface",
           "In order to protect the Xn-C reference point, it is required to implement IPsec ESP and IKEv2 certificate-based authentication. "
           "DTLS shall be supported for Xn-C. "
           "Protection of Xn is not required where the interface is trusted, for example physically protected.", P, V33),
    Clause("TS33.501-9.8", "3GPP TS 33.501", "Security mechanisms for the F1 interface",
           "F1-C traffic shall support integrity, confidentiality and replay protection. "
           "IPsec ESP and IKEv2 certificate-based authentication shall be supported on F1-C; DTLS may be used in addition. "
           "Whether to use cryptographic protection on F1 within a physically secured environment is an operator decision.", P, V33),
    # ---------------------------------------------------------------- O-RAN WG11
    Clause("ORAN-WG11-O1-1", "O-RAN WG11 Security Requirements", "O1 interface transport security",
           "The O1 interface shall be protected for confidentiality, integrity and replay. "
           "NETCONF over SSH or NETCONF over TLS shall be used for O1 management sessions. "
           "Plaintext NETCONF shall not be used.", P, VOR),
    Clause("ORAN-WG11-TLS-1", "O-RAN WG11 Security Protocols", "TLS profile",
           "Implementations shall support TLS 1.2 and should support TLS 1.3. "
           "TLS 1.0 and TLS 1.1 shall not be negotiated. "
           "Cipher suites without forward secrecy should not be used.", P, VOR),
    Clause("ORAN-WG11-E2-1", "O-RAN WG11 Security Requirements", "E2 interface protection",
           "The E2 interface shall support confidentiality, integrity and replay protection. "
           "IPsec shall be supported on E2. "
           "The decision to enable protection on E2 inside a trusted domain is made by the operator.", P, VOR),
    Clause("ORAN-WG11-A1-1", "O-RAN WG11 Security Requirements", "A1 interface protection",
           "The A1 interface shall use mutual TLS authentication between the Non-RT RIC and the Near-RT RIC. "
           "OAuth 2.0 may be used for authorization of A1 services.", P, VOR),
    Clause("ORAN-WG11-OFH-1", "O-RAN WG11 Security Requirements", "Open fronthaul M-plane",
           "The open fronthaul M-plane shall use NETCONF over SSH or TLS. "
           "802.1X port-based network access control may be used on the fronthaul network.", P, VOR),
    Clause("ORAN-WG11-SMO-1", "O-RAN WG11 Security Requirements", "SMO and rApp security",
           "The SMO shall authenticate and authorize rApps before granting access to R1 services. "
           "Configuration changes pushed by the SMO shall be logged in a tamper-evident audit log.", P, VOR),
    # ---------------------------------------------------------------- Operator Security Baseline
    Clause("OSB-1", "Operator Security Baseline (project, synthetic)", "Null ciphering",
           "NEA0 shall not be configured on any gNB unless unauthenticated emergency sessions are a regulatory requirement. "
           "Where NEA0 is configured for emergency use, it shall have the lowest priority in the ciphering list. "
           "At least one of 128-NEA1, 128-NEA2 or 128-NEA3 shall be configured.", S, VOSB),
    Clause("OSB-2", "Operator Security Baseline (project, synthetic)", "User-plane ciphering",
           "Ciphering of data radio bearers shall be enabled on all gNBs. "
           "User-plane integrity protection may be enabled per slice and is not mandated by this baseline.", S, VOSB),
    Clause("OSB-3", "Operator Security Baseline (project, synthetic)", "Algorithm preference",
           "128-NEA2/128-NIA2 or 128-NEA3/128-NIA3 shall be the highest-priority algorithms. "
           "128-NEA1/128-NIA1 may be configured as a lower-priority fallback.", S, VOSB),
    Clause("OSB-4", "Operator Security Baseline (project, synthetic)", "Interface protection",
           "F1-C, N2, N3, Xn and E2 shall be cryptographically protected using IPsec or DTLS on every deployment, including deployments inside operator premises.", S, VOSB),
    Clause("OSB-5", "Operator Security Baseline (project, synthetic)", "TLS minimum version",
           "The minimum TLS version on management interfaces shall be TLS 1.3.", S, VOSB),
    # ---------------------------------------------------------------- distractors
    Clause("TS33.501-5.2.3", "3GPP TS 33.501", "User data and signalling data integrity (UE)",
           "The UE shall support integrity protection and replay protection of user data between the UE and the gNB. "
           "The UE shall implement NIA0 for integrity protection of NAS and RRC signalling. "
           "The UE shall support 128-NIA1 and 128-NIA2.", P, V33),
    Clause("TS33.501-5.2.2", "3GPP TS 33.501", "User data and signalling data confidentiality (UE)",
           "The UE shall support ciphering of user data between the UE and the gNB. "
           "The UE shall implement NEA0, 128-NEA1 and 128-NEA2 for ciphering.", P, V33),
    Clause("TS33.501-5.5.2", "3GPP TS 33.501", "Signalling data integrity (AMF)",
           "The AMF shall support integrity protection and replay protection of NAS signalling. "
           "NAS signalling shall be integrity protected with an algorithm other than NIA0 except for unauthenticated emergency calls.", P, V33),
    Clause("TS33.501-6.7.2", "3GPP TS 33.501", "NAS security mode command procedure",
           "The AMF shall select NAS algorithms with the highest priority from its configured lists that are present in the UE security capabilities. "
           "The NAS security mode command shall be integrity protected.", P, V33),
    Clause("TS33.501-6.2.1", "3GPP TS 33.501", "Key hierarchy",
           "KgNB is derived by the UE and the AMF from KAMF. "
           "KRRCint, KRRCenc, KUPint and KUPenc are derived from KgNB.", P, V33),
    Clause("TS33.501-6.9.2", "3GPP TS 33.501", "Key handling at handover",
           "At Xn handover the source gNB derives KgNB* using horizontal or vertical key derivation. "
           "The target gNB shall use KgNB* as the new KgNB.", P, V33),
    Clause("TS33.501-6.4.1", "3GPP TS 33.501", "NAS integrity mechanisms",
           "The NAS integrity algorithm input includes a 32-bit COUNT, a 5-bit bearer identity and a 1-bit direction.", P, V33),
    Clause("TS33.501-5.3.5", "3GPP TS 33.501", "Requirements for handling keys in the gNB",
           "Keys shall be stored in a secure environment in the gNB and shall never leave it except as specified.", P, V33),
    Clause("TS33.501-5.9.3", "3GPP TS 33.501", "Requirements for e2e core network interface security",
           "SEPP shall act as a non-transparent proxy node. "
           "N32 shall be protected with TLS or PRINS.", P, V33),
]

BY_ID = {c.clause_id: c for c in CLAUSES}


def manifest() -> dict:
    return {c.clause_id: c.sha256 for c in CLAUSES}


def normative_level(sentence: str) -> str:
    """Strongest normative keyword in a sentence -> shall_not | shall | should | may | optional | none."""
    s = sentence.lower()
    if re.search(r"\bshall not\b|\bmust not\b", s):
        return "shall_not"
    if re.search(r"\bshall\b|\bmust\b|\bis required\b|\bit is required\b", s):
        return "shall"
    if re.search(r"\bshould not\b|\bshould\b", s):
        return "should"
    if re.search(r"\boptional\b", s):
        return "optional"
    if re.search(r"\bmay\b", s):
        return "may"
    return "none"


def dump(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"clauses": [c.to_dict() for c in CLAUSES], "manifest": manifest()}, f, indent=2)
