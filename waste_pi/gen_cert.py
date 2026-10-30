# gen_cert.py — ينشئ شهادة HTTPS للسيرفر (مرة وحدة على اللابتوب)
# الاستخدام:  python gen_cert.py 192.168.1.20      (حط IP اللابتوب)
# بعدها انسخ cert.pem للرازبيري. أما key.pem فيبقى على اللابتوب فقط

import datetime
import ipaddress
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

if len(sys.argv) != 2:
    raise SystemExit("اكتب IP اللابتوب، مثال: python gen_cert.py 192.168.1.20")
ip = ipaddress.ip_address(sys.argv[1])

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(ip))])
now = datetime.datetime.now(datetime.timezone.utc)
cert = (
    x509.CertificateBuilder()
    .subject_name(name).issuer_name(name)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(minutes=5))
    .not_valid_after(now + datetime.timedelta(days=365))
    .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip)]), critical=False)
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    # إضافات مطلوبة في بايثون 3.13 (التحقق الصارم من الشهادات)
    .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
    .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, key_cert_sign=True,
                                 content_commitment=False, data_encipherment=False, key_agreement=False,
                                 crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
    .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    .sign(key, hashes.SHA256())
)

with open("key.pem", "wb") as f:
    f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                              serialization.NoEncryption()))
with open("cert.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))
print(f"تم للـ IP {ip}: cert.pem (ينسخ للرازبيري) و key.pem (يبقى على اللابتوب فقط)")
