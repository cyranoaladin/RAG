# ADR-0073 — Continuité temporelle A2 du successeur public

Statut : proposée pour la PR #327, après la correction technique #332.

## Contexte

La préparation publique A1 `student-public-successor-20261010-40b956c6f5ec0c60` fige 11 collections, 253 dérivés textuels, 377 placements et 3 975 chunks. Son constat de source et de révocation a une durée de 24 heures, expirant le 12 octobre 2026 à 13:58:41 UTC. Ce délai ne suffit pas à la fenêtre de qualification de sept jours demandée. Changer l'horodatage ou les octets de A1 falsifierait la preuve et modifierait les empreintes des manifests, du registre de droits, du registre PII et du CAS privé.

## Décision

Créer une autorité temporelle **A2 distincte**, liée au SHA de l'ancre A1 et à chacun de ses digests de contenu, manifests, inventaire, registre de release, droits, PII, registre d'actualité et CAS. L'identité des 253 couples `content_sha256` dérivé / `source_pdf_sha256` et celle des 11 sujets et profils doivent rester exactement celles de A1. Le PDF CFTR `3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6` reste exclu. Ni la visibilité, ni les droits, ni les chunks, ni les scopes ne sont changés par A2.

À l'émission, rejouer le constat canonique sur de **nouvelles captures réelles** : 253/253 téléchargements PDF de SHA exact, pages Éduscol liant ces PDF, observation d'actualité et absence de révocation connue. Le récepteur recoupe les reçus privés, le rapport canonique, les 253 identités et les horloges. Une capture ou un constat manquant, ancien de plus d'une heure à l'émission, divergent, révoqué ou non vérifiable refuse A2. Une date simplement reportée ou réécrite ne vaut pas capture.

La nouvelle politique `PUBLIC_SUCCESSOR_A2_SEVEN_DAY_CURRENTNESS_V1` fixe la validité maximale de l'autorité A2 à sept jours après son émission. Elle **ne modifie pas** la politique A1 de 24 heures. À la qualification C et avant chaque activation, un **constat de source et de révocation C** indépendant doit être rejoué sur les 253 identités exactes ; sa capture ne peut dater de plus d'une heure. Ce constat peut être renouvelé sans changer le SHA A2, les 11 autorisations et le pin de contenu. C exige au moins 24 heures de validité A2 résiduelle. Une révocation ou une identité de source divergente au temps C bloque la publication, même si A2 reste dans sa fenêtre de sept jours.

A2 porte `activation_allowed=false` et n'autorise aucune mutation de staging, production ou base de données. Le transfert, les autorisations LOT41A, les scopes B, la review et C constituent des autorités distinctes. Les anciens reçus A1 et #330 ne sont pas réinterprétés silencieusement comme des reçus A2. La PR #327 doit consommer explicitement A2 et le constat C, émettre de nouveaux identifiants d'autorisation versionnés et refaire les bindings B/plan/pin que leur protocole impose.

## Contrat du vérificateur

`nexus_release_chain.public_successor_temporal` construit l'autorité déterministe A2 et la reconstruit lors de la vérification. Il refuse une différence de SHA, d'inventaire, de population, de statut, de date, de CFTR, de droits/PII/CAS ou de preuve individuelle. Le producteur `scripts/go_live/build_public_successor_a2_continuity.py` rejoue en plus le CAS privé et le rapport `attest_student_derivative_source_currentness.py` depuis les captures privées. Un simple JSON rédigé à la main ne suffit donc pas à l'émission. Le consommateur C doit, de la même façon, rejouer son constat privé **avant** l'appel au vérificateur partagé.

La période de sept jours est une borne de l'autorité, pas une promesse qu'une source restera publiée ou non révoquée pendant sept jours. Chaque décision C exige un nouveau constat positif. Après activation, la surveillance de révocation du runtime et son comportement de retrait restent requis par le protocole de publication ; A2 seul n'est jamais une preuve de disponibilité continue.
