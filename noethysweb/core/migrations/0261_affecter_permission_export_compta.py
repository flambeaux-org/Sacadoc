# -*- coding: utf-8 -*-
#  Affectation de la nouvelle permission "Comptabilité | Export compta".
#  Comme en 0254 et 0259, on l'accorde à qui dispose déjà d'une des pages d'analyse
#  comptable, en traitant à la fois les groupes et les permissions attribuées en direct.
#  La permission est créée ici (get_or_create) car le signal post_migrate qui la créerait
#  automatiquement ne s'exécute qu'une fois toutes les migrations passées.

from django.db import migrations


PERMISSION = "export_compta"
PERMISSION_LABEL = "Comptabilité | Export compta"

# Possède l'une de ces permissions => reçoit la nouvelle
PERMISSIONS_REFERENCE = ["suivi_compta", "liste_ventilation"]


def affecter(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    Utilisateur = apps.get_model("core", "Utilisateur")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct = ContentType.objects.get_for_model(Utilisateur)

    references = list(Permission.objects.filter(codename__in=PERMISSIONS_REFERENCE, content_type=ct))
    if not references:
        return

    permission, _ = Permission.objects.get_or_create(
        codename=PERMISSION, content_type=ct,
        defaults={"name": PERMISSION_LABEL})

    for groupe in Group.objects.filter(permissions__in=references).distinct():
        groupe.permissions.add(permission)

    for utilisateur in Utilisateur.objects.filter(is_active=True, user_permissions__in=references).distinct():
        utilisateur.user_permissions.add(permission)


def retirer(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    Utilisateur = apps.get_model("core", "Utilisateur")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct = ContentType.objects.get_for_model(Utilisateur)
    permission = Permission.objects.filter(codename=PERMISSION, content_type=ct).first()
    if not permission:
        return

    for groupe in Group.objects.filter(permissions=permission):
        groupe.permissions.remove(permission)
    for utilisateur in Utilisateur.objects.filter(user_permissions=permission):
        utilisateur.user_permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0260_permission_export_compta"),
    ]

    operations = [
        migrations.RunPython(affecter, retirer),
    ]
