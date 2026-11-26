# -*- coding: utf-8 -*-
#  Création et affectation de la permission "Comptabilité | Bilan organisateur".
#
#  La migration 0262 ne fait qu'AlterModelOptions : elle déclare la permission dans le
#  modèle, mais ne crée pas la ligne en base (comme en 0259 et 0261, on la crée ici).
#  La page étant réservée au staff, seuls les utilisateurs is_staff la reçoivent.

from django.db import migrations
from django.db.models import Q

PERMISSION = "bilan_organisateur"
PERMISSION_LABEL = "Comptabilité | Bilan organisateur"
PERMISSION_REFERENCE = "suivi_compta"


def affecter(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Utilisateur = apps.get_model("core", "Utilisateur")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct = ContentType.objects.get_for_model(Utilisateur)
    permission, _ = Permission.objects.get_or_create(
        codename=PERMISSION, content_type=ct, defaults={"name": PERMISSION_LABEL})

    reference = Permission.objects.filter(codename=PERMISSION_REFERENCE, content_type=ct).first()
    if not reference:
        return

    # Staff disposant déjà du Bilan financier, en direct ou via un groupe
    candidats = Utilisateur.objects.filter(is_active=True, is_staff=True).filter(
        Q(user_permissions=reference) | Q(groups__permissions=reference)).distinct()
    for utilisateur in candidats:
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
        ("core", "0262_permission_bilan_organisateur"),
    ]

    operations = [
        migrations.RunPython(affecter, retirer),
    ]
