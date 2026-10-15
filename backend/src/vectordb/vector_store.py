"""
vectordb/vector_store.py — the vector store: ChromaDB on disk, one collection, cosine distance.

Each chunk is tagged with its owner's tenant id, a random id from the users table, and every
read is filtered by it (S2). The tenant id is the key, not the integer user id, because user ids
restart in a new database while this store lives on in its own folder.

The store opens on first use, so importing this module opens nothing. Reading, re-tagging and
deleting chunks need no API key; adding and searching do (they embed text).

The collection records the embedding model that made its vectors. Vectors from two models cannot
be compared, so once the configured model differs, adding and searching stop with a
ModelSetupError that says how to re-embed (python -m src.reembed); reading and deleting go on.
"""

from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import chromadb
import numpy as np
from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.core.config import Settings, settings
from src.embeddings import embedder
from src.embeddings.embedder import ModelSetupError

# How many recent query embeddings embed_query() keeps
QUERY_VECTORS_KEPT = 32

# Cosine distance, so relevance scores are cosine similarity (Chroma's default is L2). Only
# applies when the collection is created.
COLLECTION_CONFIGURATION = {"hnsw": {"space": "cosine"}}

# The collection's metadata key for the model that made its vectors
EMBEDDING_KEY = "embedding"
# A store made before the model was recorded was made by Gemini's default embedding model
FIRST_EMBEDDING = Settings.model_fields["embedding_provider"].default + ":" + Settings.model_fields["embedding_model"].default

# How many passages python -m src.reembed embeds in one request
REEMBED_BATCH = 64


