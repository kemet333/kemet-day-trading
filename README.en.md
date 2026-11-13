# Kemet Day Trading

*Versión en español: [README.md](README.md).*

Sixteen Claude skills that turn Claude into your trading team: scan thousands of charts, watch news and
filings, read earnings, follow Congress trades, mark the session levels, write the plan, watch the range
break bar by bar, set the stop and the target before you enter, replay the rest of the day 10,000 times before
you risk anything, size and risk-check against your rules, send the order to a paper broker only with your
yes, ring alerts, review the journal, and decide which funded account to buy.

US stocks and futures (ES, NQ, YM, RTY, CL, GC, SI, HG, NG, 6E, ZN, ZB). Free, MIT, no signup, no API key. The
tools are plain Python that reads free public data (Yahoo Finance bars, Nasdaq Trader symbol lists, SEC EDGAR,
the House Clerk) and the published rules of Topstep, Apex, Tradeify, Alpha Futures and Lucid, with the date they
were checked.

Nothing in this pack places an order except kemet-broker, and only on a paper account by default, after
kemet-riesgo passes that exact order and you type yes for that ticket. The entry rule it ships is the textbook
one, with no filter: the time machine shows what it would have done before, and often that is a coin flip. Most
people who day trade lose money, and a tool does not change that.

