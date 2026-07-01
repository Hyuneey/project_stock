from __future__ import annotations

from typer.testing import CliRunner

from project_stock.cli import app


runner = CliRunner()


def _clear_real_run_env(monkeypatch) -> None:
    for name in [
        "PROJECT_STOCK_ALLOW_NETWORK",
        "FRED_API_KEY",
        "ECOS_API_KEY",
        "DART_API_KEY",
        "OPEN_DART_API_KEY",
        "KRX_AUTH_TOKEN",
        "KRX_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_real_run_preflight_works_without_network_or_api_keys(repo_root, monkeypatch):
    _clear_real_run_env(monkeypatch)

    result = runner.invoke(
        app,
        [
            "real-run-preflight",
            "--config",
            str(repo_root / "configs/real_data_smoke.kor_semi.example.yaml"),
            "--db-url",
            "sqlite:///./data/warehouse/preflight.sqlite",
            "--memo-dir",
            "data/processed/preflight",
        ],
    )

    assert result.exit_code == 0
    assert '"network_enabled": false' in result.output
    assert '"FRED_API_KEY": false' in result.output
    assert '"no_auto_trade": true' in result.output
    assert "real-data-smoke-doctor" in result.output


def test_real_run_preflight_requires_network_when_requested(repo_root, monkeypatch):
    _clear_real_run_env(monkeypatch)

    result = runner.invoke(
        app,
        [
            "real-run-preflight",
            "--config",
            str(repo_root / "configs/real_data_smoke.kor_semi.example.yaml"),
            "--require-network-enabled",
        ],
    )

    assert result.exit_code == 1
    assert "Network disabled" in result.output
    assert "PROJECT_STOCK_ALLOW_NETWORK=true" in result.output


def test_real_run_preflight_requires_keys_when_requested(repo_root, monkeypatch):
    _clear_real_run_env(monkeypatch)

    result = runner.invoke(
        app,
        [
            "real-run-preflight",
            "--config",
            str(repo_root / "configs/real_data_smoke.kor_semi.example.yaml"),
            "--require-keys",
        ],
    )

    assert result.exit_code == 1
    assert "Missing required API keys" in result.output
    assert "FRED_API_KEY" in result.output
    assert "ECOS_API_KEY" in result.output
    assert "DART_API_KEY or OPEN_DART_API_KEY" in result.output


def test_real_run_preflight_makes_no_network_calls(repo_root, monkeypatch):
    _clear_real_run_env(monkeypatch)

    def fail_network(*args, **kwargs):
        raise AssertionError("real-run-preflight must not call network functions")

    monkeypatch.setattr("project_stock.ingest.fred.urlopen", fail_network, raising=False)
    monkeypatch.setattr("project_stock.ingest.ecos.urlopen", fail_network, raising=False)
    monkeypatch.setattr("project_stock.ingest.dart.urlopen", fail_network, raising=False)
    monkeypatch.setattr(
        "project_stock.ingest.opendart_financials.urlopen",
        fail_network,
        raising=False,
    )
    monkeypatch.setattr("project_stock.ingest.krx.urlopen", fail_network, raising=False)

    result = runner.invoke(
        app,
        [
            "real-run-preflight",
            "--config",
            str(repo_root / "configs/real_data_smoke.kor_semi.example.yaml"),
        ],
    )

    assert result.exit_code == 0
    assert "safe_execution_sequence" in result.output


def test_real_run_checklists_exist_and_state_boundaries(repo_root):
    preflight = repo_root / "docs/checklists/real_run_preflight_checklist.md"
    postrun = repo_root / "docs/checklists/real_run_postrun_checklist.md"

    assert preflight.exists()
    assert postrun.exists()

    checklist_text = preflight.read_text(encoding="utf-8") + postrun.read_text(encoding="utf-8")
    assert "no broker execution" in checklist_text
    assert "no auto-trading" in checklist_text
    assert "no LLM investment decision" in checklist_text


def test_real_run_docs_put_dry_run_before_real_run(repo_root):
    docs = [
        repo_root / "README.md",
        repo_root / "docs/operations.md",
        repo_root / "docs/real_data_activation.md",
        repo_root / "docs/real_data_smoke_pipeline.md",
        repo_root / "docs/kor_semi_thesis_pack.md",
        repo_root / "docs/dashboard.md",
        repo_root / "docs/real_run_operator_runbook.md",
    ]

    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        dry_run_index = text.find(
            "project-stock run-real-data-smoke --config "
            "configs/real_data_smoke.kor_semi.example.yaml --dry-run"
        )
        real_run_index = text.find(
            "PROJECT_STOCK_ALLOW_NETWORK=true project-stock run-real-data-smoke "
            "--config configs/real_data_smoke.kor_semi.example.yaml"
        )
        assert dry_run_index != -1, f"{doc} should mention dry-run"
        assert real_run_index != -1, f"{doc} should mention real-run opt-in"
        assert dry_run_index < real_run_index, f"{doc} should document dry-run before real-run"


def test_no_broker_order_or_live_trading_logic_exists(repo_root):
    forbidden = {
        "place_order",
        "submit_order",
        "broker_execute",
        "live_buy",
        "live_sell",
        "auto_trade = True",
        "auto_trade=True",
    }
    python_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (repo_root / "src" / "project_stock").rglob("*.py")
    )

    assert [item for item in forbidden if item in python_text] == []
