from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

import dns.resolver
import dns.exception


def validate_email_domain_mx(value):
    if not value or "@" not in value:
        return
    domain = value.rsplit("@", 1)[1].lower()
    try:
        dns.resolver.resolve(domain, "MX")
        return
    except dns.resolver.NXDOMAIN:
        raise ValidationError(
            _("Le domaine « %(domain)s » n'existe pas. Vérifiez l'adresse email saisie."),
            params={"domain": domain},
        )
    except dns.resolver.NoAnswer:
        # Pas de MX — essai fallback A record (RFC 5321)
        try:
            dns.resolver.resolve(domain, "A")
            return
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            raise ValidationError(
                _("Le domaine « %(domain)s » ne peut pas recevoir d'emails. Vérifiez l'adresse saisie."),
                params={"domain": domain},
            )
        except dns.exception.DNSException:
            return  # Fail open sur erreur réseau
    except dns.exception.DNSException:
        return  # Fail open sur erreur réseau (timeout, etc.)
