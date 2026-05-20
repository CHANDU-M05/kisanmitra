"""
api/services/rag.py — Vertical Slice 4 (RAG Pipeline)

Generative AI layer for the KisanMitra WhatsApp Bot.
Retrieves context from PostgreSQL via pgvector and generates
Kannada agronomy advice using GPT-4.
"""
from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from api.core.config import settings
from api.core.models import KnowledgeChunk

logger = logging.getLogger("kisanmitra.rag")

# Initialize models only if API key is present
_embeddings = None
_llm = None

if settings.openai_api_key and settings.openai_api_key != "fill_this_later":
    try:
        _embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small", 
            openai_api_key=settings.openai_api_key
        )
        _llm = ChatOpenAI(
            model="gpt-4o", 
            openai_api_key=settings.openai_api_key, 
            temperature=0.2
        )
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI components: {e}")


async def get_agronomy_advice(query: str, db: AsyncSession, crop: str | None = None) -> str:
    """
    RAG pipeline for handling agronomy queries.
    1. Embeds the user query.
    2. Performs cosine similarity search against KnowledgeChunks in PostgreSQL.
    3. Prompts GPT-4 with context to generate a Kannada response.
    """
    if _embeddings is None or _llm is None:
        return (
            "ಕ್ಷಮಿಸಿ, ಕೃಷಿ ಸಲಹೆ ಸೇವೆ ಸದ್ಯಕ್ಕೆ ಲಭ್ಯವಿಲ್ಲ "
            "(OpenAI API key missing). — KisanMitra 🌾"
        )

    try:
        # 1. Embed query
        query_embedding = await _embeddings.aembed_query(query)

        # 2. Search Postgres using pgvector (HNSW index)
        stmt = select(KnowledgeChunk.content)
        
        # Metadata filtering if crop is specified
        if crop:
            # We filter for 'All' or the specific crop
            stmt = stmt.where(KnowledgeChunk.crop.in_([crop, "All", "General"]))
            
        stmt = stmt.order_by(KnowledgeChunk.embedding.cosine_distance(query_embedding)).limit(3)
        
        result = await db.execute(stmt)
        chunks = result.scalars().all()
        
        if not chunks:
            context = "No specific local context found. Provide general best practices for Karnataka."
        else:
            context = "\n\n".join(chunks)

        # 3. Generate response via GPT-4
        prompt = ChatPromptTemplate.from_messages([
            ("system", 
             "You are an expert agronomist for KisanMitra helping farmers in Karnataka. "
             "Reply strictly in concise Kannada. Do not invent facts. "
             "Use the provided context to answer the user's query."
            ),
            ("user", 
             "Context:\n{context}\n\nCrop: {crop}\nQuestion: {query}\n\n"
             "Answer concisely in Kannada:"
            )
        ])
        
        chain = prompt | _llm | StrOutputParser()
        answer = await chain.ainvoke({
            "context": context, 
            "query": query, 
            "crop": crop or "Unknown"
        })
        
        return f"{answer}\n\n— KisanMitra 🌾"

    except Exception as exc:
        logger.error(f"RAG Error: {exc}")
        return "ಸಲಹೆ ಪಡೆಯುವಾಗ ತೊಂದರೆಯಾಗಿದೆ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ. — KisanMitra 🌾"
