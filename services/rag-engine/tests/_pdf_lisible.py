"""Construit un PDF minimal mais REELLEMENT lisible par pypdf.

Les octets commençant par ``%PDF-1.7 ...`` ne sont pas un PDF : ils en
portent seulement l'en-tête. Un banc qui les utilise ne démontre rien d'une
extraction, et un maillon qui lit vraiment le document échouerait plus loin,
pour une raison sans rapport avec ce qu'on voulait tester.

Ce constructeur produit un document que ``pypdf`` ouvre en mode strict, dont
il compte les pages et dont il extrait le texte — vérifié.
"""
from __future__ import annotations


def pdf_lisible(pages: list[str]) -> bytes:
    """Un PDF valide dont pypdf extrait le texte de chaque page."""
    objets: list[bytes] = []

    def ajouter(corps: bytes) -> int:
        objets.append(corps)
        return len(objets)

    ids_pages: list[int] = []
    contenus: list[int] = []
    for texte in pages:
        flux = (
            b"BT\n/F1 12 Tf\n72 720 Td\n("
            + texte.replace("(", r"\(").replace(")", r"\)").encode("latin-1")
            + b") Tj\nET\n"
        )
        contenus.append(ajouter(
            b"<< /Length " + str(len(flux)).encode() + b" >>\nstream\n"
            + flux + b"endstream"
        ))

    police = ajouter(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    racine_pages = len(objets) + len(pages) + 1
    for contenu in contenus:
        ids_pages.append(ajouter(
            b"<< /Type /Page /Parent " + str(racine_pages).encode()
            + b" 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 "
            + str(police).encode() + b" 0 R >> >> /Contents "
            + str(contenu).encode() + b" 0 R >>"
        ))
    kids = b" ".join(str(i).encode() + b" 0 R" for i in ids_pages)
    pages_obj = ajouter(
        b"<< /Type /Pages /Kids [" + kids + b"] /Count "
        + str(len(ids_pages)).encode() + b" >>"
    )
    catalogue = ajouter(
        b"<< /Type /Catalog /Pages " + str(pages_obj).encode() + b" 0 R >>"
    )

    sortie = bytearray(b"%PDF-1.7\n")
    offsets = [0]
    for index, corps in enumerate(objets, start=1):
        offsets.append(len(sortie))
        sortie += str(index).encode() + b" 0 obj\n" + corps + b"\nendobj\n"
    depart = len(sortie)
    sortie += b"xref\n0 " + str(len(objets) + 1).encode() + b"\n"
    sortie += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        sortie += f"{offset:010d} 00000 n \n".encode()
    sortie += (
        b"trailer\n<< /Size " + str(len(objets) + 1).encode()
        + b" /Root " + str(catalogue).encode() + b" 0 R >>\nstartxref\n"
        + str(depart).encode() + b"\n%%EOF\n"
    )
    return bytes(sortie)
