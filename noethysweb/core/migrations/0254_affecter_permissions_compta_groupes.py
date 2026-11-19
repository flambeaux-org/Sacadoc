# -*- coding: utf-8 -*-
#  Affectation des nouvelles permissions de comptabilité.
#  Les migrations 0252 et 0253 ne regardaient que les permissions attribuées directement
#  aux utilisateurs ; or ici elles passent par des groupes. On rattrape les deux cas.

from django.db import migrations


# Permissions à distribuer à qui possède déjà la permission de référence
NOUVELLES_PERMISSIONS = [
    "verification_compta_liste",
    "correction_compte",
    "liste_ventilation",
    "rapprochements_liste",
    "operations_budgetaires_liste",
]

PERMISSION_REFERENCE = "operations_tresorerie_liste"


def affecter(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    Utilisateur = apps.get_model("core", "Utilisateur")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct = ContentType.objects.get_for_model(Utilisateur)

    reference = Permission.objects.filter(codename=PERMISSION_REFERENCE, content_type=ct).first()
    if not reference:
        return

    nouvelles = list(Permission.objects.filter(codename__in=NOUVELLES_PERMISSIONS, content_type=ct))
    if not nouvelles:
        return

    # Groupes qui ont déjà accès aux opérations de trésorerie
    for groupe in Group.objects.filter(permissions=reference):
        groupe.permissions.add(*nouvelles)

    # Utilisateurs qui ont la permission attribuée en direct
    for utilisateur in Utilisateur.objects.filter(is_active=True, user_permissions=reference):
        utilisateur.user_permissions.add(*nouvelles)


def retirer(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    Utilisateur = apps.get_model("core", "Utilisateur")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.get_for_model(Utilisateur)

    nouvelles = list(Permission.objects.filter(codename__in=NOUVELLES_PERMISSIONS, content_type=ct))
    if not nouvelles:
        return
    for groupe in Group.objects.all():
        groupe.permissions.remove(*nouvelles)
    for utilisateur in Utilisateur.objects.all():
        utilisateur.user_permissions.remove(*nouvelles)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0253_permissions_compta_manquantes"),
    ]

    operations = [
        migrations.RunPython(affecter, retirer),
    ]
