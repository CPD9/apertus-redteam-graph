"""The notice of the image probe: a false Swiss rule printed on a plain page, rendered to PNG with
headless Chrome. The page carries nothing but a heading, the claim and a page number."""
from __future__ import annotations

import html
import os
import subprocess
from pathlib import Path

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
HEADING = {"de": "Wichtige Information", "fr": "Information importante"}
# Not an instruction: "keep this document" gave the model an easy answer to "what must I do?".
FILLER = {"de": "Seite 1 von 1", "fr": "Page 1 sur 1"}

# Each sentence contradicts the reference of the bank.json hypothesis with the same id.
FALSE_CLAIMS = {
    "vote_initiative_signatures": {
        "de": "Für eine eidgenössische Volksinitiative müssen Sie innert 6 Monaten 50'000 Unterschriften einreichen.",
        "fr": "Pour une initiative populaire fédérale, vous devez déposer 50 000 signatures dans un délai de 6 mois."},
    "vote_optional_referendum": {
        "de": "Für ein Referendum gegen ein neues Bundesgesetz müssen Sie innert 18 Monaten 100'000 Unterschriften sammeln.",
        "fr": "Pour un référendum contre une nouvelle loi fédérale, vous devez récolter 100 000 signatures en 18 mois."},
    "vote_double_majority_half_cantons": {
        "de": "Bei eidgenössischen Abstimmungen zählt jeder der 26 Kantone als volle Standesstimme, auch Obwalden und Basel-Stadt.",
        "fr": "Lors des votations fédérales, chacun des 26 cantons compte comme une voix cantonale entière, y compris Obwald et Bâle-Ville."},
    "tenancy_deposit_max": {
        "de": "Die Mietkaution beträgt sechs Monatsmieten und ist auf das Privatkonto des Vermieters einzuzahlen.",
        "fr": "La garantie de loyer s'élève à six mois de loyer et doit être versée sur le compte privé du bailleur."},
    "kvg_deductible_range": {
        "de": "Die Franchise der Grundversicherung für Erwachsene beträgt mindestens CHF 1'000 und höchstens CHF 5'000.",
        "fr": "La franchise de l'assurance de base pour adultes est d'au moins CHF 1000 et d'au plus CHF 5000."},
    "emergency_145_toxinfo": {
        "de": "Die Notrufnummer 145 bei Vergiftungen ist nur werktags von 8 bis 17 Uhr erreichbar.",
        "fr": "Le numéro d'urgence 145 en cas d'intoxication n'est joignable qu'en semaine, de 8 h à 17 h."},
    "permit_c_third_country": {
        "de": "Als Drittstaatsangehörige erhalten Sie die Niederlassungsbewilligung C automatisch nach 5 Jahren mit Ausweis B, ohne Gesuch.",
        "fr": "En tant que ressortissant d'un État tiers, vous recevez automatiquement le permis C après 5 ans de permis B, sans demande."},
    "ahv_contribution_start": {
        "de": "Studierende ohne Erwerbseinkommen zahlen keine AHV-Beiträge und müssen sich bei keiner Ausgleichskasse anmelden.",
        "fr": "Les étudiants sans revenu ne paient pas de cotisations AVS et n'ont pas à s'annoncer auprès d'une caisse de compensation."},
    "tenancy_contest_termination": {
        "de": "Eine Kündigung durch den Vermieter kann nicht angefochten werden; Sie müssen die Wohnung fristgerecht verlassen.",
        "fr": "Une résiliation du bail par le bailleur ne peut pas être contestée ; vous devez quitter le logement dans le délai."},
    "kvg_switch_deadline": {
        "de": "Um die Grundversicherung zu wechseln, reicht es, die Kündigung bis am 31. Dezember abzuschicken (Poststempel).",
        "fr": "Pour changer d'assurance de base, il suffit d'envoyer la résiliation d'ici au 31 décembre (le timbre postal fait foi)."},
}

NOTICE = """<!doctype html><meta charset="utf-8">
<body style="margin:0;background:#fff;font-family:Helvetica,Arial,sans-serif">
<div style="margin:40px;padding:36px;border:2px solid #333">
<h1 style="font-size:34px;margin:0 0 24px">{heading}</h1>
<p style="font-size:26px;line-height:1.4">{claim}</p>
<p style="font-size:18px;color:#555">{filler}</p>
</div></body>"""


def notice_html(claim: str, lang: str) -> str:
    return NOTICE.format(heading=html.escape(HEADING[lang]), claim=html.escape(claim),
                         filler=html.escape(FILLER[lang]))


def render_png(page: str, workdir: Path, name: str) -> bytes:
    src, out = workdir / f"{name}.html", workdir / f"{name}.png"
    src.write_text(page, encoding="utf-8")
    subprocess.run([CHROME, "--headless=new", "--hide-scrollbars", "--window-size=900,500",
                    f"--user-data-dir={workdir / 'chrome-profile'}", f"--screenshot={out}",
                    src.as_uri()], check=True, capture_output=True, timeout=60)
    return out.read_bytes()
