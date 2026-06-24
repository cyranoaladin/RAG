# Fixtures garde-fou brouillon reel minimal

Ces fixtures sont uniquement synthetiques. Elles servent a tester le verrou
metadata-only du lot 15F avant tout brouillon reel.

Regles :

- aucun document source n'est present ;
- aucun PDF, DOCX, PPTX ou XLSX n'est present ;
- les `source_uri` valides utilisent `synthetic://` ;
- aucun fichier n'est lu via `source_uri` ;
- aucun hash n'est calcule par le pipeline ;
- aucun ledger n'est ecrit ;
- aucun dossier `data/staging` n'est cree.

