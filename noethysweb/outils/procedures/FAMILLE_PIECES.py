import logging

from outils.views.procedures import BaseProcedure
from core.models import Piece, Rattachement

logger = logging.getLogger(__name__)


class Procedure(BaseProcedure):
    def Arguments(self, parser=None):
        """
        Assigne automatiquement une famille aux pièces qui n'en ont pas,
        en remontant via la table Rattachement de l'individu associé.
        """
        pass

    def Executer(self, variables=None):
        total_mises_a_jour = 0
        total_orphelines = 0
        erreurs = []

        # 1. Récupération des pièces en anomalie
        pieces_a_corriger = Piece.objects.filter(
            famille__isnull=True,
            individu__isnull=False
        ).select_related('individu')

        for piece in pieces_a_corriger:
            try:
                individu = piece.individu

                # 2. Recherche du rattachement de l'individu à une famille
                # On trie par 'titulaire' descendant pour récupérer le dossier principal en premier
                rattachement = Rattachement.objects.filter(
                    individu=individu,
                    famille__isnull=False
                ).order_by('-titulaire').first()

                if rattachement and rattachement.famille:
                    # 3. Affectation et sauvegarde ciblée
                    piece.famille = rattachement.famille
                    piece.save(update_fields=['famille'])
                    total_mises_a_jour += 1
                else:
                    total_orphelines += 1
                    logger.warning(
                        f"Aucun rattachement trouvé pour l'individu ID {individu.pk} "
                        f"(Pièce ID {piece.idpiece})"
                    )

            except Exception as e:
                erreurs.append(f"Erreur pour la pièce {piece.idpiece} : {e}")
                logger.exception(f"Erreur lors de la mise à jour de la pièce {piece.idpiece}")

        # 4. Rapport d'exécution final
        resultat = f"Nombre de pièces associées avec succès à une famille : {total_mises_a_jour}"

        if total_orphelines > 0:
            resultat += f"\nNombre de pièces impossibles à lier (individus sans rattachement) : {total_orphelines}"

        if erreurs:
            resultat += "\n\nErreurs rencontrées :\n" + "\n".join(erreurs)

        return resultat