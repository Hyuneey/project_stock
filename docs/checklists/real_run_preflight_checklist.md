# Real-Run Preflight Checklist

Complete this checklist before running any real official-data smoke command.

## Environment

- [ ] Python environment installed with `python -m pip install -e ".[dev,dashboard]"`.
- [ ] Working tree is clean or intentional local changes are documented.
- [ ] `project-stock real-run-preflight` runs successfully in default safe mode.

## API Keys

- [ ] `FRED_API_KEY` is set when FRED real fetches are configured.
- [ ] `ECOS_API_KEY` is set when ECOS real fetches are configured.
- [ ] `DART_API_KEY` or `OPEN_DART_API_KEY` is set when OpenDART real fetches
      are configured.
- [ ] Optional KRX credentials, if required by the deployment, are set only via
      `KRX_AUTH_TOKEN` or `KRX_API_KEY`.
- [ ] No secrets are committed or copied into config files.

## Network Opt-In

- [ ] Default safe mode confirmed with `PROJECT_STOCK_ALLOW_NETWORK` unset or
      false.
- [ ] `PROJECT_STOCK_ALLOW_NETWORK=true` will be set only for the bounded real
      smoke command.
- [ ] `project-stock real-run-preflight --require-network-enabled` fails safely
      before network opt-in.

## DB Path

- [ ] Target DB URL is explicit and run-specific when needed.
- [ ] Existing SQLite DB is backed up before real ingestion.
- [ ] Operator knows whether the run should append to an existing DB or use a
      fresh DB.

## Raw Cache Path

- [ ] Raw cache directories under `data/raw/` are ignored by Git.
- [ ] Operator has enough disk space for the bounded run.
- [ ] Cache retention policy is understood before the run starts.

## Date Range Bounds

- [ ] Smoke config `start_date` and `end_date` are reviewed.
- [ ] `max_days` is small enough for a smoke run.
- [ ] `max_records` is small enough for a smoke run.
- [ ] No broad historical download is planned in this workflow.

## Source Configs

- [ ] `configs/real_data_smoke.kor_semi.example.yaml` exists or an approved
      run-specific copy is used.
- [ ] ECOS series config exists.
- [ ] OpenDART corp-code config exists.
- [ ] KRX symbol config exists.
- [ ] Portfolio fixture/config paths are intentional if portfolio review is
      enabled.

## Dry-Run Result

- [ ] `project-stock real-data-smoke-doctor --config ...` succeeds.
- [ ] `project-stock run-real-data-smoke --config ... --dry-run` succeeds
      before any real run.
- [ ] Dry-run output shows `no_auto_trade=true`.

## Fixture Smoke Result

- [ ] `project-stock run-real-data-smoke-fixture --config ... --db-url ...`
      succeeds before any real run.
- [ ] Inserted and skipped duplicate counts are reviewed.
- [ ] Fixture smoke memo path is recorded.

## Expected Output Paths

- [ ] DB URL is recorded.
- [ ] Memo directory is recorded.
- [ ] Raw cache directories are recorded.
- [ ] Expected smoke report path is recorded.

## Dashboard Launch Command

- [ ] `project-stock run-dashboard --db-url ... --memo-dir ...` prints the
      expected local Streamlit command.
- [ ] Dashboard will point at the same DB and memo directory as the run.

## Manual Review Required

- [ ] Operator is assigned to review events, evidence, scenario triggers,
      thesis snapshots, and memos.
- [ ] KOR_SEMI drilldown review is planned when using the KOR_SEMI smoke config.
- [ ] Any investment conclusion remains a manual human review conclusion.

## No-Auto-Trade Confirmation

- [ ] Confirm no broker execution.
- [ ] Confirm no auto-trading.
- [ ] Confirm no live buy/sell orders.
- [ ] Confirm no LLM investment decision.
- [ ] Confirm every output is decision support only.
