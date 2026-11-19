# -*- coding: utf-8 -*-
#  Création et affectation de la permission de la page "Vérification comptable".

from django.db import migrations


def affecter_permission_verification(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Utilisateur = apps.get_model("core", "Utilisateur")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct = ContentType.objects.get_for_model(Utilisateur)

    perm, created = Permission.objects.get_or_create(
        codename="verification_compta_liste",
        content_type=ct,
        defaults={"name": "Comptabilité | Vérification comptable"},
    )

    # On l'affecte aux utilisateurs qui ont déjà accès aux opérations de trésorerie
    perm_tresorerie = Permission.objects.filter(codename="operations_tresorerie_liste", content_type=ct).first()
    if perm_tresorerie:
        for user in Utilisateur.objects.filter(is_active=True, user_permissions=perm_tresorerie):
            user.user_permissions.add(perm)


def supprimer_permission_verification(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Utilisateur = apps.get_model("core", "Utilisateur")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.get_for_model(Utilisateur)
    Permission.objects.filter(codename="verification_compta_liste", content_type=ct).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0251_comptaoperation_verification"),
    ]

    operations = [
        migrations.RunPython(affecter_permission_verification, supprimer_permission_verification),
    ]
