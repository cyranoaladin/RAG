#!/usr/bin/env bash
# Neutralisation, sans effet de bord, du contrôle de transaction qu'un
# fichier SQL porte lui-même.
#
# **Le problème.** `bootstrap_ingestion_control_schema.sh` et
# `rollback_ingestion_control_schema.sh` composent chacun plusieurs
# fragments — verrou, registre, migration, enregistrement — et les exécutent
# dans UNE transaction (`psql --single-transaction`) : tout committe
# ensemble, ou rien. PostgreSQL documente qu'un `BEGIN;` ou un `COMMIT;`
# présent dans le flux défait cet effet : le `BEGIN;` n'ouvre rien et
# avertit, et le `COMMIT;` valide la transaction EXTÉRIEURE. Ce qui suit
# s'exécute alors hors transaction.
#
# Mesuré sur ce dépôt : les migrations 016 et 017 portent chacune ce couple,
# les quinze précédentes non. Conséquences réelles, et non théoriques :
# l'enregistrement d'une migration pouvait committer séparément de son DDL,
# et un rollback composé validait à mi-parcours — une reprise interrompue
# laissait alors un schéma à moitié défait.
#
# **Ce qui n'est pas fait.** Les OCTETS des fichiers ne sont pas modifiés.
# L'empreinte d'une migration est celle de son fichier, elle reste vérifiée
# à l'identique, et une base qui a déjà appliqué 016 ou 017 ne voit aucune
# dérive. Seul le FLUX exécuté est débarrassé de ces deux instructions.
#
# **Ce qui est retiré, exactement.** Une ligne ne portant que `BEGIN;` ou
# `COMMIT;`, et seulement hors d'un corps délimité par `$$`. Le `BEGIN`
# d'un bloc PL/pgSQL n'est pas une commande de transaction, ne porte pas de
# point-virgule à cet endroit, et n'est jamais retiré. Aucune autre ligne
# n'est touchée.

strip_inner_transaction_control() {
    awk '
        {
            ligne = $0
            hors_corps = (guillemet == 0)
            n = gsub(/\$\$/, "&", ligne)
            if (hors_corps && n % 2 == 1) { guillemet = 1; print; next }
            if (!hors_corps) { if (n % 2 == 1) guillemet = 0; print; next }
            if (ligne ~ /^[[:space:]]*(BEGIN|COMMIT)[[:space:]]*;[[:space:]]*$/) next
            print
        }
    '
}
