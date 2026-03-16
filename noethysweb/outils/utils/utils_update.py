# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, os, datetime, codecs, zipfile, requests, subprocess, glob

logger = logging.getLogger(__name__)

from noethysweb import version
from django.core.management import call_command
from django.conf import settings
from django.core.cache import cache
from django.utils.html import format_html_join

def Get_update_for_accueil(request=None):
    """Recherche si une nouvelle version est disponible"""
    key_cache = "last_check_update"
    version_cache = cache.get(key_cache)
    if version_cache:
        nouvelle_version = version_cache["nouvelle_version"]
    if not version_cache:
        nouvelle_version = search_update()
        cache.set(key_cache, {"nouvelle_version": nouvelle_version}, timeout=60 * 60)
    return nouvelle_version

def _check_release(release):
    version_online_tuple = version.GetVersionTuple(release["tag_name"])
    logger.debug("version disponible =" + release["tag_name"])

    # Lecture version actuelle
    version_actuelle_txt = version.GetVersion()
    version_actuelle_tuple = version.GetVersionTuple(version_actuelle_txt)
    logger.debug("version actuelle =" + version_actuelle_txt)

    # Comparaison des versions
    if version_online_tuple <= version_actuelle_tuple:
        logger.debug("Pas de nouvelle version disponible")
        return

    return release["tag_name"]

def search_update():
    """Recherche une nouvelle version de l'application sur GitHub et retourne son numéro de version si elle est plus récente que la version actuelle."""
    logger.debug("Récupération de la dernière version...")
    try:
        r = requests.get("https://api.github.com/repos/flambeaux-org/Sacadoc/releases/latest", timeout=10)
        r.raise_for_status()
    except requests.exceptions.RequestException:
        logger.debug("La version n'a pas pu être récupérée.")
        return

    release = r.json()
    return _check_release(release)


def get_changelog():
    """Récupère le changelog des 30 dernières versions et le tag de la dernière version si elle est plus récette que la courante."""
    logger.debug("Récupération du changelog des 30 dernières versions...")
    try:
        r = requests.get("https://api.github.com/repos/flambeaux-org/Sacadoc/releases?per_page=30", timeout=10)
        r.raise_for_status()
    except requests.exceptions.RequestException:
        logger.debug("Le changelog n'a pas pu être récupéré.")
        return
    releases = r.json()
    changelog = ""
    for release in releases:
        changelog += f"Version {release['tag_name']} - {release['published_at']} - {release['author']['login']}\n{release['body']}\n\n"

    changelog = format_html_join(
        "\n\n", "<a href='{}' target='_blank'>Version {}</a> - {} - {}\n{}", ((release["html_url"], release["tag_name"], release["published_at"], release["author"]["login"], release["body"]) for release in releases))

    latest_version = _check_release(releases[0])
    return latest_version, changelog


