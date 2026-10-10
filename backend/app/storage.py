import json
import sqlite3
from pathlib import Path
from typing import Any

from .graph_ontology import KnowledgeSubgraph


class Repository:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS experiments (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
              filename TEXT NOT NULL, file_path TEXT NOT NULL, file_hash TEXT, status TEXT NOT NULL,
              profile_json TEXT NOT NULL, sample_json TEXT NOT NULL, schema_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS visualizations (
              id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, request_text TEXT NOT NULL,
              status TEXT NOT NULL, spec_json TEXT NOT NULL, code_path TEXT,
              image_path TEXT, svg_path TEXT, error_message TEXT, created_at TEXT NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 0, model_name TEXT,
              token_usage_json TEXT NOT NULL DEFAULT '{}',
              FOREIGN KEY(experiment_id) REFERENCES experiments(id)
            );
            CREATE TABLE IF NOT EXISTS datasets (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dataset_variants (
              id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
              raw_name TEXT NOT NULL, display_name TEXT NOT NULL,
              parameters_json TEXT NOT NULL, confidence REAL NOT NULL,
              FOREIGN KEY(experiment_id) REFERENCES experiments(id),
              FOREIGN KEY(dataset_id) REFERENCES datasets(id)
            );
            CREATE TABLE IF NOT EXISTS methods (
              id TEXT PRIMARY KEY, name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS method_variants (
              id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, method_id TEXT NOT NULL,
              raw_name TEXT NOT NULL, display_name TEXT NOT NULL, source_column TEXT NOT NULL,
              parameters_json TEXT NOT NULL, confidence REAL NOT NULL,
              FOREIGN KEY(experiment_id) REFERENCES experiments(id),
              FOREIGN KEY(method_id) REFERENCES methods(id)
            );
            CREATE TABLE IF NOT EXISTS observations (
              id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
              dataset_variant_id TEXT NOT NULL, method_variant_id TEXT,
              metric_name TEXT NOT NULL, metric_value REAL NOT NULL,
              dimensions_json TEXT NOT NULL, source_row INTEGER NOT NULL,
              source_column TEXT NOT NULL,
              FOREIGN KEY(experiment_id) REFERENCES experiments(id),
              FOREIGN KEY(dataset_variant_id) REFERENCES dataset_variants(id),
              FOREIGN KEY(method_variant_id) REFERENCES method_variants(id)
            );
            CREATE TABLE IF NOT EXISTS knowledge_documents (
              experiment_id TEXT PRIMARY KEY, search_text TEXT NOT NULL,
              FOREIGN KEY(experiment_id) REFERENCES experiments(id)
            );
            CREATE TABLE IF NOT EXISTS visualization_sources (
              visualization_id TEXT NOT NULL, experiment_id TEXT NOT NULL,
              PRIMARY KEY(visualization_id, experiment_id),
              FOREIGN KEY(visualization_id) REFERENCES visualizations(id),
              FOREIGN KEY(experiment_id) REFERENCES experiments(id)
            );
            CREATE TABLE IF NOT EXISTS graph_entities (
              id TEXT NOT NULL, source_experiment_id TEXT NOT NULL,
              entity_type TEXT NOT NULL, properties_json TEXT NOT NULL,
              confidence REAL NOT NULL, assertion_method TEXT NOT NULL,
              status TEXT NOT NULL, evidence_json TEXT NOT NULL,
              ontology_version TEXT NOT NULL,
              PRIMARY KEY(id, source_experiment_id),
              FOREIGN KEY(source_experiment_id) REFERENCES experiments(id)
            );
            CREATE TABLE IF NOT EXISTS graph_relations (
              id TEXT NOT NULL, source_experiment_id TEXT NOT NULL,
              relation_type TEXT NOT NULL, source_id TEXT NOT NULL,
              source_type TEXT NOT NULL, target_id TEXT NOT NULL,
              target_type TEXT NOT NULL, properties_json TEXT NOT NULL,
              confidence REAL NOT NULL, assertion_method TEXT NOT NULL,
              status TEXT NOT NULL, evidence_json TEXT NOT NULL,
              ontology_version TEXT NOT NULL,
              PRIMARY KEY(id, source_experiment_id),
              FOREIGN KEY(source_experiment_id) REFERENCES experiments(id),
              FOREIGN KEY(source_id, source_experiment_id)
                REFERENCES graph_entities(id, source_experiment_id),
              FOREIGN KEY(target_id, source_experiment_id)
                REFERENCES graph_entities(id, source_experiment_id)
            );
            CREATE INDEX IF NOT EXISTS idx_dataset_variants_experiment ON dataset_variants(experiment_id);
            CREATE INDEX IF NOT EXISTS idx_method_variants_experiment ON method_variants(experiment_id);
            CREATE INDEX IF NOT EXISTS idx_observations_experiment ON observations(experiment_id);
            CREATE INDEX IF NOT EXISTS idx_observations_dimensions ON observations(dataset_variant_id, method_variant_id, metric_name);
            CREATE INDEX IF NOT EXISTS idx_visualization_sources_visualization ON visualization_sources(visualization_id);
            CREATE INDEX IF NOT EXISTS idx_graph_entities_experiment ON graph_entities(source_experiment_id);
            CREATE INDEX IF NOT EXISTS idx_graph_entities_type ON graph_entities(entity_type);
            CREATE INDEX IF NOT EXISTS idx_graph_relations_experiment ON graph_relations(source_experiment_id);
            CREATE INDEX IF NOT EXISTS idx_graph_relations_type ON graph_relations(relation_type);
            CREATE INDEX IF NOT EXISTS idx_graph_relations_source ON graph_relations(source_id,source_experiment_id);
            CREATE INDEX IF NOT EXISTS idx_graph_relations_target ON graph_relations(target_id,source_experiment_id);
            """)
            experiment_columns = {row[1] for row in conn.execute("PRAGMA table_info(experiments)")}
            if "sample_json" not in experiment_columns:
                conn.execute("ALTER TABLE experiments ADD COLUMN sample_json TEXT NOT NULL DEFAULT '{}'")
            if "file_hash" not in experiment_columns:
                conn.execute("ALTER TABLE experiments ADD COLUMN file_hash TEXT")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_experiments_file_hash ON experiments(file_hash)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(visualizations)")}
            if "attempt_count" not in columns:
                conn.execute("ALTER TABLE visualizations ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0")
            if "model_name" not in columns:
                conn.execute("ALTER TABLE visualizations ADD COLUMN model_name TEXT")
            if "token_usage_json" not in columns:
                conn.execute("ALTER TABLE visualizations ADD COLUMN token_usage_json TEXT NOT NULL DEFAULT '{}'")
            if "svg_path" not in columns:
                conn.execute("ALTER TABLE visualizations ADD COLUMN svg_path TEXT")

    @staticmethod
    def _decode(row: sqlite3.Row | None, fields: tuple[str, ...]) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        for field in fields:
            if value.get(field):
                target = "table_sample" if field == "sample_json" else field.removesuffix("_json")
                value[target] = json.loads(value.pop(field))
        return value

    def create_experiment(
        self,
        data: dict[str, Any],
        knowledge: dict[str, Any] | None = None,
        graph: KnowledgeSubgraph | dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO experiments
                   (id, name, description, filename, file_path, file_hash, status,
                    profile_json, sample_json, schema_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (data["id"], data["name"], data["description"], data["filename"],
                 data["file_path"], data.get("file_hash"), data["status"], json.dumps(data["profile"], ensure_ascii=False),
                json.dumps(data["table_sample"], ensure_ascii=False),
                json.dumps(data["schema"], ensure_ascii=False), data["created_at"]),
            )
            if knowledge:
                self._insert_knowledge(conn, data["id"], knowledge)
            if graph:
                self._insert_graph(conn, data["id"], graph)

    def get_experiment_by_file_hash(self, file_hash: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM experiments WHERE file_hash=?", (file_hash,)).fetchone()
        return self._decode(row, ("profile_json", "sample_json", "schema_json"))

    @staticmethod
    def _insert_knowledge(conn: sqlite3.Connection, experiment_id: str, knowledge: dict[str, Any]) -> None:
        for item in knowledge["datasets"]:
            conn.execute(
                "INSERT OR IGNORE INTO datasets (id,name,metadata_json) VALUES (?,?,?)",
                (item["id"], item["name"], json.dumps(item["metadata"], ensure_ascii=False)),
            )
        for item in knowledge["methods"]:
            conn.execute(
                "INSERT OR IGNORE INTO methods (id,name) VALUES (?,?)",
                (item["id"], item["name"]),
            )
        conn.executemany(
            """INSERT INTO dataset_variants
               (id,experiment_id,dataset_id,raw_name,display_name,parameters_json,confidence)
               VALUES (?,?,?,?,?,?,?)""",
            [
                (
                    item["id"], experiment_id, item["dataset_id"], item["raw_name"],
                    item["display_name"], json.dumps(item["parameters"], ensure_ascii=False), item["confidence"],
                )
                for item in knowledge["dataset_variants"]
            ],
        )
        conn.executemany(
            """INSERT INTO method_variants
               (id,experiment_id,method_id,raw_name,display_name,source_column,parameters_json,confidence)
               VALUES (?,?,?,?,?,?,?,?)""",
            [
                (
                    item["id"], experiment_id, item["method_id"], item["raw_name"],
                    item["display_name"], item["source_column"],
                    json.dumps(item["parameters"], ensure_ascii=False), item["confidence"],
                )
                for item in knowledge["method_variants"]
            ],
        )
        conn.executemany(
            """INSERT INTO observations
               (id,experiment_id,dataset_variant_id,method_variant_id,metric_name,metric_value,
                dimensions_json,source_row,source_column)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                (
                    item["id"], experiment_id, item["dataset_variant_id"], item["method_variant_id"],
                    item["metric_name"], item["metric_value"],
                    json.dumps(item["dimensions"], ensure_ascii=False), item["source_row"], item["source_column"],
                )
                for item in knowledge["observations"]
            ],
        )
        conn.execute(
            "INSERT INTO knowledge_documents (experiment_id,search_text) VALUES (?,?)",
            (experiment_id, knowledge["search_text"]),
        )

    @staticmethod
    def _insert_graph(
        conn: sqlite3.Connection,
        experiment_id: str,
        graph: KnowledgeSubgraph | dict[str, Any],
    ) -> None:
        subgraph = graph if isinstance(graph, KnowledgeSubgraph) else KnowledgeSubgraph.model_validate(graph)
        if subgraph.source_experiment_id and subgraph.source_experiment_id != experiment_id:
            raise ValueError("KnowledgeSubgraph 与目标 experiment_id 不一致")
        conn.executemany(
            """INSERT INTO graph_entities
               (id,source_experiment_id,entity_type,properties_json,confidence,
                assertion_method,status,evidence_json,ontology_version)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                (
                    item.id, experiment_id, item.entity_type.value,
                    json.dumps(item.properties, ensure_ascii=False), item.confidence,
                    item.assertion_method.value, item.status.value,
                    json.dumps([evidence.model_dump(mode="json") for evidence in item.evidence], ensure_ascii=False),
                    item.ontology_version,
                )
                for item in subgraph.entities
            ],
        )
        conn.executemany(
            """INSERT INTO graph_relations
               (id,source_experiment_id,relation_type,source_id,source_type,target_id,target_type,
                properties_json,confidence,assertion_method,status,evidence_json,ontology_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    item.id, experiment_id, item.relation_type.value,
                    item.source_id, item.source_type.value, item.target_id, item.target_type.value,
                    json.dumps(item.properties, ensure_ascii=False), item.confidence,
                    item.assertion_method.value, item.status.value,
                    json.dumps([evidence.model_dump(mode="json") for evidence in item.evidence], ensure_ascii=False),
                    item.ontology_version,
                )
                for item in subgraph.relations
            ],
        )

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        return self._decode(row, ("profile_json", "sample_json", "schema_json"))

    def list_experiments(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM experiments ORDER BY created_at DESC").fetchall()
        return [self._decode(row, ("profile_json", "sample_json", "schema_json")) for row in rows]  # type: ignore[misc]

    def list_knowledge(self, query: str = "") -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%"
        where = "WHERE e.name LIKE ? OR e.description LIKE ? OR e.schema_json LIKE ? OR k.search_text LIKE ?" if query.strip() else ""
        params: tuple[Any, ...] = (pattern, pattern, pattern, pattern) if query.strip() else ()
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT e.id,e.name,e.description,e.filename,e.status,e.created_at,
                    e.schema_json,
                    CASE WHEN k.experiment_id IS NULL THEN 0 ELSE 1 END AS indexed,
                    COUNT(DISTINCT dv.id) AS dataset_variant_count,
                    COUNT(DISTINCT mv.id) AS method_variant_count,
                    COUNT(DISTINCT o.id) AS observation_count
                    FROM experiments e
                    LEFT JOIN knowledge_documents k ON k.experiment_id=e.id
                    LEFT JOIN dataset_variants dv ON dv.experiment_id=e.id
                    LEFT JOIN method_variants mv ON mv.experiment_id=e.id
                    LEFT JOIN observations o ON o.experiment_id=e.id
                    {where}
                    GROUP BY e.id ORDER BY e.created_at DESC""",
                params,
            ).fetchall()
            items = [dict(row) for row in rows]
            if not items:
                return []
            placeholders = ",".join("?" for _ in items)
            experiment_ids = [item["id"] for item in items]
            dataset_rows = conn.execute(
                f"""SELECT DISTINCT dv.experiment_id,d.name
                    FROM dataset_variants dv JOIN datasets d ON d.id=dv.dataset_id
                    WHERE dv.experiment_id IN ({placeholders}) ORDER BY d.name""",
                experiment_ids,
            ).fetchall()
            method_rows = conn.execute(
                f"""SELECT DISTINCT experiment_id,display_name
                    FROM method_variants WHERE experiment_id IN ({placeholders})
                    ORDER BY display_name""",
                experiment_ids,
            ).fetchall()
            metric_rows = conn.execute(
                f"""SELECT DISTINCT experiment_id,metric_name
                    FROM observations WHERE experiment_id IN ({placeholders})
                    ORDER BY metric_name""",
                experiment_ids,
            ).fetchall()
        datasets_by_experiment: dict[str, list[str]] = {}
        methods_by_experiment: dict[str, list[str]] = {}
        metrics_by_experiment: dict[str, list[str]] = {}
        for row in dataset_rows:
            datasets_by_experiment.setdefault(row["experiment_id"], []).append(row["name"])
        for row in method_rows:
            methods_by_experiment.setdefault(row["experiment_id"], []).append(row["display_name"])
        for row in metric_rows:
            metrics_by_experiment.setdefault(row["experiment_id"], []).append(row["metric_name"])
        for item in items:
            schema = json.loads(item.pop("schema_json"))
            item["datasets"] = datasets_by_experiment.get(item["id"]) or schema.get("datasets", [])
            method_schema = schema.get("methods", {})
            item["methods"] = methods_by_experiment.get(item["id"]) or method_schema.get("values", [])
            item["metrics"] = metrics_by_experiment.get(item["id"]) or [
                metric.get("name") for metric in schema.get("metrics", []) if metric.get("name")
            ]
        return items

    def get_knowledge(self, experiment_id: str) -> dict[str, Any] | None:
        experiment = self.get_experiment(experiment_id)
        if not experiment:
            return None
        with self.connect() as conn:
            dataset_rows = conn.execute(
                """SELECT dv.*,d.name AS dataset_name FROM dataset_variants dv
                   JOIN datasets d ON d.id=dv.dataset_id WHERE dv.experiment_id=?
                   ORDER BY d.name,dv.display_name""",
                (experiment_id,),
            ).fetchall()
            method_rows = conn.execute(
                """SELECT mv.*,m.name AS method_name FROM method_variants mv
                   JOIN methods m ON m.id=mv.method_id WHERE mv.experiment_id=?
                   ORDER BY m.name,mv.display_name""",
                (experiment_id,),
            ).fetchall()
            observation_count = conn.execute(
                "SELECT COUNT(*) FROM observations WHERE experiment_id=?", (experiment_id,)
            ).fetchone()[0]
            metrics = [row[0] for row in conn.execute(
                "SELECT DISTINCT metric_name FROM observations WHERE experiment_id=? ORDER BY metric_name",
                (experiment_id,),
            ).fetchall()]
        datasets = [self._decode(row, ("parameters_json",)) for row in dataset_rows]
        methods = [self._decode(row, ("parameters_json",)) for row in method_rows]
        return {
            "experiment": experiment,
            "dataset_variants": datasets,
            "method_variants": methods,
            "metrics": metrics,
            "observation_count": observation_count,
        }

    def replace_knowledge(
        self,
        experiment_id: str,
        knowledge: dict[str, Any],
        graph: KnowledgeSubgraph | dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM graph_relations WHERE source_experiment_id=?", (experiment_id,))
            conn.execute("DELETE FROM graph_entities WHERE source_experiment_id=?", (experiment_id,))
            conn.execute("DELETE FROM observations WHERE experiment_id=?", (experiment_id,))
            conn.execute("DELETE FROM method_variants WHERE experiment_id=?", (experiment_id,))
            conn.execute("DELETE FROM dataset_variants WHERE experiment_id=?", (experiment_id,))
            conn.execute("DELETE FROM knowledge_documents WHERE experiment_id=?", (experiment_id,))
            self._insert_knowledge(conn, experiment_id, knowledge)
            if graph:
                self._insert_graph(conn, experiment_id, graph)

    def get_experiment_graph(self, experiment_id: str) -> KnowledgeSubgraph | None:
        if not self.get_experiment(experiment_id):
            return None
        with self.connect() as conn:
            entity_rows = conn.execute(
                "SELECT * FROM graph_entities WHERE source_experiment_id=? ORDER BY entity_type,id",
                (experiment_id,),
            ).fetchall()
            relation_rows = conn.execute(
                "SELECT * FROM graph_relations WHERE source_experiment_id=? ORDER BY relation_type,id",
                (experiment_id,),
            ).fetchall()
        entities = [
            {
                "id": row["id"], "entity_type": row["entity_type"],
                "properties": json.loads(row["properties_json"]), "confidence": row["confidence"],
                "assertion_method": row["assertion_method"], "status": row["status"],
                "evidence": json.loads(row["evidence_json"]),
                "source_experiment_id": row["source_experiment_id"],
                "ontology_version": row["ontology_version"],
            }
            for row in entity_rows
        ]
        relations = [
            {
                "id": row["id"], "relation_type": row["relation_type"],
                "source_id": row["source_id"], "source_type": row["source_type"],
                "target_id": row["target_id"], "target_type": row["target_type"],
                "properties": json.loads(row["properties_json"]), "confidence": row["confidence"],
                "assertion_method": row["assertion_method"], "status": row["status"],
                "evidence": json.loads(row["evidence_json"]),
                "source_experiment_id": row["source_experiment_id"],
                "ontology_version": row["ontology_version"],
            }
            for row in relation_rows
        ]
        if not entities and not relations:
            return KnowledgeSubgraph(source_experiment_id=experiment_id)
        return KnowledgeSubgraph(
            source_experiment_id=experiment_id,
            entities=entities,
            relations=relations,
        )

    def get_graph_summary(self, experiment_id: str) -> dict[str, Any] | None:
        if not self.get_experiment(experiment_id):
            return None
        with self.connect() as conn:
            entity_rows = conn.execute(
                """SELECT entity_type,COUNT(*) AS count FROM graph_entities
                   WHERE source_experiment_id=? GROUP BY entity_type ORDER BY entity_type""",
                (experiment_id,),
            ).fetchall()
            relation_rows = conn.execute(
                """SELECT relation_type,COUNT(*) AS count FROM graph_relations
                   WHERE source_experiment_id=? GROUP BY relation_type ORDER BY relation_type""",
                (experiment_id,),
            ).fetchall()
            versions = [row[0] for row in conn.execute(
                "SELECT DISTINCT ontology_version FROM graph_entities WHERE source_experiment_id=?",
                (experiment_id,),
            ).fetchall()]
        return {
            "experiment_id": experiment_id,
            "ontology_versions": versions,
            "entity_count": sum(row["count"] for row in entity_rows),
            "relation_count": sum(row["count"] for row in relation_rows),
            "entities_by_type": {row["entity_type"]: row["count"] for row in entity_rows},
            "relations_by_type": {row["relation_type"]: row["count"] for row in relation_rows},
        }

    def query_observations(
        self,
        experiment_id: str,
        *,
        dataset_variant_ids: list[str] | None = None,
        method_variant_ids: list[str] | None = None,
        metric_names: list[str] | None = None,
        dimension_filters: dict[str, Any] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses = ["o.experiment_id=?"]
        params: list[Any] = [experiment_id]
        for column, values in (
            ("o.dataset_variant_id", dataset_variant_ids or []),
            ("o.method_variant_id", method_variant_ids or []),
            ("o.metric_name", metric_names or []),
        ):
            if values:
                clauses.append(f"{column} IN ({','.join('?' for _ in values)})")
                params.extend(values)
        params.append(10000)
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT o.*,dv.display_name AS dataset_variant,
                    mv.display_name AS method_variant
                    FROM observations o
                    JOIN dataset_variants dv ON dv.id=o.dataset_variant_id
                    LEFT JOIN method_variants mv ON mv.id=o.method_variant_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY o.source_row,o.source_column LIMIT ?""",
                params,
            ).fetchall()
        filters = dimension_filters or {}
        result: list[dict[str, Any]] = []
        for row in rows:
            item = self._decode(row, ("dimensions_json",))
            if item is None or any(item["dimensions"].get(key) != value for key, value in filters.items()):
                continue
            result.append(item)
            if len(result) >= limit:
                break
        return result

    def export_observations(self, experiment_ids: list[str], *, limit: int = 100000) -> list[dict[str, Any]]:
        """Export normalized observations from multiple experiments with canonical labels."""
        ids = list(dict.fromkeys(experiment_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT o.*,e.name AS experiment_name,d.name AS dataset,
                    dv.display_name AS dataset_variant,m.name AS method,
                    mv.display_name AS method_variant
                    FROM observations o
                    JOIN experiments e ON e.id=o.experiment_id
                    JOIN dataset_variants dv ON dv.id=o.dataset_variant_id
                    JOIN datasets d ON d.id=dv.dataset_id
                    LEFT JOIN method_variants mv ON mv.id=o.method_variant_id
                    LEFT JOIN methods m ON m.id=mv.method_id
                    WHERE o.experiment_id IN ({placeholders})
                    ORDER BY e.created_at,o.source_row,o.source_column LIMIT ?""",
                [*ids, min(max(limit, 1), 100000)],
            ).fetchall()
        return [self._decode(row, ("dimensions_json",)) for row in rows]  # type: ignore[misc]

    def create_visualization(self, data: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO visualizations
                   (id, experiment_id, request_text, status, spec_json, code_path,
                    image_path, svg_path, error_message, created_at, attempt_count, model_name, token_usage_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (data["id"], data["experiment_id"], data["request_text"], data["status"],
                 json.dumps(data["spec"], ensure_ascii=False), data.get("code_path"),
                 data.get("image_path"), data.get("svg_path"), data.get("error_message"), data["created_at"],
                 data.get("attempt_count", 0), data.get("model_name"),
                 json.dumps(data.get("token_usage", {}), ensure_ascii=False)),
            )
            source_ids = list(dict.fromkeys(data.get("source_experiment_ids") or [data["experiment_id"]]))
            conn.executemany(
                "INSERT OR IGNORE INTO visualization_sources (visualization_id,experiment_id) VALUES (?,?)",
                [(data["id"], experiment_id) for experiment_id in source_ids],
            )

    def get_visualization(self, visualization_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM visualizations WHERE id=?", (visualization_id,)).fetchone()
            source_rows = conn.execute(
                """SELECT e.id,e.name,e.filename FROM visualization_sources s
                   JOIN experiments e ON e.id=s.experiment_id
                   WHERE s.visualization_id=? ORDER BY e.created_at""",
                (visualization_id,),
            ).fetchall()
        result = self._decode(row, ("spec_json", "token_usage_json"))
        if result is not None:
            result["sources"] = [dict(item) for item in source_rows]
            result["source_experiment_ids"] = [item["id"] for item in source_rows]
        return result

    def update_visualization_artifacts(
        self,
        visualization_id: str,
        *,
        spec: dict[str, Any],
        code_path: str,
        image_path: str,
        svg_path: str | None = None,
        status: str = "SUCCEEDED",
        error_message: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE visualizations SET spec_json=?,code_path=?,image_path=?,svg_path=?,status=?,error_message=?
                   WHERE id=?""",
                (json.dumps(spec, ensure_ascii=False), code_path, image_path, svg_path, status, error_message, visualization_id),
            )
