# RADAR B2B — PRODOTTO PULITO (nessuna azienda precaricata)

Sito vuoto come un nuovo iscritto. Aggiungi un'azienda (nome + sito) -> ogni notte il
motore la profila con K3 e genera: tipo T1/T2/T3, mercati, segmenti, clienti potenziali,
competitor, strategia. Tutto etichettato "generato dal motore · da verificare" finche' le
fonti non sono controllate. Se T1 con codici HS: anche dati di scambio REALI da Comtrade.

## Setup (una tantum, ~20 min)
1. Repo PUBLIC "radar" -> carica TUTTO: index.html, dashboard.html, engine.py,
   config.json, companies.json, data/.gitkeep, .github/workflows/engine.yml
2. Settings -> Secrets -> Actions -> New secret: KIMI_API_KEY (platform.moonshot.ai,
   ricarica minima = tetto assoluto di spesa)
3. Settings -> Pages -> main -> Save
4. Actions -> engine -> Run workflow -> spunta verde -> apri https://TUONOME.github.io/radar/ -> Ctrl+F5

## Uso
- "+ Aggiungi azienda" nel menù -> genera la riga -> incolla in companies.json (matita) ->
  Run workflow -> dopo 1-2 min la scheda azienda e' piena.
- companies.json e' la lista delle aziende: togli una riga = l'azienda sparisce.
- Tetto spesa: config.json budget_monthly_usd (default 5). Oltre il tetto i passi a
  pagamento si sospendono, i dati gratuiti continuano.

## Costi
Profilazione + pacchetto completo: ~0,3-0,8 USD per azienda (una tantum, poi in cache).
Refresh notturno: ~0 (cache). Dati Comtrade: 0. Infrastruttura: 0.
