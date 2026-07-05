# tasks/todo.md

## Setup (run in Claude Code CLI)
- [ ] `git init` + create GitHub repo via `gh repo create` (see note on public/private)
- [ ] commit all files, push to main
- [ ] verify `.github/workflows/scan.yml` present on GitHub

## Setup (manual — browser, YOU only)
- [ ] Repo → Settings → Pages → Source: `main` / root  (dashboard goes live)
- [ ] Repo → Actions → enable workflows → "Run workflow" once to test
- [ ] Repo → Settings → Secrets and variables → Actions → add Secrets:
      SMTP_HOST=smtp.gmail.com  SMTP_PORT=587  SMTP_USER=<gmail>
      SMTP_PASS=<gmail app password>  MAIL_TO=<inbox>
      (never paste these into a prompt or a file)

## Verify (done = proof)
- [ ] first Actions run is green
- [ ] dashboard loads at https://<you>.github.io/<repo>/
- [ ] test email received (trigger "Run workflow" with data change)

## Build — Phase 1 remainder
- [x] drop-tracker: link lots across rounds, flag floor cuts
- [ ] discount score: €/m² vs municipality comps + walk-away price per lot

## Decide (write the answer here, don't leave blank)
- [ ] greenlight target for commercialising: __________
- [ ] kill criterion + date: __________