Made by [Kemet Capital](https://kemet-capital.com). The systems Kemet runs with agents on funded accounts carry
filters and parameters validated on its own bench; they are not in this pack: this is the desk, open. The
architecture follows [The Day Trader skill](https://github.com/Jakeschincariol/day-trader-skill) by Jake
Schincariol (MIT): everything that one does is here, in Spanish, plus futures, prop firms, session plan,
journal and risk geometry. The skills speak Spanish; the tools' flags are Spanish words too (`--ahora` is
"now", `--escribir` is "write", `--offline` is offline). Claude reads both languages without trouble.

## Install

Paste this into Claude:

```
https://github.com/kemet333/kemet-day-trading

install the skill
```

As a plugin, in Claude Code:

```
/plugin marketplace add kemet333/kemet-day-trading
/plugin install kemet-day-trading@kemet-day-trading
```

Claude Code namespaces plugin skills (`/kemet-day-trading:kemet-entrada`). Copy the folders instead if you want
plain `/kemet-entrada`:

```bash
git clone https://github.com/kemet333/kemet-day-trading.git
cp -r kemet-day-trading/kemet-* ~/.claude/skills/
```

For one project, the same folders in your repo's `.claude/skills/`. On Claude.ai or the Claude app: download the
zip from [kemet-capital.com/skill](https://www.kemet-capital.com/skill/) and upload it under Settings, Capabilities,
Skills: it is the whole pack as one skill. No Claude Code and no skills? Paste any `SKILL.md` at the top of a chat
and it runs as a method; you lose the Python tools, not the rules.

Python 3.8 or newer. Nothing to pip install. Mac, Linux and Windows.

## The sixteen

| command | what it is | what it does |
| --- | --- | --- |
| `/kemet-desk` | The desk | Places you (market, account, stop, hours), picks the piece and chains the rest in order. |
| `/kemet-scanner` | Scanner | Sweeps thousands of US stocks (Nasdaq Trader universe) before the open and at 10:15, and the twelve futures: what broke, what sits above yesterday's high. |
| `/kemet-noticias` | News | Headlines and 8-K filings per ticker with time and tag, plus the day's macro calendar, in one place. |
| `/kemet-niveles` | Levels | Yesterday's high, low and close, the overnight range, the opening range and the initial balance, and where price sits. |
| `/kemet-plan` | Session plan | The written plan: time slots, no-trade windows around data (automatic calendar), traffic light, size, your firm's cutoff. |
| `/kemet-entrada` | Entry | The range break bar by bar (60 minutes on futures, 15 on stocks): forming, waiting, triggered, expired. |
| `/kemet-salida` | Exit | Stop and target before you enter, to the tick, in points and dollars per micro or per share. |
| `/kemet-maquina` | Time machine | Replays the rest of the day 10,000 times from the instrument's own bars and reruns the rule on the real past sessions. An honest verdict. |
| `/kemet-tamano` | Size | Your account (a prop firm's rules or your own budget) and how many micros or shares fit your stop inside your daily limit. The bracket order. |
| `/kemet-riesgo` | Risk | PASS or BLOCK per order: stop, loss, daily limit, three losses and you stop, data windows, cutoff, market open. |
| `/kemet-broker` | Broker | Turns the passed order into a plain-words ticket; with your yes, Claude sends it to Alpaca on paper. Futures: by hand on your platform. |
| `/kemet-alertas` | Alerts | Stop, target, flat-by, your firm's cutoff, opening bell, Globex and NYSE clocks. Each rings once. |
| `/kemet-diario` | Journal | Reviews your trades CSV: plan compliance before P&L. Three things done right, two that broke the plan, one fix. |
| `/kemet-resultados` | Earnings | Reads SEC XBRL: quarters, revenue, net income, EPS, margins, when the next report is due. |
| `/kemet-congreso` | Congress | Congress members' trade disclosures (STOCK Act), the day they post. A hook, not a strategy. |
| `/kemet-geometria` | Geometry | Which funded account to buy, how much to risk and when to withdraw, from a study of 76 accounts. |

## How to use it

Everything lands in a `kemet/` folder in your project, and each skill reads what the last one wrote:

```
scanner -> noticias -> niveles -> plan                          (before the open)
entrada -> salida -> maquina -> tamano -> riesgo -> broker      (one trade)
alertas                                                         (while it is open)
riesgo registrar -> diario                                      (afterwards)
noticias / resultados / congreso                                (when it applies)
```

A real example: NQ, Wednesday November 11 2026 (the Spanish README walks it step by step; every number is
reproduced by the tests). The initial balance was 28,199 to 28,426; the 10:40 bar closed at 28,429.75, above the
high: triggered long at 10:45. Stop at the midpoint, 28,312.50; target 1R, 28,547; risk 117.25 points, 234.50 $
per MNQ. The time machine, over the previous 46 sessions with seed 19: target first 45.5 %, stop first 46.3 %,
still open at 15:55 8.2 %. Verdict: close to a coin flip, and it says so before anything is placed. On an Apex
150K, one MNQ fits and passes risk; on a 50K, none fits, and the tool says so instead of writing a smaller order.
The same path with a stock (TSLA, that same day) is documented in each skill.

## The tools

All standard-library Python, polite with the free endpoints (one request every half second, one retry on a 429).
`--ahora "2026-11-11 10:35"` pins the clock in New York time and replays a day; `--offline FILE` reads saved bars;
`--json` prints the whole document; `--escribir` saves into `kemet/`.

```bash
python3 kemet-scanner/scanner.py universo                              # -> kemet/universo.txt (~5,900 US stocks)
python3 kemet-scanner/scanner.py diario                                # pre-market setups -> kemet/watchlist.json
python3 kemet-scanner/scanner.py orb --a 10:15                         # opening-range breakouts so far
python3 kemet-scanner/scanner.py futuros                               # the twelve contracts
python3 kemet-noticias/noticias.py --tickers TSLA --horas 12           # headlines, 8-Ks, today's move, macro calendar
python3 kemet-niveles/niveles.py --mercado NQ --escribir             # -> kemet/niveles.json
python3 kemet-plan/plan.py agenda --auto                               # today's macro calendar -> kemet/agenda.json
python3 kemet-plan/plan.py plan --stop 18 --escribir                   # -> kemet/plan-sesion.json
python3 kemet-entrada/entrada.py check --escribir                      # -> kemet/entrada.json
python3 kemet-entrada/entrada.py watch --hasta 15:00                   # bar by bar until it triggers
python3 kemet-salida/salida.py plan --escribir                         # -> kemet/plan.json
python3 kemet-maquina/maquina.py run --escribir                        # 10,000 replays + the history
python3 kemet-tamano/tamano.py config --firma apex --cuenta eod-pa-150 # -> kemet/config.json (prop-firm account)
python3 kemet-tamano/tamano.py config --propia --presupuesto 5000 --max-perdida-operacion 50 --max-perdida-dia 150
python3 kemet-tamano/tamano.py orden --escribir                        # -> kemet/orden.json (bracket)
python3 kemet-riesgo/riesgo.py check                                   # PASS / BLOCK per order
python3 kemet-broker/broker.py mostrar                                 # the ticket, READY only with today's PASS
python3 kemet-broker/broker.py registrar --huella H --id-broker ID --precio P
python3 kemet-alertas/alertas.py add --desde-plan                      # stop, target, flat-by
python3 kemet-alertas/alertas.py check                                 # rings what hit, once
python3 kemet-diario/diario.py revisar operaciones.csv                 # the review
python3 kemet-resultados/resultados.py AAPL --trimestres 8             # quarters, margins, EPS
python3 kemet-congreso/congreso.py recientes --dias 45 --miembro pelosi
```

```bash
python3 -m unittest discover -s tests -v
```

The tests run offline on real saved data (Yahoo 5-minute bars for NQ, ES and TSLA, 60 days to November 12 2026;
CL, GC and AAPL, 5 days; the 234-chart wall of October 19 2026 and the Nasdaq Trader symbol lists; Apple's and
Coca-Cola's XBRL; real House Clerk PTRs) and reproduce every number in the examples.

## Fine print

**Not financial advice.** This is software that reads public data and does arithmetic. It does not know your
situation and it cannot see the future. Most people who day trade lose money. You can lose money, and pay for
evaluations you do not pass. Decide for yourself, and talk to a licensed professional if you need advice.

**No order without your yes.** Only `/kemet-broker` can lead to an order, and only after `/kemet-riesgo` passes
that exact order and you type yes for that ticket in the chat. Set the broker tool to "Needs approval" in Claude,
never "Always allow", so Claude's own card is a second check. Paper account by default (`"papel": true`); keys
live in environment variables, never in the chat. There is no free futures connector: futures orders you place
yourself on your platform. Kemet Capital runs, with agents on its own platform, systems whose filters and
parameters were validated on its own bench; that is a different product and it is not here.

**The time machine is a simulation, not a prediction.** It is built from the instrument's own 5-minute bars over
the previous sessions (Yahoo keeps about 48). The future can do things those sessions never did: a data release,
a gap, a headline. Treat its odds as a reality check, never as a promise.

**A stop is a plan, not a guarantee.** In a fast market or across a gap a stop order fills far from its price. The
max loss shown is the loss at the stop price.

**The data is free and unofficial.** Yahoo's chart endpoint is not an official API: futures arrive about 10 minutes
late, it can fail or rate-limit you. Bars are 5-minute bars, never ticks. EDGAR and the House Clerk ask you to
identify yourself (`sec_user_agent` in `kemet/config.json`). Check anything that matters on your platform before
you act on it.

**Prop-firm rules change.** They come from the firms' sites with the date they were checked; your dashboard wins.
Confirm them before paying and before every payout.

**Congress trades are public, not inside information.** Members must disclose trades over $1,000 within 45 days
(the STOCK Act). `/kemet-congreso` reads those public filings.

**The opening-range break is not a system with an edge.** It is the best-known textbook day-trading rule, with
no filter: it is there to learn to execute with a stop, a size and an exit time written down beforehand, and to see
in the time machine what it would have done. Nobody promises it wins; often it does not.

## Files

```
kemet-desk/        SKILL.md, references/ (session plan, review)
kemet-scanner/     SKILL.md, scanner.py
kemet-noticias/    SKILL.md, noticias.py
kemet-niveles/     SKILL.md, niveles.py
kemet-plan/        SKILL.md, plan.py, agenda.example.json
kemet-entrada/     SKILL.md, entrada.py
kemet-salida/      SKILL.md, salida.py
kemet-maquina/     SKILL.md, maquina.py
kemet-tamano/      SKILL.md, tamano.py, reglas-de-firmas.json, reglas-de-firmas.md, config.example.json, config.propia.example.json
kemet-riesgo/      SKILL.md, riesgo.py
kemet-broker/      SKILL.md, broker.py, claude_desktop_config.example.json
kemet-alertas/     SKILL.md, alertas.py, alertas.example.json
kemet-diario/      SKILL.md, diario.py, diario.example.csv
kemet-resultados/  SKILL.md, resultados.py, metricas.example.json
kemet-congreso/    SKILL.md, congreso.py
kemet-geometria/   SKILL.md, geometria-de-riesgo.md
tests/             unittest + real fixtures
```

Every tool folder carries its own copy of `comun.py` (New York and Madrid time without zoneinfo, Yahoo bars, the
CME trading day, contracts and micros, stocks by ticker, the Globex and NYSE clocks, the `kemet/` files), so each
skill installs on its own.

MIT. Made by [Kemet Capital](https://kemet-capital.com).
