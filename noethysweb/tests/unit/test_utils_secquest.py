import datetime
from types import SimpleNamespace
from unittest import mock

from portail.utils import utils_secquest


def _check(date_naiss, reponse):
    famille = SimpleNamespace(internet_secquest="datenaiss_1")
    rattachement = SimpleNamespace(individu=SimpleNamespace(date_naiss=date_naiss))
    with mock.patch.object(utils_secquest.Rattachement, "objects") as objects:
        objects.select_related.return_value.get.return_value = rattachement
        return utils_secquest.Check_secquest(famille=famille, reponse=reponse)


class TestCheckSecquest:
    def test_sans_question(self):
        famille = SimpleNamespace(internet_secquest=None)
        assert utils_secquest.Check_secquest(famille=famille, reponse="") is True

    def test_bonne_reponse(self):
        assert _check(datetime.date(2015, 3, 7), "07/03/2015") is True

    def test_mauvaise_reponse(self):
        assert _check(datetime.date(2015, 3, 7), "08/03/2015") is False

    def test_date_naiss_vide(self):
        assert _check(None, "07/03/2015") is False
