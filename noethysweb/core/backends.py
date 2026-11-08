from django.contrib.auth.backends import ModelBackend, UserModel

from core.models import Individu, Rattachement


class EmailModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or password is None:
            return
        try:
            user = UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            # Sous SQLite, iexact est traduit en LIKE, qui n'est insensible
            # à la casse que pour les caractères ASCII.
            rattachement = (
                Rattachement.objects.select_related("famille__utilisateur")
                .filter(individu__mail__iexact=username, famille__utilisateur__isnull=False)
                .exclude(individu__statut=Individu.STATUT_JEUNE)
                .order_by("individu", "pk")
                .first()
            )
            if rattachement is None:
                # Run the default password hasher once to reduce the timing
                # difference between an existing and a nonexistent user (#20760).
                UserModel().set_password(password)
                return
            user = rattachement.famille.utilisateur

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
