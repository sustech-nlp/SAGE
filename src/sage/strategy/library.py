"""FAISS-backed Vulnerability Codex.

The library stores structured failure patterns, embeds their summaries with an
OpenAI-compatible embedding endpoint, and retrieves similar entries by FAISS
L2 distance for later attack rounds.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import faiss
import numpy as np
from openai import OpenAI
from sklearn.cluster import KMeans
from tqdm import tqdm

from sage.agents.builders import get_summary_strategy_prompt
from sage.agents.types import ErrorStrategies, ErrorType, StrategyEntity, ToleranceLevel
from sage.prompts.formatting import format_response_json
from sage.server.client import LLMClient, _resolve_api_key
from sage.utils.threading import Task, run_task_multithreaded

if TYPE_CHECKING:  # pragma: no cover
    pass


class StrategyLib:
    """The Vulnerability Codex.

    Embeds the ``errorSummary`` of every :class:`StrategyEntity` via an
    OpenAI-compatible embedding server, stores the vectors in an L2 FAISS
    index, and supports semantic-distance retrieval + Summarizer-driven
    semantic compression of near-duplicate clusters.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8002/v1",
        summary_model_url: str = "http://127.0.0.1:8000/v1",
        embedding_model: str = "localModel",
        summary_model: str = "localModel",
    ) -> None:
        self.model = OpenAI(base_url=base_url, api_key=_resolve_api_key(None))
        self.embedding_model_name = embedding_model
        self.summary_model = LLMClient(base_url=summary_model_url, model=summary_model)
        self.index: faiss.Index | None = None
        self.id_to_strategy: dict[int, StrategyEntity] = {}
        self.next_id: int = 0

    # ------------------------------------------------------------------
    # Insertion
    # ------------------------------------------------------------------
    def update_bench(self, item_list: list[StrategyEntity]) -> None:
        """Embed each ``errorSummary`` and append to the index."""
        if not item_list:
            return
        texts = [item.errorStrategies.errorSummary for item in item_list]
        try:
            response = self.model.embeddings.create(input=texts, model=self.embedding_model_name)
        except Exception as e:
            print("embedding error", e)
            print(texts)
            return

        embeddings = [np.array(d.embedding, dtype=np.float32) for d in response.data]
        if not embeddings:
            return

        if self.index is None:
            self.index = faiss.IndexFlatL2(len(embeddings[0]))

        vector_dim = len(embeddings[0])
        assert vector_dim == self.index.d, (
            f"FAISS index dim {self.index.d} ≠ embedding dim {vector_dim}"
        )

        self.index.add(np.vstack(embeddings))
        for vec_id, item in enumerate(item_list):
            self.id_to_strategy[self.next_id + vec_id] = item
        self.next_id += len(item_list)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def search(self, item: StrategyEntity, top_k: int = 5) -> list[StrategyEntity]:
        """Find up to ``top_k`` codex entries that share ``item``'s tolerance level."""
        # Codex may be empty if no A-class successes have been seen yet
        # (e.g. cold-start / smoke runs). Bail out before computing the query
        # embedding to avoid a wasted server call.
        if self.index is None or self.index.ntotal == 0:
            return []
        query_text = item.errorStrategies.errorSummary
        try:
            response = self.model.embeddings.create(
                input=[query_text], model=self.embedding_model_name
            )
        except Exception as e:
            print("embedding error", e)
            print(query_text)
            return []
        query_vec = np.array(response.data[0].embedding, dtype=np.float32).reshape(1, -1)

        print(f"[info] Searching for similar strategies with top_k={top_k}...")
        _, indices = self.index.search(query_vec, top_k * 3)  # over-fetch for filtering
        results: list[StrategyEntity] = []
        for idx in indices[0]:
            if idx == -1:
                continue
            candidate = self.id_to_strategy.get(int(idx))
            if not candidate:
                continue
            if (
                candidate.toleranceLevel == item.toleranceLevel
                and candidate.errorStrategies.errorDetail != item.errorStrategies.errorDetail
            ):
                results.append(candidate)
            if len(results) >= top_k:
                break
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self, path: str) -> None:
        """Persist the FAISS index + ``id_to_strategy`` map to ``path``."""
        os.makedirs(path, exist_ok=True)
        if self.index:
            faiss.write_index(self.index, os.path.join(path, "index.faiss"))
        meta = {
            "next_id": self.next_id,
            "id_to_strategy": {str(k): v.to_dict() for k, v in self.id_to_strategy.items()},
        }
        with open(os.path.join(path, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def load(self, path: str) -> None:
        """Restore a previously saved index + metadata."""
        index_path = os.path.join(path, "index.faiss")
        self.index = faiss.read_index(index_path) if os.path.exists(index_path) else None
        with open(os.path.join(path, "metadata.json"), "r", encoding="utf-8") as f:
            meta = json.load(f)
            self.next_id = meta["next_id"]
            self.id_to_strategy = {
                int(k): StrategyEntity.from_dict(v) for k, v in meta["id_to_strategy"].items()
            }

    def delete(self) -> None:
        """Drop the in-memory index and id map."""
        self.index = None
        self.id_to_strategy.clear()
        self.next_id = 0

    # ------------------------------------------------------------------
    # Semantic compression (step 7 in paper Fig. 1)
    # ------------------------------------------------------------------
    def compress(self, threshold: float = 0.1, top_k: int = 10) -> None:
        """Merge near-duplicate entries via the Summarizer model.

        For every unprocessed seed, find all entries within ``threshold`` L2
        distance; if more than one is found, ask the Summarizer to compress
        them into a smaller list. Singletons are kept as-is. Finally, rebuild
        the index from the new list.
        """
        processed: set[int] = set()
        all_ids = list(self.id_to_strategy.keys())

        grouped_tasks: list[Task] = []
        new_strategies: list[StrategyEntity] = []

        # Cluster by L2 distance.
        for seed_id in tqdm(all_ids):
            if seed_id in processed:
                continue
            seed_item = self.id_to_strategy[seed_id]
            seed_vec = self.index.reconstruct(seed_id).reshape(1, -1)
            distances, indices = self.index.search(seed_vec, top_k * 3)

            group: list[StrategyEntity] = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx == -1 or idx in processed:
                    continue
                if dist <= threshold:
                    group.append(self.id_to_strategy[int(idx)])
                    processed.add(int(idx))

            if len(group) <= 1:
                new_strategies.append(seed_item)
                processed.add(seed_id)
                continue

            prompt = get_summary_strategy_prompt(group)
            grouped_tasks.append(
                Task(
                    func=self.summary_model.chat_with_llm_only,
                    args=[[{"role": "user", "content": prompt}], format_response_json, 3],
                    default_result=[],
                )
            )

        # Run Summarizer calls in parallel.
        result_lists = (
            run_task_multithreaded(task_list=grouped_tasks) if grouped_tasks else []
        )

        # Parse compressed results.
        for result_group in result_lists:
            try:
                compressed = [StrategyEntity.from_dict(item) for item in result_group[0]]
                new_strategies.extend(compressed)
            except Exception as e:
                print("Failed to convert compressed result:", e)

        # Rebuild the index.
        self.delete()
        self.update_bench(new_strategies)

    # ------------------------------------------------------------------
    # KMeans-based grouping (analysis tool — paper Appendix-style)
    # ------------------------------------------------------------------
    def compress_by_group(
        self,
        path: str,
        type: ErrorType | None = None,
        group_num: int = 10,
        sample_size: int = 10,
    ) -> list[dict]:
        """Run KMeans over the codex embeddings and dump per-cluster metadata.

        Does NOT mutate the in-memory codex; the result is purely an analysis
        artifact written under ``path/metadata.json``. Used by the paper's
        Appendix A.1 "Novel Patterns" analysis to surface error archetypes.
        """
        if not isinstance(path, str) or path.strip() == "":
            raise ValueError("path must be a non-empty string")

        if len(self.id_to_strategy) == 0:
            os.makedirs(path, exist_ok=True)
            with open(os.path.join(path, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            return []

        orig_ids = list(self.id_to_strategy.keys())
        orig_items = [self.id_to_strategy[_id] for _id in orig_ids]

        if type is not None:
            filtered = [
                (i, item)
                for i, item in zip(orig_ids, orig_items)
                if getattr(item.errorStrategies, "errorType", None) == type
            ]
            if filtered:
                orig_ids, orig_items = zip(*filtered)  # type: ignore[assignment]
                orig_ids, orig_items = list(orig_ids), list(orig_items)
            else:
                orig_ids, orig_items = [], []

        valid_indices: list[int] = []
        embeddings: list[np.ndarray] = []
        for i, item in enumerate(tqdm(orig_items, desc="Generating embeddings")):
            try:
                text = item.errorStrategies.errorSummary
            except Exception:
                continue
            try:
                resp = self.model.embeddings.create(input=[text], model=self.embedding_model_name)
                embeddings.append(np.array(resp.data[0].embedding, dtype=np.float32))
                valid_indices.append(i)
            except Exception as e:
                print(f"[warn] embedding failed for index {i}: {e}")
                continue

        if not embeddings:
            os.makedirs(path, exist_ok=True)
            with open(os.path.join(path, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            return []

        X = np.vstack(embeddings)
        n_clusters = min(max(1, group_num), X.shape[0])
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X)

        clusters: dict[int, list[int]] = {}
        for i_valid, lab in enumerate(labels):
            clusters.setdefault(int(lab), []).append(valid_indices[i_valid])

        results = []
        for lab, member_orig_idxs in clusters.items():
            member_positions = [j for j, v in enumerate(valid_indices) if v in member_orig_idxs]
            if not member_positions:
                continue
            centroid = kmeans.cluster_centers_[lab]
            member_embs = X[member_positions]
            dists = np.linalg.norm(member_embs - centroid.reshape(1, -1), axis=1)
            closest_pos = member_positions[int(np.argmin(dists))]
            representative = orig_items[valid_indices[closest_pos]]

            try:
                category_name = representative.errorStrategies.errorSummary
            except Exception:
                category_name = f"cluster_{lab}"

            selected_idxs = member_orig_idxs[:sample_size]
            summary_strategies = [orig_items[idx].to_dict() for idx in selected_idxs]
            group_summaries = [orig_items[idx].to_dict() for idx in member_orig_idxs]

            results.append(
                {
                    "summary": {
                        "category_name": category_name,
                        "summary_strategies": summary_strategies,
                    },
                    "len": len(member_orig_idxs),
                    "group": group_summaries,
                }
            )

        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[info] Saved metadata to {path}/metadata.json. Groups: {len(results)}")
        return results
