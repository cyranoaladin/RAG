# Politique de conservation des contenus non-PDF

Les valeurs font autorité dans `non_pdf_retention_policy.json`. Ce document dit
pourquoi la politique est écrite ainsi.

## Ce que le gate mesure, et ce qu'il ne mesure pas

Le compteur `non_pdf_servable_reacquired` porte sur les **ressources
interactives servables**, pas sur les demandes de réacquisition. Les deux
totaux coexistaient sans que leur rapport soit écrit, et un compteur qu'on
prend pour un autre est un compteur qu'on peut faire baisser sans rien avoir
fermé. La réconciliation ligne à ligne est portée par
`non_pdf_37_vs_57_reconciliation.json` ; elle établit qu'il n'y avait pas de
contradiction.

Les autres demandes non-PDF sont **non indexables par rôle**. Elles sont
conservées comme traces de provenance et ne comptent jamais au numérateur
servable. Les retenir ne dit rien de l'état des servables.

## Pourquoi la mesure a remplacé une valeur figée

Le gate lisait un compteur figé. Une valeur figée ne peut ni se fermer quand le
travail est fait, ni se rouvrir quand le magasin disparaît — elle décrit un
instant, pas un état. Le gate mesure désormais les octets présents au magasin
durable, et il délègue cette mesure au réconciliateur canonique plutôt que de
la refaire : deux implémentations de la rétention finiraient par ne pas compter
pareil.

Le compteur figé reste le **plancher**. La mesure peut le confirmer ou le
dépasser, jamais le faire baisser.

## Ce qui ferme le bloqueur, et ce qui ne le ferme pas

Un contenu n'est retenu que si ses **octets** sont présents, que leur empreinte
SHA-256 égale l'empreinte attendue, et que leur taille égale la taille
attendue. Trois choses ne ferment rien :

- **un identifiant Drive.** Un lien prouve qu'un fichier existe quelque part,
  pas qu'on en a gardé une copie ;
- **une copie non vérifiée.** Des octets qu'on n'a pas confrontés à leur
  empreinte peuvent être n'importe quoi ;
- **une préservation locale d'urgence.** Elle met à l'abri, elle ne gouverne
  pas. Tant que le magasin canonique du projet n'est pas établi, le bloqueur
  reste ouvert et le rapport dit pourquoi : `DURABLE_STORE_UNREADABLE`.

Un magasin absent ou illisible ne vaut jamais un zéro silencieux : la raison
est nommée dans l'état de readiness.

## Exploitation

Les ressources interactives sont conservées comme **binaires**. Les rendre
recherchables suppose une extraction gouvernée puis le gate PII — aucune
exécution de macro, et les protections d'archive restent en place. Conserver un
fichier ne le rend ni servable, ni ingéré, ni exploitable par recherche.

Les traces non indexables ne sont jamais indexées ni servies.

## Ce que cette politique ne ferme pas

La revue PII, l'adoption de la politique d'actualité, les bloqueurs de
qualification et le go-live lui-même relèvent d'autres autorités. Fermer ce
bloqueur ne rapproche du go-live que d'un cran, et le gate continue de refuser.