def backup_database():
    """Crée une sauvegarde de la base de données avec un timestamp dans le nom en utilisant la commande SQLite backup."""
    # Récupération du chemin de la base de données
    databases = settings.DATABASES
    if "default" not in databases:
        logger.debug("Aucune base de données 'default' trouvée.")
        return False

    db_config = databases["default"]

    # On ne fait la sauvegarde que pour SQLite
    if db_config.get("ENGINE") != "django.db.backends.sqlite3":
        logger.debug("La sauvegarde automatique n'est supportée que pour SQLite.")
        return False

    db_path = db_config.get("NAME")
    if not db_path or not os.path.isfile(db_path):
        logger.debug(f"Fichier de base de données non trouvé: {db_path}")
        return False

    # Création du nom de fichier avec timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    db_dir = os.path.dirname(db_path)
    db_filename = os.path.basename(db_path)
    db_name, db_ext = os.path.splitext(db_filename)
    backup_filename = f"{db_name}_backup_{timestamp}{db_ext}"
    backup_path = os.path.join(db_dir, backup_filename)

    try:
        logger.debug(
            f"Sauvegarde de la base de données avec SQLite backup: {db_path} -> {backup_path}"
        )

        # Utilisation de la commande backup de SQLite via CLI
        # Exécution de: sqlite3 db_path ".backup backup_path"
        result = subprocess.run(
            ["sqlite3", db_path, f".backup {backup_path}"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
        )

        if result.returncode != 0:
            logger.error(f"Erreur lors de la sauvegarde SQLite: {result.stderr}")
            return False

        logger.debug("Sauvegarde de la base de données terminée avec succès.")

        # Nettoyage: garder seulement les 5 derniers backups
        cleanup_old_backups(db_dir, db_name, db_ext)

        return backup_path
    except subprocess.TimeoutExpired:
        logger.error(
            "La sauvegarde de la base de données a dépassé le délai d'attente (5 minutes)."
        )
        return False
    except FileNotFoundError:
        logger.error(
            "La commande sqlite3 n'a pas été trouvée. Assurez-vous que SQLite est installé."
        )
        return False
    except Exception as err:
        logger.error(f"Erreur lors de la sauvegarde de la base de données: {err}")
        return False


def cleanup_old_backups(db_dir, db_name, db_ext, max_backups=5):
    """Supprime les anciens backups en ne gardant que les max_backups plus récents."""
    try:
        # Recherche tous les fichiers de backup
        pattern = os.path.join(db_dir, f"{db_name}_backup_*{db_ext}")
        backup_files = glob.glob(pattern)

        if len(backup_files) <= max_backups:
            logger.debug(
                f"Nombre de backups ({len(backup_files)}) <= {max_backups}, pas de nettoyage nécessaire."
            )
            return

        # Trier par date de modification (du plus ancien au plus récent)
        backup_files.sort(key=os.path.getmtime)

        # Supprimer les plus anciens pour ne garder que max_backups
        files_to_delete = backup_files[:-max_backups]

        for file_path in files_to_delete:
            logger.debug(f"Suppression de l'ancien backup: {file_path}")
            os.remove(file_path)

        logger.debug(
            f"Nettoyage terminé. {len(files_to_delete)} backup(s) supprimé(s)."
        )
    except Exception as err:
        logger.error(f"Erreur lors du nettoyage des anciens backups: {err}")


def _manual_update():
    # Recherche une version disponible
    try:
        r = requests.get("https://api.github.com/repos/flambeaux-org/Sacadoc/releases/latest", timeout=10)
        r.raise_for_status()
    except requests.exceptions.RequestException:
        logger.debug("La version n'a pas pu être récupérée.")
        return

    release = r.json()
    latest_version = _check_release(release)
    if not latest_version:
        return False

    # Téléchargement du zip
    rep_temp = os.path.join(settings.MEDIA_ROOT, "temp")
    if not os.path.isdir(rep_temp):
        os.mkdir(rep_temp)
    chemin_fichier = os.path.join(rep_temp, f"Sacadoc-{latest_version}.zip")

    try:
        logger.debug("Telechargement de la version %s..." % latest_version)
        r = requests.get(release["zipball_url"], allow_redirects=True, timeout=30, stream=True)
        r.raise_for_status()

        with open(chemin_fichier, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024): # 1M chunks
                f.write(chunk)
    except Exception as err:
        logger.debug(
            "La nouvelle version '%s' n'a pas pu etre telechargee." % latest_version
        )
        logger.debug(err)
        return False

    # Backup de la db
    logger.debug("Sauvegarde de la base de données avant mise à jour...")
    backup_result = backup_database()
    if backup_result:
        logger.debug(f"Sauvegarde créée: {backup_result}")
    else:
        logger.warning(
            "La sauvegarde de la base de données a échoué ou n'est pas supportée."
        )

    # Dezippage
    logger.debug("Dezippage du zip...")
    zfile = zipfile.ZipFile(chemin_fichier, "r")
    liste_fichiers = zfile.namelist()

    # Remplacement des fichiers
    prefixe = f"Sacadoc-{latest_version}/noethysweb/"
    chemin_dest = os.path.join(settings.BASE_DIR, "")

    logger.debug("Installation des nouveaux fichiers...")
    for i in liste_fichiers:
        d = i.replace(prefixe, "")
        if len(d) > 1 and not d.startswith(f"Sacadoc-{latest_version}"):
            if i.endswith("/"):
                os.makedirs(os.path.join(chemin_dest, d), exist_ok=True)

            else:
                os.makedirs(os.path.join(chemin_dest, os.path.dirname(d)), exist_ok=True)
                nom_fichier_temp = os.path.join(chemin_dest, d)

                # Remplace le dossier s'il existe déjà pour mettre un fichier à la place
                if os.path.isdir(nom_fichier_temp):
                    os.rmdir(nom_fichier_temp)

                data = zfile.read(i)
                with open(nom_fichier_temp, "wb") as fp:
                    fp.write(data)

    zfile.close()
    os.remove(chemin_fichier)
    logger.debug("Installation terminee.")

    # Efface le numéro de version du cache
    cache.delete("version_application")

    # AutoReloadWSGI
    logger.debug("AutoReloadWSGI...")
    AutoReloadWSGI()

    # Mise à jour du répertoire Static
    logger.debug("Collectstatic...")
    call_command("collectstatic", verbosity=0, interactive=False)

    # Mise à jour de la DB
    logger.debug("Migration DB...")
    call_command("migrate")

    # Mise à jour des permissions
    logger.debug("Mise à jour des permissions...")
    call_command("update_permissions")

    logger.debug("Mise a jour terminee.")
    return True

def _nanny_update():
    latest_version = search_update()
    if not latest_version:
        return False

    try:
        with open(settings.NANNY_PIPE, "w") as f:
            f.write(f"update {latest_version}")
    except Exception as err:
        logger.error(f"Erreur lors de l'envoi de la commande de mise à jour à Nanny: {err}")
        return False

def Update():
    if settings.UPDATE_USING_NANNY:
        return _nanny_update()
    return _manual_update()


def AutoReloadWSGI():
    """Reload le serveur en envoyant un SIGHUP à gunicorn ou en modifiant le fichier wsgi.py."""
    if (
        hasattr(settings, "GUNICORN_PIDFILE")
        and settings.GUNICORN_PIDFILE
        and os.path.isfile(settings.GUNICORN_PIDFILE)
    ):
        with open(settings.GUNICORN_PIDFILE) as pidfile:
            gunicorn_pid = int(pidfile.read())
        import signal

        logger.debug(f"Envoi de SIGHUP à {gunicorn_pid} pour reload le code")
        try:
            os.kill(gunicorn_pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        else:
            return

    nom_fichier = os.path.join(settings.BASE_DIR, "noethysweb/wsgi.py")
    # Lecture du fichier
    with open(nom_fichier, "r") as fichier_wsgi:
        liste_lignes_wsgi = fichier_wsgi.readlines()

    # Modification du fichier
    logger.debug(
        f"Modification de {nom_fichier} pour que l'autoreload du serveur reload le code"
    )
    with codecs.open(nom_fichier, "w") as fichier_wsgi:
        for ligne in liste_lignes_wsgi:
            if ligne.startswith("# lastupdate"):
                ligne = "# lastupdate = %s" % datetime.datetime.now()
            fichier_wsgi.write(ligne)


if __name__ == "__main__":
    Update()
