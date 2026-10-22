import datetime
from types import SimpleNamespace

from individus.views.inscriptions_activite_liste import Liste


def _inscription(date_naiss):
    return SimpleNamespace(individu=SimpleNamespace(date_naiss=date_naiss))


class TestGetNaissance:
    def test_date_formatee(self):
        inscription = _inscription(datetime.date(2015, 3, 7))
        assert Liste.datatable_class.Get_naissance(None, inscription) == "07/03/2015"

    def test_date_naiss_vide(self):
        inscription = _inscription(None)
        assert Liste.datatable_class.Get_naissance(None, inscription) == ""
