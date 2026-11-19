#  La liste des virements internes est désormais contrôlée par la permission
#  "virements_liste" (elle n'avait pas de menu_code). Comme en 0254, on l'accorde à
#  ceux qui ont déjà accès aux opérations de trésorerie, pour ne retirer l'accès à personne.

from django.db import migrations

PERMISSION = "virements_liste"
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
    permission, _ = Permission.objects.get_or_create(
        codename=PERMISSION, content_type=ct,
        defaults={"name": "Comptabilité | Liste des virements interne"})

    for groupe in Group.objects.filter(permissions=reference):
        groupe.permissions.add(permission)
    for utilisateur in Utilisateur.objects.filter(is_active=True, user_permissions=reference):
        utilisateur.user_permissions.add(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0258_permissions_compta_hors_menu"),
    ]

    operations = [
        # Pas de retour arrière : on ne sait pas qui avait déjà la permission avant
        migrations.RunPython(affecter, migrations.RunPython.noop),
    ]
