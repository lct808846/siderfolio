"""Persistent RAG operations and isolated index generations; schema6."""

import json

from astroagent.conversations import encode, utc_now


def migrate(db):
    db.execute(
        "CREATE TABLE rag_indexes (id TEXT PRIMAR"
        "Y KEY,project_id TEXT NOT NULL REFERENCE"
        "S projects(id) ON DELETE CASCADE,request"
        "_id TEXT NOT NULL,request_hash TEXT NOT "
        "NULL,state TEXT NOT NULL,record TEXT NOT"
        " NULL,UNIQUE(project_id,request_id))"
    )
    db.execute(
        "CREATE TABLE rag_active (project_id TEXT"
        " PRIMARY KEY REFERENCES projects(id) ON "
        "DELETE CASCADE,index_id TEXT NOT NULL RE"
        "FERENCES rag_indexes(id) ON DELETE CASCA"
        "DE)"
    )
    db.execute(
        "CREATE TABLE rag_vectors (index_id TEXT "
        "NOT NULL REFERENCES rag_indexes(id) ON D"
        "ELETE CASCADE,unit_id TEXT NOT NULL,vers"
        "ion_id TEXT NOT NULL,document_id TEXT NO"
        "T NULL,project_id TEXT NOT NULL REFERENC"
        "ES projects(id) ON DELETE CASCADE,text_s"
        "ha256 TEXT NOT NULL,embedding vector NOT"
        " NULL,PRIMARY KEY(index_id,unit_id))"
    )
    db.execute("CREATE INDEX rag_vector_scope ON rag_vectors(project_id,index_id,version_id)")
    db.execute(
        "CREATE TABLE rag_previews (id TEXT PRIMA"
        "RY KEY,project_id TEXT NOT NULL REFERENC"
        "ES projects(id) ON DELETE CASCADE,record"
        " TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE rag_answers (id TEXT PRIMAR"
        "Y KEY,project_id TEXT NOT NULL REFERENCE"
        "S projects(id) ON DELETE CASCADE,request"
        "_id TEXT NOT NULL,request_hash TEXT NOT "
        "NULL,state TEXT NOT NULL,record TEXT NOT"
        " NULL,reserved_bytes INTEGER NOT NULL DE"
        "FAULT 0,UNIQUE(project_id,request_id))"
    )
    db.execute(
        "CREATE TABLE rag_answer_requests (id TEX"
        "T PRIMARY KEY,project_id TEXT NOT NULL R"
        "EFERENCES projects(id) ON DELETE CASCADE"
        ",request_id TEXT NOT NULL,request_hash T"
        "EXT NOT NULL,answer_id TEXT NOT NULL,rec"
        "ord TEXT NOT NULL,UNIQUE(project_id,requ"
        "est_id))"
    )


def recover(db):
    for table in ("rag_indexes", "rag_answers"):
        for row in db.execute(
            f"SELECT id,record FROM {table} WHERE state IN ('pending','running')"
        ).fetchall():
            value = json.loads(row[1])
            value.update(
                state="interrupted",
                completed_at=utc_now(),
                error="服务重启中断；未自动重试模型调用或构建。",
            )
            db.execute(
                f"UPDATE {table} SET state='interrupted',record=?"
                + (",reserved_bytes=0" if table == "rag_answers" else "")
                + " WHERE id=?",
                (encode(value), row[0]),
            )


def used_bytes(db):
    return (
        sum(
            db.execute(f"SELECT coalesce(sum(octet_length(record)),0) FROM {table}").fetchone()[0]
            for table in ("rag_indexes", "rag_previews", "rag_answers", "rag_answer_requests")
        )
        + db.execute("SELECT count(*)*128 FROM rag_active").fetchone()[0]
        + db.execute("SELECT coalesce(sum(reserved_bytes),0) FROM rag_answers").fetchone()[0]
    )


def vector_bytes(db):
    return db.execute(
        "SELECT coalesce(sum(pg_column_size(embed"
        "ding)+octet_length(unit_id)+octet_length"
        "(index_id)+octet_length(version_id)+octe"
        "t_length(document_id)+octet_length(proje"
        "ct_id)+octet_length(text_sha256)+64),0)+"
        "pg_indexes_size('rag_vectors') FROM rag_"
        "vectors"
    ).fetchone()[0]
