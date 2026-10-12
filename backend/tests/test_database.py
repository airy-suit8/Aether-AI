from src.db.database import (
    create_user, get_user_by_username,
    save_document_record, get_all_documents_detailed, clear_user_documents,
    save_conversation, get_conversation_history
)

def test_user_creation_and_retrieval():
    username = "db_test_user"
    user_id = create_user(username, "hash123")
    assert user_id > 0
    
    user = get_user_by_username(username)
    assert user is not None
    assert user["id"] == user_id
    assert user["username"] == username
    assert user["password_hash"] == "hash123"

def test_document_records():
    user_id = create_user("doc_user", "hash")
    
    # Save a document
    save_document_record(user_id, "test.pdf", pages=5, chunks=20)
    
    # List documents
    docs = get_all_documents_detailed(user_id)
    assert len(docs) == 1
    assert docs[0]["filename"] == "test.pdf"
    
    # Clear documents
    clear_user_documents(user_id)
    assert len(get_all_documents_detailed(user_id)) == 0

def test_conversation_logging():
    user_id = create_user("chat_user", "hash")
    save_conversation(user_id, "sess1", "hello", "hi")
    
    history = get_conversation_history(user_id, "sess1")
    assert len(history) == 1
    assert history[0]["question"] == "hello"
    assert history[0]["answer"] == "hi"
