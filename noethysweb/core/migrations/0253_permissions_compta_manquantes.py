# -*- coding: utf-8 -*-
#  Création des permissions de comptabilité absentes de la base.
#  Ces pages n'avaient aucun contrôle de permission (menu_code manquant) ; maintenant
#  qu'elles en ont un, leur permission doit exister sinon plus personne n'y accède.

from django.db import migrations


# codename -> libellé
PERMISSIONS = {
    "correction_compte": "Comptabilité | Correction du compte d'une opération",
    "liste_ventilation": "Comptabilité | Liste des opérations par catégorie",
    "rapprochements_liste": "Comptabilité | Rapprochement bancaire",
    "operations_budgetaires_liste": "Comptabilité | Liste des opérations budgétaires",
}

# Permission de référence : qui l'a déjà, reçoit les nouvelles
PERMISSION_REFERENCE = "operations_tresorerie_liste"


def creer_permissions_compta(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Utilisateur = apps.get_model("core", "Utilisateur")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct = ContentType.objects.get_for_model(Utilisateur)

    perm_reference = Permission.objects.filter(codename=PERMISSION_REFERENCE, content_type=ct).first()
    utilisateurs = []
    if perm_reference:
        utilisateurs = list(Utilisateur.objects.filter(is_active=True, user_permissions=perm_reference))

    for codename, name in PERMISSIONS.items():
        perm, created = Permission.objects.get_or_create(
            codename=codename, content_type=ct, defaults={"name": name}
        )
        for user in utilisateurs:
            user.user_permissions.add(perm)


def supprimer_permissions_compta(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Utilisateur = apps.get_model("core", "Utilisateur")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.get_for_model(Utilisateur)
    Permission.objects.filter(codename__in=list(PERMISSIONS), content_type=ct).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0252_permission_verification_compta"),
    ]

    operations = [
        migrations.RunPython(creer_permissions_compta, supprimer_permissions_compta),
    ]
