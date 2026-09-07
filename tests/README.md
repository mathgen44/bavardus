# Tests

Emplacement réservé aux tests unitaires du moteur, à écrire avec le code de production.

Les scripts de `outils/` ne sont **pas** des tests : ils exigent de vrais identifiants et
une interaction humaine. Ils portent délibérément le préfixe `diag_` et non `test_`, pour
que `pytest` ne tente jamais de les collecter.
