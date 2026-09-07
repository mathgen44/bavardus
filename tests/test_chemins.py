"""Séparation du code et de l'état — ce qui rend le conteneur possible."""

import pytest

from bavardus import chemins


def test_par_defaut_letat_vit_avec_le_code(monkeypatch):
    monkeypatch.delenv("BAVARDUS_DONNEES", raising=False)
    assert chemins.dossier_etat() == chemins.racine_code()


def test_la_variable_deplace_tout_letat(monkeypatch, tmp_path):
    """Cinq fichiers en dépendent, et aucun autre : sauvegarder ce dossier,
    c'est sauvegarder l'installation entière."""
    monkeypatch.setenv("BAVARDUS_DONNEES", str(tmp_path))
    for chemin in (chemins.config_yaml(), chemins.fichier_env(),
                   chemins.fichier_jetons(), chemins.base_donnees(),
                   chemins.cle_session()):
        assert chemin.parent == tmp_path


def test_le_dossier_est_cree_sil_manque(monkeypatch, tmp_path):
    cible = tmp_path / "absent" / "etat"
    monkeypatch.setenv("BAVARDUS_DONNEES", str(cible))
    assert chemins.dossier_etat().exists()


def test_config_creee_depuis_lexemple(monkeypatch, tmp_path):
    """Un premier `docker compose up` échouerait sinon sur un fichier absent
    que l'utilisateur n'a aucun moyen de deviner."""
    monkeypatch.setenv("BAVARDUS_DONNEES", str(tmp_path))
    chemin, cree = chemins.preparer_config()
    assert cree is True and chemin.exists()
    assert "base_url" in chemin.read_text(encoding="utf-8")


def test_config_existante_nest_pas_ecrasee(monkeypatch, tmp_path):
    monkeypatch.setenv("BAVARDUS_DONNEES", str(tmp_path))
    (tmp_path / "config.yaml").write_text("persona: le mien\n", encoding="utf-8")
    chemin, cree = chemins.preparer_config()
    assert cree is False
    assert chemin.read_text(encoding="utf-8") == "persona: le mien\n"
