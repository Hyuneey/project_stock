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


def test_real_run_acceptance_template_and_sanitized_example_exist(repo_root):
    template = repo_root / "docs/reports/real_run_acceptance_template.md"
    example = repo_root / "docs/reports/real_run_acceptance_example.sanitized.md"

    assert template.exists()
    assert example.exists()

    example_text = example.read_text(encoding="utf-8")
    assert "SANITIZED EXAMPLE" in example_text
    assert "secrets" in example_text
    assert "No real event rows" in example_text


def test_render_real_run_acceptance_template_works_without_network_or_keys(
    tmp_path,
    repo_root,
    monkeypatch,
):
    _clear_real_run_env(monkeypatch)
    output_path = tmp_path / "acceptance" / "report.md"

    result = runner.invoke(
        app,
        [
            "render-real-run-acceptance-template",
            "--run-id",
            "TEST_RUN_001",
            "--config",
            str(repo_root / "configs/real_data_smoke.kor_semi.example.yaml"),
            "--db-url",
            "sqlite:///./data/warehouse/test_real_run.sqlite",
            "--memo-dir",
            "data/processed/test_real_run",
            "--output-path",
            str(output_path),
            "--git-sha",
            "abc123",
            "--operator",
            "test_operator",
        ],
    )

    assert result.exit_code == 0
    assert '"output_path":' in result.output
    assert '"no_auto_trade": true' in result.output
    assert output_path.exists()

    report = output_path.read_text(encoding="utf-8")
    assert "TEST_RUN_001" in report
    assert "test_operator" in report
    assert "abc123" in report
    assert "real_data_smoke.kor_semi.example.yaml" in report
    assert "sqlite:///./data/warehouse/test_real_run.sqlite" in report
    assert "test_real_run" in report
    assert "no_auto_trade: `true`" in report
    assert "no broker execution" in report
    assert "no auto-trading" in report
    assert "no live order" in report
    assert "no LLM investment decision" in report


def test_render_real_run_acceptance_template_makes_no_network_calls(
    tmp_path,
    repo_root,
    monkeypatch,
):
    _clear_real_run_env(monkeypatch)

    def fail_network(*args, **kwargs):
        raise AssertionError("render-real-run-acceptance-template must not call network functions")

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
            "render-real-run-acceptance-template",
            "--run-id",
            "NO_NETWORK_RUN",
            "--config",
            str(repo_root / "configs/real_data_smoke.kor_semi.example.yaml"),
            "--db-url",
            "sqlite:///./data/warehouse/no_network.sqlite",
            "--memo-dir",
            "data/processed/no_network",
            "--output-path",
            str(tmp_path / "no_network_report.md"),
        ],
    )

    assert result.exit_code == 0


def test_real_run_acceptance_docs_warn_against_committing_raw_data_or_db_files(repo_root):
    docs = [
        repo_root / "README.md",
        repo_root / "docs/real_run_operator_runbook.md",
        repo_root / "docs/real_data_smoke_pipeline.md",
        repo_root / "docs/operations.md",
        repo_root / "docs/reports/real_run_acceptance_template.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in docs)

    assert "Do not commit" in combined
    assert "raw data" in combined
    assert "database files" in combined or "DB files" in combined
    assert "data/processed/real_run_acceptance/" in combined


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