class VectorStore:
    """Every tenant's chunks in one ChromaDB collection on disk, each tagged with its tenant_id."""
    collection_name = "aether_collection"
    # Where src.reembed builds the new vectors before they replace the old ones
    rebuild_name = "aether_collection_reembed"

    def __init__(self):
        self._client = None
        self._collection = None
        self._chroma = None
        self._versions: Dict[str, int] = {}
        self._query_vectors: "OrderedDict[str, List[float]]" = OrderedDict()

    def _path(self) -> Path:
        return Path(settings.vector_store_dir) / "chroma_db"

    def exists(self) -> bool:
        """True when a store has been created on disk."""
        return (self._path() / "chroma.sqlite3").exists()

    @property
    def collection(self) -> chromadb.Collection:
        """The Chroma collection itself, for reads, metadata updates and deletes (no embedding model needed)."""
        if self._collection is None:
            self._path().mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._path()))
            self._finish_interrupted_rebuild()
            self._collection = self._client.get_or_create_collection(
                self.collection_name, configuration=COLLECTION_CONFIGURATION)
        return self._collection

    def embedding_model(self) -> str:
        """The embedding model that made the stored vectors ("provider:model"). An empty store has
        no vectors to keep apart, so it takes the configured model, whatever it recorded before."""
        coll = self.collection
        recorded = (coll.metadata or {}).get(EMBEDDING_KEY)
        if coll.count():
            return recorded or FIRST_EMBEDDING
        if recorded != settings.embedding_label():
            coll.modify(metadata={EMBEDDING_KEY: settings.embedding_label()})
        return settings.embedding_label()

    def embedding_model_changed(self) -> Optional[str]:
        """What to tell the person asking when the stored vectors are not the configured model's,
        or None when they are."""
        stored = self.embedding_model()
        if stored == settings.embedding_label():
            return None
        return (f"The documents here were read with the embedding model {stored}, and the app is now set to "
                f"use {settings.embedding_label()}. Their passages cannot be searched until they are read "
                "again: stop the server and run python -m src.reembed --apply in backend/, or set the "
                "embedding model back.")

    @property
    def chroma(self) -> Chroma:
        """The same collection through LangChain, which embeds text: needs the configured embedding
        model, and stored vectors made by that model."""
        if self._chroma is None:
            changed = self.embedding_model_changed()  # opens the client
            if changed:
                raise ModelSetupError(changed)
            self._chroma = Chroma(
                collection_name=self.collection_name,
                embedding_function=embedder.get_embeddings(),
                client=self._client,
                collection_configuration=COLLECTION_CONFIGURATION,
            )
        return self._chroma

    def version(self, tenant: str) -> int:
        """A number that changes whenever this tenant's chunks change, for anything cached from them.

        Kept in this process: the app runs as one server process (as the conversation cache and
        the rate limiter already assume).
        """
        return self._versions.get(tenant, 0)

    def _changed(self, tenant: str) -> None:
        self._versions[tenant] = self._versions.get(tenant, 0) + 1

    def add_documents(self, tenant: str, documents: List[Document]):
        """Directly add Document objects to Chroma, tagged with the tenant id."""
        for doc in documents:
            doc.metadata["tenant_id"] = tenant
        self.chroma.add_documents(documents)
        self._changed(tenant)

    def embed_query(self, query: str) -> List[float]:
        """The query's embedding. The last few are kept, so one question is embedded once even
        when both the search and similarities() need its vector."""
        vector = self._query_vectors.get(query)
        if vector is None:
            vector = self.chroma.embeddings.embed_query(query)
            self._query_vectors[query] = vector
            while len(self._query_vectors) > QUERY_VECTORS_KEPT:
                self._query_vectors.popitem(last=False)
        return vector

    @staticmethod
    def _where(tenant: str, document_ids: Optional[List[int]] = None) -> Dict:
        """A Chroma filter for one tenant's chunks, of some of its documents when ids are given."""
        if document_ids is None:
            return {"tenant_id": tenant}
        return {"$and": [{"tenant_id": tenant}, {"document_id": {"$in": list(document_ids)}}]}

    def similarity_search(self, tenant: str, query: str, k: int,
                          document_ids: Optional[List[int]] = None) -> List[Tuple[Document, float]]:
        """The k chunks of one tenant closest to the query, with cosine similarity scores from 0 to 1;
        only of the documents named by document_ids, when given."""
        vector = self.embed_query(query)
        where = self._where(tenant, document_ids)
        found = self.chroma.similarity_search_by_vector_with_relevance_scores(vector, k=k, filter=where)
        # Chroma returns cosine distance. Rounding can put an exact match just above 1, and an
        # opposite vector is below 0; both are clamped so a score is always a share of 1.
        hits = [(doc, max(0.0, min(1.0, 1.0 - distance))) for doc, distance in found]
        # Chroma's index search can return fewer of a tenant's chunks than the tenant has, or none
        # at all, when the store holds many identical vectors (second audit, N4). Then the
        # tenant's chunks are compared one by one, which misses nothing. A tenant who simply has
        # fewer than k chunks costs one count and no more.
        if len(hits) < k and len(self.collection.get(where=where, include=[])["ids"]) > len(hits):
            return self._exact_search(where, vector, k)
        return hits

    def _exact_search(self, where: Dict, vector: List[float], k: int) -> List[Tuple[Document, float]]:
        """The k chunks the filter selects closest to the vector, by comparing it with every one of them."""
        res = self.collection.get(where=where, include=["documents", "metadatas", "embeddings"])
        if not res["ids"]:
            return []
        chunks = np.asarray(res["embeddings"], dtype=np.float32)
        query_vector = np.asarray(vector, dtype=np.float32)
        norms = np.linalg.norm(chunks, axis=1) * np.linalg.norm(query_vector)
        cosines = np.divide(chunks @ query_vector, norms, out=np.zeros(len(chunks), dtype=np.float32), where=norms > 0)
        nearest = np.argsort(-cosines, kind="stable")[:k]
        return [
            (Document(page_content=res["documents"][i], metadata=res["metadatas"][i]), max(0.0, min(1.0, float(cosines[i]))))
            for i in nearest
        ]

    def similarities(self, tenant: str, query: str, chunk_ids: List[str]) -> Dict[str, float]:
        """The cosine similarity (0 to 1) between the query and each named chunk of one tenant."""
        if not chunk_ids:
            return {}
        res = self.collection.get(
            where={"$and": [{"tenant_id": tenant}, {"chunk_id": {"$in": list(chunk_ids)}}]},
            include=["metadatas", "embeddings"],
        )
        query_vector = np.asarray(self.embed_query(query), dtype=float)
        scores = {}
        for meta, vector in zip(res["metadatas"], res["embeddings"]):
            vector = np.asarray(vector, dtype=float)
            norms = float(np.linalg.norm(query_vector) * np.linalg.norm(vector))
            cosine = float(query_vector @ vector) / norms if norms else 0.0
            scores[meta["chunk_id"]] = max(0.0, min(1.0, cosine))
        return scores

    def first_passages(self, tenant: str) -> Dict[int, Tuple[str, Dict]]:
        """The first passage of each of a tenant's documents, by document id: where a paper or a
        letter says what it is and who wrote it. Passages are numbered from 1 (chunk_index)."""
        res = self.collection.get(where={"$and": [{"tenant_id": tenant}, {"chunk_index": 1}]},
                                  include=["documents", "metadatas"])
        return {meta["document_id"]: (text, meta) for text, meta in zip(res["documents"], res["metadatas"])
                if meta.get("document_id") is not None}

    def passages_around(self, tenant: str, document_id: int, chunk_index: int, window: int) -> List[Tuple[str, Dict]]:
        """The passages within `window` places of one passage in its document, the passage itself
        not included, in document order."""
        return self.passages_at(tenant, document_id,
                                [i for i in range(chunk_index - window, chunk_index + window + 1) if i != chunk_index])

    def passages_at(self, tenant: str, document_id: int, indexes: List[int]) -> List[Tuple[str, Dict]]:
        """Some passages of one of a tenant's documents, by their numbers (from 1), in document order;
        a number it does not have is left out."""
        indexes = [i for i in indexes if i >= 1]
        if not indexes:
            return []
        res = self.collection.get(where={"$and": [{"tenant_id": tenant}, {"document_id": document_id},
                                                  {"chunk_index": {"$in": indexes}}]},
                                  include=["documents", "metadatas"])
        return sorted(zip(res["documents"], res["metadatas"]), key=lambda tm: tm[1].get("chunk_index", 0))

    def get_user_chunks(self, tenant: str) -> Tuple[List[str], List[Dict]]:
        """Every chunk text and its metadata for one tenant."""
        res = self.collection.get(where={"tenant_id": tenant}, include=["documents", "metadatas"])
        return res.get("documents", []), res.get("metadatas", [])

    def delete_document_chunks(self, tenant: str, document_id: int, filename: Optional[str] = None) -> int:
        """Delete the chunks of one of a tenant's documents and return how many there were (R7).
        With a filename, chunks of that name stored before documents had ids go too."""
        coll = self.collection
        chunk_ids = coll.get(where={"$and": [{"tenant_id": tenant}, {"document_id": document_id}]}, include=[])["ids"]
        if not chunk_ids and filename:
            # Chunks stored before documents had an id carry only the file name
            named = coll.get(where={"$and": [{"tenant_id": tenant}, {"source": filename}]}, include=["metadatas"])
            chunk_ids = [i for i, meta in zip(named["ids"], named["metadatas"]) if "document_id" not in meta]
        if chunk_ids:
            coll.delete(ids=chunk_ids)
        self._changed(tenant)
        return len(chunk_ids)

    def delete_user_chunks(self, tenant: str) -> int:
        """Delete every chunk of one tenant and return how many there were. Errors propagate."""
        coll = self.collection
        chunk_ids = coll.get(where={"tenant_id": tenant}, include=[])["ids"]
        if chunk_ids:
            coll.delete(where={"tenant_id": tenant})
        self._changed(tenant)
        return len(chunk_ids)

    # ── Every tenant at once, for python -m src.maintenance ───────────────────

    def all_chunks(self) -> Tuple[List[str], List[Dict]]:
        """The ids and metadata of every chunk in the store."""
        res = self.collection.get(include=["metadatas"])
        return res["ids"], res["metadatas"]

    def delete_chunks(self, chunk_ids: List[str]) -> int:
        """Delete chunks by id, whichever tenant they belong to. Returns how many were asked for."""
        if chunk_ids:
            tenants = {meta.get("tenant_id") for meta in self.collection.get(ids=list(chunk_ids), include=["metadatas"])["metadatas"]}
            self.collection.delete(ids=list(chunk_ids))
            for tenant in tenants - {None}:
                self._changed(tenant)
        return len(chunk_ids)

    # ── Chunks stored before tenant ids (keyed by the integer user_id) ────────

    def chunks_without_tenant(self) -> Tuple[List[str], List[Dict]]:
        """The ids and metadata of chunks still keyed by an integer user_id."""
        res = self.collection.get(where={"user_id": {"$gte": 0}}, include=["metadatas"])
        return res["ids"], res["metadatas"]

    def set_tenants(self, tenants: Dict[str, str]) -> None:
        """Re-key chunks: give each chunk id its tenant id and drop its user_id."""
        if not tenants:
            return
        ids = list(tenants)
        self.collection.update(ids=ids, metadatas=[{"tenant_id": tenants[i], "user_id": None} for i in ids])
        for tenant in set(tenants.values()):
            self._changed(tenant)

    # ── Another embedding model, for python -m src.reembed ────────────────────

    def reembed(self, progress: Callable[[int, int], None] = lambda done, total: None) -> int:
        """Embed every stored passage again with the configured embedding model, keeping its id, text
        and metadata, and return how many there were. The new vectors are built in a collection of
        their own and replace the old ones only once all are made, so a failure part-way leaves
        the store as it was. progress(done, total) is called after each batch."""
        coll = self.collection
        res = coll.get(include=["documents", "metadatas"])
        ids, texts, metas = res["ids"], res["documents"], res["metadatas"]
        try:
            self._client.delete_collection(self.rebuild_name)  # left by a run that failed
        except Exception:
            pass
        rebuild = self._client.create_collection(self.rebuild_name, configuration=COLLECTION_CONFIGURATION,
                                                 metadata={EMBEDDING_KEY: settings.embedding_label()})
        embeddings = embedder.get_embeddings()
        for start in range(0, len(ids), REEMBED_BATCH):
            end = start + REEMBED_BATCH
            rebuild.add(ids=ids[start:end], documents=texts[start:end], metadatas=metas[start:end],
                        embeddings=embeddings.embed_documents(texts[start:end]))
            progress(min(end, len(ids)), len(ids))
        # Complete: from here on the rebuild is the store, even if this process stops before the rename
        rebuild.modify(metadata={EMBEDDING_KEY: settings.embedding_label(), "complete": True})
        self._client.delete_collection(self.collection_name)
        self._finish_interrupted_rebuild()
        self._collection = self._client.get_collection(self.collection_name)
        self._chroma = None
        self._query_vectors.clear()
        for tenant in {meta.get("tenant_id") for meta in metas} - {None}:
            self._changed(tenant)
        return len(ids)

    def _finish_interrupted_rebuild(self) -> None:
        """A complete rebuild whose old collection is already deleted becomes the store. One that is
        not complete is left for the next python -m src.reembed to replace."""
        names = {getattr(c, "name", c) for c in self._client.list_collections()}
        if self.rebuild_name not in names or self.collection_name in names:
            return
        rebuild = self._client.get_collection(self.rebuild_name)
        if (rebuild.metadata or {}).get("complete"):
            rebuild.modify(name=self.collection_name, metadata={EMBEDDING_KEY: rebuild.metadata[EMBEDDING_KEY]})


# Module-level singleton — opens the store on first use
store = VectorStore()
