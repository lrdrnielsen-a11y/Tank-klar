# Tank klar – sådan sætter du den op (gratis)

Du skal bruge en gratis GitHub-konto. Det tager ca. 15 minutter første gang.

## 1. Opret konto og projekt
1. Gå til github.com og opret en gratis konto.
2. Tryk **+** øverst til højre → **New repository**.
3. Navn: `Tank-klar` (GitHub laver selv mellemrummet om til en bindestreg). Vælg **Public** (gratis hjemmesider kræver et offentligt projekt). Tryk **Create repository**.

## 2. Læg filerne op
1. Pak zip-filen ud på din computer.
2. I dit nye projekt: tryk **uploading an existing file** (eller **Add file → Upload files**).
3. Træk ALT indholdet fra mappen ind: alle filerne (`index.html`, `manifest.webmanifest`, `sw.js`, `sources.json`, `override.json` m.fl.) og mapperne `scripts`, `data` og `ikoner`. Tryk **Commit changes**.

## 3. Opret den automatiske opdatering
Mappen `.github` er skjult på de fleste computere, så den laver du i hånden:
1. Tryk **Add file → Create new file**.
2. Skriv præcis dette som filnavn: `.github/workflows/opdater.yml`
3. Åbn filen `workflow-opdater.yml` (fra zip-filen) i Notesblok/TextEdit, kopiér alt, og indsæt det.
4. Tryk **Commit changes**.

## 4. Slå hjemmesiden og skriveadgang til
1. **Settings → Pages**: under *Source* vælg **GitHub Actions**.
2. **Settings → Actions → General**: under *Workflow permissions* vælg **Read and write permissions** → **Save**.

## 5. Kør den første gang
1. Gå til fanen **Actions** → vælg **Opdater priser** → **Run workflow**.
2. Efter et minut eller to er den grøn. Din app ligger nu på
   `https://DIT-BRUGERNAVN.github.io/Tank-klar/`
3. Åbn adressen på mobilen og vælg **Føj til hjemmeskærm**, så ligner den en app.

Herefter opdaterer den sig selv hver aften.

## Hvis et selskab mangler
Klik på den seneste kørsel under **Actions** og åbn trinnet *Hent priser og beregn prognose*. Der står for hvert selskab, om priserne blev fundet.
Mangler et selskab, så find selskabets side med dagens priser i din browser, og ret adressen i `sources.json` (tryk på filen → blyanten). Nogle selskaber viser først priserne via JavaScript – dem kan scriptet ikke læse, og så kan du sætte `"aktiv": false`.

## Selv bestemme morgendagens pris
Ret `override.json`: skriv morgendagens dato (fx `2026-10-25`) og prisen, fx `"diesel": 12.39`. Når datoen er passeret, bruges den automatiske prognose igen.

## Sådan regnes prognosen
Hver aften ser scriptet på, hvor meget markedsprisen på benzin og diesel (futures i dollar pr. gallon) og dollarkursen har ændret sig siden dagen før. Ændringen omregnes til kr. pr. liter inkl. moms og lægges oven i dagens listepris. Har markedet holdt lukket (weekend), regnes prisen som uændret. Det er et skøn – selskaberne kan gøre andet.

Elpriserne er morgendagens spotpriser fra Energi Data Service (Energinet). De er uden nettarif, afgifter og moms.
