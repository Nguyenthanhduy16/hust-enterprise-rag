import os
from dotenv import load_dotenv
load_dotenv()

from transformers.masking_utils import chunked_overlay
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma  
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

# === Load PDF === 
file_path = 'data/raw/02_gioi thieu NoteBookLM.pdf' 
loader = PyPDFLoader(file_path) 
pages = loader.load() 
print(f"Tổng số trang: {len(pages)}")


# === Chunking ===
splitter = RecursiveCharacterTextSplitter(
    chunk_size = 200, 
    chunk_overlap = 50
)
chunks= splitter.split_documents(pages)
print(f"Số chunks: {len(chunks)}")

# === Embedding + Store vao Vector DB ===
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = Chroma.from_documents(chunks, embeddings)
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

# === RAG Chain ===
template = """Trả lời câu hỏi dựa trên context sau.
Nếu không tìm thấy, nói "Tôi không tìm thấy trong tài liệu."
Trích dẫn nguồn (trang số) nếu có thể.

Context:
{context}

Câu hỏi: {question}
"""
prompt = ChatPromptTemplate.from_template(template)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

rag_chain = (
    {"context": retriever, "question": RunnablePassthrough()}
    | prompt
    | llm
)
# Tạo embedding cho một câu bất kỳ
sample_vector = embeddings.embed_query("Đây là một câu cần được chuyển thành vector")
print(f"Kiểu dữ liệu: {type(sample_vector)}")
print(f"Số chiều (độ dài của vector): {len(sample_vector)}") 
print(f"5 giá trị đầu tiên của vector: {sample_vector[:5]}")




# # === Testing ===
# while True:
#     question = input("\nHỏi: ")
#     if question.lower() in ["quit", "exit"]:
#         break
#     answer = rag_chain.invoke(question)
#     print(f"\n Trả lời: {answer.content}")

