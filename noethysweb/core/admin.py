#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from core.models import Utilisateur, Structure
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.models import Permission, Group
from django import forms
from django.utils.html import format_html
from core.views.login import genereate_login_link

# --------------------------- Groupes d'utilisateurs ----------------------------

class GroupAdminForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.exclude(name__startswith='Can').order_by("name"), label="Permissions",
        widget=admin.widgets.FilteredSelectMultiple('permissions', False))

    class Meta:
        model = Group
        exclude = ()


class MyGroupAdmin(admin.ModelAdmin):
    form = GroupAdminForm


admin.site.unregister(Group)
admin.site.register(Group, MyGroupAdmin)


# --------------------------- Modification du formulaire (permissions)  ----------------------------

class UserEditForm(UserChangeForm):
    user_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.exclude(name__startswith='Can').order_by("name"), label="Permissions",
        widget=admin.widgets.FilteredSelectMultiple('permissions', False), required=False)

    structures_admin = forms.ModelMultipleChoiceField(
        queryset=Structure.objects_all.all().order_by("nom"), label="Structures",
        widget=admin.widgets.FilteredSelectMultiple('structures', False), required=False)

    class Meta:
        model = Utilisateur
        exclude = []


# --------------------------- Utilisateurs ----------------------------

@admin.register(Utilisateur_Utilisateur)
class UtilisateurAdmin(UserAdmin):
    form = UserEditForm

    # Ajoute la colonne is_active dans la liste des utilisateurs
    list_display = UserAdmin.list_display + ('is_active', "login_link")

    # Affichage des champs
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Informations personnelles', {'fields': ('first_name', 'last_name', 'email')}),
        ('Activation du compte', {'fields': ('is_active',)}),
        ('Permissions accordées', {'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Structures accessibles', {'fields': ('structures_admin',), 'description': "Sélectionnez les structures accessibles par cet utilisateur."}),
        ('Options', {'fields': ('adresse_exp', 'signature')}),
        ('Dates importantes', {'fields': ('last_login', 'date_joined')})
    )

    def get_queryset(self, request):
        # Stock request for usage in login_link
        self._request = request
        qs = super().get_queryset(request)
        return qs.filter(categorie="utilisateur")

    @admin.display(description="Connexion")
    def login_link(self, obj):
        """Display a login as user link."""
        if not self._request:
            return "-"
        link = genereate_login_link(self._request, obj)
        return format_html('<a href="{}">Se connecter</a>', link)

class Utilisateur_Utilisateur(Utilisateur):
    class Meta:
        proxy = True
        verbose_name = "Utilisateur"



# --------------------------- Familles ----------------------------

@admin.register(Utilisateur_Famille)
class FamilleAdmin(UserAdmin):
    form = UserEditForm

    # Affiche uniquement les colonnes suivantes dans la liste
    list_display = ('username', 'email', 'is_active')

    # Affiche uniquement les filtres suivants
    list_filter = ('is_active',)

    # Affiche uniquement les champs suivants
    fieldsets = (
        (None, {'fields': ('username', 'password', 'email')}),
        ('Permissions', {'fields': ('is_active', 'user_permissions')}),
        ('Dates importantes', {'fields': ('last_login', 'date_joined')})
    )

    def get_queryset(self, request):
        """ Affiche uniquement les utilisateurs de type famille """
        qs = super().get_queryset(request)
        return qs.filter(categorie="famille")

    def has_add_permission(self, request):
        """ Empêche l'ajout d'un utilisateur famille """
        return False

    def has_delete_permission(self, request, obj=None):
        """ Empêche la suppression d'un utilisateur famille """
        return False


class Utilisateur_Famille(Utilisateur):
    class Meta:
        proxy = True
        verbose_name = "Famille"


