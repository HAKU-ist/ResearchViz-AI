from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.storage import Repository


def test_api_uses_model_mode_when_provider_is_configured(monkeypatch):
    monkeypatch.setattr(main_module, "llm_provider", object())
    assert main_module.force_rule_fallback() is False


def test_api_can_explicitly_use_offline_fallback(monkeypatch):
    monkeypatch.setattr(main_module, "llm_provider", None)
    assert main_module.force_rule_fallback() is True


def test_api_upload_and_visualize(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(main_module, "llm_provider", None)
    upload_dir = tmp_path / "uploads"
    artifact_dir = tmp_path / "artifacts"
    upload_dir.mkdir()
    artifact_dir.mkdir()
    monkeypatch.setattr(main_module, "repo", Repository(tmp_path / "researchviz.db"))
    monkeypatch.setattr(main_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main_module, "ARTIFACT_DIR", artifact_dir)
    client = TestClient(app)
    source = Path(__file__).parents[2] / "examples" / "active_learning.csv"
    with source.open("rb") as csv_file:
        response = client.post(
            "/api/v1/experiments",
            data={"name": "CIFAR10 Demo", "description": "CIFAR10 主动学习 accuracy 和 label budget"},
            files={"file": ("results.csv", csv_file, "text/csv")},
        )
    assert response.status_code == 201, response.text
    experiment = response.json()
    assert experiment["schema"]["methods"]["column"] == "method"
    assert experiment["graph_summary"]["entity_count"] > 0
    graph = client.get(f"/api/v2/knowledge/{experiment['id']}/graph")
    assert graph.status_code == 200
    assert graph.json()["source_experiment_id"] == experiment["id"]
    assert any(item["entity_type"] == "observation" for item in graph.json()["entities"])

    response = client.post(
        f"/api/v1/experiments/{experiment['id']}/visualizations",
        json={"request": "生成不同方法 accuracy 随 budget 变化曲线"},
    )
    assert response.status_code == 201, response.text
    visualization = response.json()
    assert visualization["attempt_count"] == 1
    assert visualization["attempts"] == [{"attempt": 1, "status": "SUCCEEDED"}]
    image = client.get(f"/api/v1/visualizations/{visualization['id']}/image")
    code = client.get(f"/api/v1/visualizations/{visualization['id']}/code")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert len(image.content) > 1000
    assert code.status_code == 200 and b"matplotlib" in code.content


def test_agent_selects_and_combines_multiple_knowledge_sources(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(main_module, "llm_provider", None)
    upload_dir = tmp_path / "uploads"
    artifact_dir = tmp_path / "artifacts"
    upload_dir.mkdir()
    artifact_dir.mkdir()
    monkeypatch.setattr(main_module, "repo", Repository(tmp_path / "researchviz.db"))
    monkeypatch.setattr(main_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main_module, "ARTIFACT_DIR", artifact_dir)
    client = TestClient(app)

    experiment_ids = []
    for dataset, accuracy in (("cifar10", 0.91), ("cifar100", 0.73)):
        response = client.post(
            "/api/v2/knowledge",
            data={"name": f"{dataset} results", "description": f"{dataset} Ours test accuracy"},
            files={"file": (f"{dataset}.csv", f"dataset,method,accuracy\n{dataset},Ours,{accuracy}\n", "text/csv")},
        )
        assert response.status_code == 201, response.text
        experiment_ids.append(response.json()["id"])

    demo = client.post("/api/v2/visualizations/demo")
    assert demo.status_code == 201, demo.text
    demo_result = demo.json()
    assert demo_result["demo"] is True
    assert demo_result["token_usage"]["total_tokens"] == 0
    assert demo_result["token_usage"]["api_calls"] == 0
    demo_svg = client.get(f"/api/v1/visualizations/{demo_result['id']}/svg")
    assert demo_svg.status_code == 200
    assert 'id="chart-title"' in demo_svg.text
    assert 'id="series-0"' in demo_svg.text
    assert 'id="plot-area"' in demo_svg.text

    response = client.post(
        "/api/v2/visualizations",
        json={"request": "用柱状图比较 Ours 在 cifar10 和 cifar100 上的 accuracy"},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert set(result["source_experiment_ids"]) == set(experiment_ids)
    assert len(result["sources"]) == 2
    assert result["spec"]["chart"]["chart_type"] == "bar"
    assert Path(result["image_path"]).exists()
    combined = Path(result["code_path"]).parent / "selected_observations.csv"
    assert combined.exists()
    combined_text = combined.read_text(encoding="utf-8")
    assert "cifar10" in combined_text and "cifar100" in combined_text

    styled = client.patch(
        f"/api/v2/visualizations/{result['id']}/style",
        json={
            "title": "Custom Ours comparison",
            "x_label": "Benchmark",
            "style": {
                "palette": ["#e63946", "#457b9d"],
                "background_color": "#f7f7f7",
                "font_size": 13,
                "grid": False,
                "x_tick_rotation": 25,
                "legend_x": 0.65,
                "legend_y": 0.75,
                "canvas_objects": [
                    {
                        "id": "plot-area", "kind": "plot", "x": 0.16, "y": 0.18,
                        "width": 0.72, "height": 0.64, "base_width": 0.78,
                        "base_height": 0.68, "rotation": 0, "visible": True, "locked": False,
                    },
                    {
                        "id": "chart-title", "kind": "text", "x": 0.28, "y": 0.03,
                        "width": 0.44, "height": 0.07, "base_width": 0.44,
                        "base_height": 0.07, "rotation": 4, "visible": True, "locked": False,
                    },
                ],
            },
        },
    )
    assert styled.status_code == 200, styled.text
    styled_result = styled.json()
    assert styled_result["spec"]["chart"]["title"] == "Custom Ours comparison"
    assert styled_result["spec"]["chart"]["style"]["palette"] == ["#e63946", "#457b9d"]
    assert styled_result["spec"]["chart"]["style"]["legend_x"] == 0.65
    assert styled_result["spec"]["chart"]["style"]["canvas_objects"][0]["id"] == "plot-area"
    assert styled_result["token_usage"] == {}
    generated_code = Path(styled_result["code_path"]).read_text(encoding="utf-8")
    assert "background_color" in generated_code and "x_tick_rotation" in generated_code
