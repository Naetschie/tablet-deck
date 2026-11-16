"""TLS für den WLAN-Zugang der Bridge.

Über WLAN laufen Maus und Tastatur des PCs durchs Heimnetz - ohne Verschlüsselung könnte jedes Gerät im
Netz mitlesen und die Verbindung (samt Kopplungs-Cookie) übernehmen. Deshalb eine eigene, zweistufige CA:
- tls/ca.crt: Wurzel. Der Hub schickt sie (mit inter.crt, ohne Schlüssel) beim Anstecken per ADB an den
  Launcher (hub_ca_bundle, HubTrust.java). Ihr Schlüssel wird nur einmal zum Ausstellen der Zwischen-CA
  benutzt und nie gespeichert.
- tls/inter.crt/inter.key: Zwischen-CA mit NameConstraints (nur private IPv4-Netze, als DNS-Name nur die
  Pseudo-Domain "invalid"). Android/PKIX setzt Constraints in Zwischenzertifikaten durch (in der Wurzel
  nicht) - selbst mit inter.key lassen sich keine Zertifikate für fremde Webseiten ausstellen. Zusätzlich
  prüft der Launcher die Kette nur für die WLAN-Adresse des Hubs (die Web-Kachel vertraut ihr nicht).
- Server-Zertifikat für die LAN-Adresse des PCs, neu ausgestellt bei Adresswechsel und vor Ablauf
  (das laufende SSLContext-Objekt lädt es nach).
tls/ liegt nicht im Git.
"""
import datetime
import ipaddress
import logging
import socket
import ssl
from pathlib import Path

log = logging.getLogger("tls")

SERVER_DAYS = 397
RENEW_DAYS = 30
PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]


def lan_ips():
    """LAN-Adresse dieses PCs: die Schnittstelle mit der Standardroute (keine virtuellen Adapter wie
    Hyper-V/WSL/VirtualBox). Ohne Standardroute alle privaten IPv4-Adressen."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))   # TEST-NET: es wird nichts gesendet, nur die Route bestimmt
            ip = ipaddress.ip_address(s.getsockname()[0])
            if any(ip in n for n in PRIVATE_NETS):
                return [str(ip)]
    except OSError:
        pass
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = ipaddress.ip_address(info[4][0])
            if any(ip in n for n in PRIVATE_NETS):
                ips.add(str(ip))
    except OSError:
        pass
    return sorted(ips)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _key_bytes(key):
    from cryptography.hazmat.primitives import serialization
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def _pem(cert):
    from cryptography.hazmat.primitives import serialization
    return cert.public_bytes(serialization.Encoding.PEM)


def _ca_usage():
    from cryptography import x509
    return x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                         data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                         encipher_only=False, decipher_only=False)


def ensure_ca(d: Path):
    """Zwischen-CA laden oder (samt Wurzel) einmalig erzeugen. Gibt (Zwischenzertifikat, Schlüssel) zurück."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    root_p, inter_p, key_p = d / "ca.crt", d / "inter.crt", d / "inter.key"
    if root_p.exists() and inter_p.exists() and key_p.exists():
        return (x509.load_pem_x509_certificate(inter_p.read_bytes()),
                serialization.load_pem_private_key(key_p.read_bytes(), None))
    d.mkdir(parents=True, exist_ok=True)
    host = socket.gethostname()
    root_key = ec.generate_private_key(ec.SECP256R1())
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Tablet Deck Root ({host})")])
    root = (x509.CertificateBuilder()
            .subject_name(root_name).issuer_name(root_name).public_key(root_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - datetime.timedelta(days=1))
            .not_valid_after(_now() + datetime.timedelta(days=7300))
            .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
            .add_extension(_ca_usage(), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False)
            .sign(root_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    inter = (x509.CertificateBuilder()
             .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Tablet Deck CA ({host})")]))
             .issuer_name(root_name).public_key(key.public_key())
             .serial_number(x509.random_serial_number())
             .not_valid_before(_now() - datetime.timedelta(days=1))
             .not_valid_after(_now() + datetime.timedelta(days=7299))
             .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
             .add_extension(_ca_usage(), critical=True)
             .add_extension(x509.NameConstraints(
                 permitted_subtrees=[x509.IPAddress(n) for n in PRIVATE_NETS] + [x509.DNSName("invalid")],
                 excluded_subtrees=None), critical=True)
             .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
             .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
                            critical=False)
             .sign(root_key, hashes.SHA256()))
    del root_key   # Wurzelschlüssel wird nie gespeichert
    key_p.write_bytes(_key_bytes(key))
    inter_p.write_bytes(_pem(inter))
    root_p.write_bytes(_pem(root))
    log.info("Neue WLAN-CA erzeugt (%s) - der Hub schickt sie beim nächsten Anstecken per USB ans Tablet", root_p)
    return inter, key


def issue_server_cert(d: Path, ips, extra_ips=()):
    """Server-Zertifikat ausstellen (tls/server.crt mit Kette, server.key). Gibt das Ablaufdatum zurück.
    extra_ips nur für Tests (z. B. eine öffentliche IP, die die Constraints verletzen muss)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    ca_cert, ca_key = ensure_ca(d)
    key = ec.generate_private_key(ec.SECP256R1())
    san = [x509.IPAddress(ipaddress.ip_address(i)) for i in list(ips) + list(extra_ips)]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Tablet Deck Bridge")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - datetime.timedelta(days=1))
            .not_valid_after(_now() + datetime.timedelta(days=SERVER_DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(san), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    (d / "server.key").write_bytes(_key_bytes(key))
    # Kette: Server + Zwischen-CA (die Wurzel hat der Launcher per ADB bekommen)
    (d / "server.crt").write_bytes(_pem(cert) + _pem(ca_cert))
    return cert.not_valid_after_utc


class ServerTLS:
    """SSLContext für den WLAN-Zugang; reload() stellt bei neuer LAN-Adresse oder vor Ablauf neu aus."""

    def __init__(self, d: Path):
        self.dir = d
        self.ips = []
        self.expires = None
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        self.reload()

    def reload(self):
        ips = lan_ips()
        due = self.expires is None or self.expires - _now() < datetime.timedelta(days=RENEW_DAYS)
        if ips == self.ips and not due:
            return False
        if not ips:
            log.warning("Keine private LAN-Adresse gefunden - WLAN-Zugang ohne gültiges Zertifikat")
            return False
        self.expires = issue_server_cert(self.dir, ips)
        self.ctx.load_cert_chain(self.dir / "server.crt", self.dir / "server.key")
        changed = ips != self.ips
        self.ips = ips
        log.info("WLAN-Zertifikat für %s (gültig bis %s)", ", ".join(ips), self.expires.date())
        return changed
