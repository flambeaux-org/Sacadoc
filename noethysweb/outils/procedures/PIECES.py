import logging

from outils.views.procedures import BaseProcedure
from core.models import Piece

logger = logging.getLogger(__name__)


class Procedure(BaseProcedure):
    def Arguments(self, parser=None):
        """
        Supprime les pièces qui ne possèdent aucun document.
        """
        pass

    def Executer(self, variables=None):
        total_supprimees = 0
        erreurs = []

        pieces_a_supprimer = Piece.objects.filter(document__isnull=True) | Piece.objects.filter(document="")

        for piece in pieces_a_supprimer.distinct():
            try:
                piece.delete()
                total_supprimees += 1
            except Exception as e:
                erreurs.append(f"Erreur pour la pièce {piece.idpiece} : {e}")
                logger.exception(f"Erreur lors de la suppression de la pièce {piece.idpiece}")

        resultat = f"Nombre de pièces supprimées : {total_supprimees}"

        if erreurs:
            resultat += "\n\nErreurs rencontrées :\n" + "\n".join(erreurs)

        return resultat