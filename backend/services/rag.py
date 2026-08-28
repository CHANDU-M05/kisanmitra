"""
backend/services/rag.py — Vertical Slice 4 (RAG Pipeline)

Generative AI layer for the KisanMitra WhatsApp Bot and Farmer Advisory Console.
Retrieves context from PostgreSQL via pgvector and generates
high-fidelity agronomy advice using Gemini 1.5 Pro.
"""
from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from backend.core.config import settings
from backend.core.models import KnowledgeChunk

logger = logging.getLogger("kisanmitra.rag")

# Initialize models only if API key is present
_embeddings = None
_llm = None

if settings.gemini_api_key and settings.gemini_api_key.get_secret_value() != "fill_this_later" and settings.gemini_api_key.get_secret_value() != "":
    try:
        _embeddings = GoogleGenerativeAIEmbeddings(
            model="models/text-embedding-004",
            google_api_key=settings.gemini_api_key.get_secret_value(),
        )
        
        # Primary: Gemini 2.5 Flash for fast, robust generative advisory.
        try:
            _llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash", 
                google_api_key=settings.gemini_api_key.get_secret_value(), 
                temperature=0.1
            )
            logger.info("RAG: Initialized Gemini 2.5 Flash LLM.")
        except Exception as pro_ex:
            logger.warning(f"RAG: Failed to load gemini-2.5-flash: {pro_ex}")
            _llm = None
    except Exception as e:
        logger.error(f"Failed to initialize Gemini components: {e}")


def is_kannada(text: str) -> bool:
    """Detect if the text contains any Kannada Unicode characters."""
    return any('\u0c80' <= char <= '\u0cff' for char in text)


def get_offline_fallback(query: str, crop: str | None) -> tuple[str, str]:
    """
    Returns (fallback_msg, suffix) depending on query language and keywords.
    Matches queries dynamically to simulate a high-quality agronomy assistant.
    """
    is_kn = is_kannada(query)
    q = query.lower()
    c = (crop or "").lower()
    
    if is_kn:
        suffix = "🌾 (ಆಫ್‌ಲೈನ್ ಸಲಹೆ)"
        # Default fallback messages per crop in Kannada
        tomato_fallback = (
            "📋 **ಟೊಮೆಟೊ ಬೆಳೆ ರೋಗ ನಿರ್ವಹಣೆ (Tomato Care)**:\n"
            "• **ಸಮಸ್ಯೆ**: ತೇವಾಂಶ ಹೆಚ್ಚಾದಾಗ ಹೂ ಮತ್ತು ಕಾಯಿ ಕೊಳೆಯುವ ರೋಗ (Fruit Rot/Late Blight).\n"
            "• **ಕ್ರಮಗಳು**: ಜಮೀನಿನಲ್ಲಿ ನೀರು ನಿಲ್ಲದಂತೆ ನೋಡಿಕೊಳ್ಳಿ. ಪೀಡಿತ ಭಾಗಗಳನ್ನು ತಕ್ಷಣ ತೆಗೆದುಹಾಕಿ.\n"
            "• **ಔಷಧಿ**: ಶೇ 1% ಬೋರ್ಡೋ ಮಿಶ್ರಣ ಅಥವಾ ಮ್ಯಾಂಕೋಜೆಬ್ (2g/L) ಸಿಂಪಡಿಸಿ."
        )
        maize_fallback = (
            "📋 **ಮೆಕ್ಕೆಜೋಳ ಪೋಷಕಾಂಶ ಮತ್ತು ಕೀಟ ನಿರ್ವಹಣೆ (Maize Care)**:\n"
            "• **ಗೊಬ್ಬರ**: ಸಾರಜನಕ ಮತ್ತು ಯೂರಿಯಾವನ್ನು ಸರಿಯಾದ ಸಮಯಕ್ಕೆ (ಬಿತ್ತನೆ ನಂತರ 30 ಮತ್ತು 60 ದಿನಗಳಲ್ಲಿ) ನೀಡಿ.\n"
            "• **ಕೀಟ ಬಾಧೆ**: ಕತ್ತರಿಸುಳ್ಳು/ಸೈನಿಕ ಹುಳು (Fall Armyworm) ನಿಯಂತ್ರಣಕ್ಕೆ ಎಲೆ ಸುಳಿಯಲ್ಲಿ ನೀರು ನಿಲ್ಲಿಸಿ.\n"
            "• **ಔಷಧಿ**: ಇಮಾಮೆಕ್ಟಿನ್ ಬೆಂಜೋಯೇಟ್ (0.4g/L) ಅಥವಾ ಸ್ಪಿನೋಸಾದ್ ಸಿಂಪಡಿಸಿ."
        )
        onion_fallback = (
            "📋 **ಈರುಳ್ಳಿ ಕೊಳೆರೋಗ ನಿರ್ವಹಣೆ (Onion Bulb Rot)**:\n"
            "• **ಸಮಸ್ಯೆ**: ಈರುಳ್ಳಿ ಕುತ್ತಿಗೆ ಕೊಳೆರೋಗ ಮತ್ತು ನೇರಳೆ ಮಚ್ಚೆ ರೋಗ.\n"
            "• **ಕ್ರಮಗಳು**: ಜಮೀನಿನಲ್ಲಿ ಹೆಚ್ಚುವರಿ ನೀರು ಹೋಗಲು ಬಸಿಕಾಲುವೆಗಳನ್ನು ನಿರ್ಮಿಸಿ.\n"
            "• **ಔಷಧಿ**: ಮ್ಯಾಂಕೋಜೆಬ್ ಅಥವಾ ಸಾಫ್ (2g/L) ಸಿಂಪಡಿಸಿ."
        )
        potato_fallback = (
            "📋 **ಆಲೂಗಡ್ಡೆ ಅಂಗಮಾರಿ ರೋಗ ನಿಯಂತ್ರಣ (Potato Blight)**:\n"
            "• **ರೋಗ**: ಲೇಟ್ ಬ್ಲೈಟ್ (ಅಂಗಮಾರಿ ರೋಗ).\n"
            "• **ಕ್ರಮಗಳು**: ಪ್ರಮಾಣೀಕೃತ ಬಿತ್ತನೆ ಆಲೂಗಡ್ಡೆ ಬಳಸಿ. ಬೆಳವಣಿಗೆಯ ಹಂತದಲ್ಲಿ ಸಾಲುಗಳಲ್ಲಿ ಮಣ್ಣು ಏರಿಸಿರಿ.\n"
            "• **ಔಷಧಿ**: ಮೆಟಲಾಕ್ಸಿಲ್ + ಮ್ಯಾಂಕೋಜೆಬ್ (2.5g/L) ಮುನ್ನೆಚ್ಚರಿಕೆಯಾಗಿ ಸಿಂಪಡಿಸಿ."
        )
        ragi_fallback = (
            "📋 **ರಾಗಿ ಬೆಳೆ ಇಳುವರಿ ಮತ್ತು ರೋಗ ನಿರ್ವಹಣೆ (Ragi Care)**:\n"
            "• **ರೋಗ**: ಕುತ್ತಿಗೆ ಕೊಳೆ ಮತ್ತು ಎಲೆ ಕರಕು ರೋಗ (Blast Disease).\n"
            "• **ಕ್ರಮಗಳು**: ಹೆಚ್ಚಿನ ಸಾರಜನಕ ಬಳಕೆ ತಪ್ಪಿಸಿ. ಜೈವಿಕ ಗೊಬ್ಬರ (ಅಜೋಸ್ಪಿರಿಲಮ್) ಬಳಸಿ.\n"
            "• **ಔಷಧಿ**: ಟ್ರೈಸೈಕ್ಲಾಜೋಲ್ (0.6g/L) ಸಿಂಪಡಿಸಿ."
        )
        brinjal_fallback = (
            "📋 **ಬದನೆ ಬೆಳೆ ಕೀಟ ನಿರ್ವಹಣೆ (Brinjal Care)**:\n"
            "• **ರೋಗ**: ಬದನೆಕಾಯಿಯ ಕಾಂಡ ಮತ್ತು ಕಾಯಿ ಕೊರಕ ಕೀಟ (Shoot & Fruit Borer).\n"
            "• **ಕ್ರಮಗಳು**: ಬಾಧಿತ ಚಿಗುರು ಮತ್ತು ಕಾಯಿಗಳನ್ನು ತೆಗೆದು ನಾಶಪಡಿಸಿ.\n"
            "• **ಔಷಧಿ**: ಪ್ರೊಫೆನೋಫಾಸ್ (2ml/L) ಅಥವಾ ಕ್ಲೋರಂಟ್ರಾನಿಲಿಪ್ರೋಲ್ (0.3ml/L) ಸಿಂಪಡಿಸಿ."
        )
        marigold_fallback = (
            "📋 **ಚೆಂಡುಹೂ ಬೆಳೆ ರೋಗ ನಿರ್ವಹಣೆ (Marigold Care)**:\n"
            "• **ರೋಗ**: ಎಲೆ ಚುಕ್ಕೆ ಮತ್ತು ಮೊಗ್ಗು ಕೊಳೆ ರೋಗ (Leaf Spot & Bud Rot).\n"
            "• **ಕ್ರಮಗಳು**: ನರ್ಸರಿಯಲ್ಲಿ ನೀರು ಬಸಿದು ಹೋಗಲು ಸೂಕ್ತ ವ್ಯವಸ್ಥೆ ಮಾಡಿ.\n"
            "• **ಔಷಧಿ**: ಕಾರ್ಬನ್ಡಾಜಿಮ್ (2g/L) ಅಥವಾ ಮ್ಯಾಂಕೋಜೆಬ್ ಸಿಂಪಡಿಸಿ."
        )
        default_fallback = "ಬೆಳೆಗೆ ಸೂಕ್ತ ಕಾಲದಲ್ಲಿ ನೀರು ಮತ್ತು ಗೊಬ್ಬರ ಒದಗಿಸಿ. ಕೀಟ ಬಾಧೆ ಕಂಡುಬಂದಲ್ಲಿ ಜೈವಿಕ ಕೀಟನಾಶಕ ಬಳಸಿ."

        # Keyword mapping for Tomato
        if c == "tomato":
            if any(kw in q for kw in ["ಗೊಬ್ಬರ", "ಪ್ರಮಾಣ", "fertilizer", "dose"]):
                return (
                    "📋 **ಟೊಮೆಟೊ ಗೊಬ್ಬರ ನಿರ್ವಹಣೆ (Tomato Fertilizer Dose)**:\n"
                    "• **ವಿಷಯ**: ಸಮತೋಲಿತ ಪೋಷಕಾಂಶಗಳ ಕೊಡುಗೆ (NPK).\n"
                    "• **ಕ್ರಮಗಳು**: ಪ್ರತಿ ಎಕರೆಗೆ 60 ಕೆಜಿ ಸಾರಜನಕ, 50 ಕೆಜಿ ರಂಜಕ ಮತ್ತು 50 ಕೆಜಿ ಪೊಟ್ಯಾಶ್ ನೀಡಬೇಕು.\n"
                    "• **ಟಿಪ್**: ಗೊಬ್ಬರ ನೀಡಿದ ತಕ್ಷಣ ಹಗುರವಾಗಿ ನೀರು ಹಾಯಿಸಿ.", suffix
                )
            if any(kw in q for kw in ["ಅಂಗಮಾರಿ", "late blight", "blight"]):
                return (
                    "📋 **ಟೊಮೆಟೊ ಅಂಗಮಾರಿ ರೋಗ ನಿಯಂತ್ರಣ (Tomato Late Blight Control)**:\n"
                    "• **ವಿಷಯ**: ಹವಾಮಾನದಲ್ಲಿ ತೇವಾಂಶ ಹೆಚ್ಚಾದಾಗ ಬರುವ ಶಿಲೀಂಧ್ರ ರೋಗ.\n"
                    "• **ಕ್ರಮಗಳು**: ರೋಗಪೀಡಿತ ಎಲೆಗಳನ್ನು ತಕ್ಷಣ ಕತ್ತರಿಸಿ ನಾಶಮಾಡಿ.\n"
                    "• **ಔಷಧಿ**: ಸಿಮೋಕ್ಸಾನಿಲ್ + ಮ್ಯಾಂಕೋಜೆಬ್ (2g/L) ಅಥವಾ ಮೆಟಲಾಕ್ಸಿಲ್ ಸಿಂಪಡಿಸಿ.", suffix
                )
            return tomato_fallback, suffix

        # Keyword mapping for Maize
        elif c == "maize":
            if any(kw in q for kw in ["ಸೈನಿಕ ಹುಳು", "armyworm"]):
                return maize_fallback, suffix
            if any(kw in q for kw in ["ಯೂರಿಯಾ", "urea"]):
                return (
                    "📋 **ಮೆಕ್ಕೆಜೋಳಕ್ಕೆ ಯೂರಿಯಾ ಗೊಬ್ಬರ ನೀಡುವಿಕೆ (Maize Urea Application)**:\n"
                    "• **ವಿಷಯ**: ಯೂರಿಯಾವನ್ನು ಬೆಳವಣಿಗೆಯ ನಿರ್ಣಾಯಕ ಹಂತಗಳಲ್ಲಿ ಹಂಚಿ ನೀಡಬೇಕು.\n"
                    "• **ಕ್ರಮಗಳು**: ಬಿತ್ತನೆಯ 30ನೇ ದಿನಕ್ಕೆ ಮತ್ತು 60ನೇ ದಿನಕ್ಕೆ ಹೂ ಬಿಡುವ ಮುನ್ನ ಪ್ರತಿ ಎಕರೆಗೆ 35 ಕೆಜಿ ಯೂರಿಯಾ ಕೊಡಿ.\n"
                    "• **ಎಚ್ಚರಿಕೆ**: ಒಣ ಮಣ್ಣಿನಲ್ಲಿ ಯೂರಿಯಾ ಹಾಕಬೇಡಿ; ಮಣ್ಣಿನಲ್ಲಿ ತೇವಾಂಶ ಇರಲಿ.", suffix
                )
            if any(kw in q for kw in ["ನೀರಾವರಿ", "ನೀರು", "irrigation"]):
                return (
                    "📋 **ಮೆಕ್ಕೆಜೋಳದ ನೀರಿನ ನಿರ್ವಹಣೆ (Maize Irrigation Schedule)**:\n"
                    "• **ವಿಷಯ**: ಮೆಕ್ಕೆಜೋಳಕ್ಕೆ ಮೊಣಕಾಲು ಎತ್ತರ ಹಂತ ಮತ್ತು ತೆನೆ ಬರುವ ಹಂತ ಅತ್ಯಂತ ಸೂಕ್ಷ್ಮ ಹಂತಗಳು.\n"
                    "• **ಕ್ರಮಗಳು**: ತೇವಾಂಶ ಕೊರತೆಯಾಗದಂತೆ 10-12 ದಿನಗಳಿಗೊಮ್ಮೆ ನೀರು ಹಾಯಿಸಿ.\n"
                    "• **ಟಿಪ್**: ತೆನೆ ಕಟ್ಟುವ ಸಮಯದಲ್ಲಿ ನೀರು ನಿಲ್ಲದಂತೆ ನೋಡಿಕೊಳ್ಳಿ.", suffix
                )
            return maize_fallback, suffix

        # Keyword mapping for Onion
        elif c == "onion":
            if any(kw in q for kw in ["ಕೊಳೆರೋಗ", "rot", "ನೇರಳೆ"]):
                return onion_fallback, suffix
            if any(kw in q for kw in ["ದಪ್ಪಗಾಗಲು", "size", "bulb"]):
                return (
                    "📋 **ಈರುಳ್ಳಿ ಕಾಯಿ ದಪ್ಪಗಾಗುವಿಕೆ ವಿಧಾನ (Onion Bulb Size Booster)**:\n"
                    "• **ವಿಷಯ**: ಪೋಷಕಾಂಶಗಳ ಕೊರತೆ ಮತ್ತು ಅಸಮತೋಲಿತ ನೀರಾವರಿಯಿಂದ ಈರುಳ್ಳಿ ಗಾತ್ರ ಚಿಕ್ಕದಾಗುತ್ತದೆ.\n"
                    "• **ಕ್ರಮಗಳು**: ಬಿತ್ತನೆ ಮಾಡಿದ 45 ಮತ್ತು 60 ದಿನಗಳಲ್ಲಿ ಮಲ್ಟಿ-ಕೆ (13:0:45) ಗೊಬ್ಬರವನ್ನು 5g/L ನೀರಿನಲ್ಲಿ ಬೆರೆಸಿ ಸಿಂಪಡಿಸಿ.\n"
                    "• **ಟಿಪ್**: ಸಾಲುಗಳ ನಡುವೆ ಮಣ್ಣು ಸಡಿಲಗೊಳಿಸಿ and ಲಘುವಾಗಿ ನೀರು ನೀಡಿ.", suffix
                )
            if any(kw in q for kw in ["ಬೀಜ", "seed"]):
                return (
                    "📋 **ಈರುಳ್ಳಿ ಬಿತ್ತನೆ ಬೀಜದ ಪ್ರಮಾಣ (Onion Seed Rate Guidelines)**:\n"
                    "• **ವಿಷಯ**: ಒಂದು ಎಕರೆ ಪ್ರದೇಶಕ್ಕೆ ಸೂಕ್ತ ಸಸ್ಯ ಸಾಂದ್ರತೆ ಕಾಯ್ದುಕೊಳ್ಳುವುದು ಮುಖ್ಯ.\n"
                    "• **ಕ್ರಮಗಳು**: ಒಂದು ಎಕರೆ ಸಸ್ಯ ನಾಟಿಗಾಗಿ 3 ರಿಂದ 4 ಕೆಜಿ ಬಿತ್ತನೆ ಬೀಜದ ಅವಶ್ಯಕತೆ ಇರುತ್ತದೆ.\n"
                    "• **ಎಚ್ಚರಿಕೆ**: ನರ್ಸರಿಯಲ್ಲಿ 6-8 ವಾರಗಳ ಕಾಲ ಸಸಿ ಬೆಳೆಸಿದ ನಂತರ ಜಮೀನಿಗೆ ನಾಟಿ ಮಾಡಿ.", suffix
                )
            return onion_fallback, suffix

        # Keyword mapping for Ragi
        elif c == "ragi":
            if any(kw in q for kw in ["ಕುತ್ತಿಗೆ ಕೊಳೆ", "blast"]):
                return ragi_fallback, suffix
            if any(kw in q for kw in ["ಕಟಾವು", "harvest"]):
                return (
                    "📋 **ರಾಗಿ ಬೆಳೆ ಕಟಾವಿನ ಸಮಯ (Ragi Harvesting Guidelines)**:\n"
                    "• **ವಿಷಯ**: ಕಾಳುಗಳು ಗಟ್ಟಿಯಾಗಿ ಹೊಂಬಣ್ಣಕ್ಕೆ ತಿರುಗಿದಾಗ ಕಟಾವು ಮಾಡಬೇಕು.\n"
                    "• **ಕ್ರಮಗಳು**: ತೆನೆಗಳನ್ನು ಕತ್ತರಿಸಿ ಬಿಸಿಲಿನಲ್ಲಿ ಒಣಗಿಸಿ, ನಂತರ ಒಕ್ಕಣೆ ಮಾಡಿ ಸಂಗ್ರಹಿಸಿ.\n"
                    "• **ಟಿಪ್**: ಕೊಯ್ಲಿಗೆ 10 ದಿನ ಮುಂಚಿತವಾಗಿ ನೀರು ಹಾಯಿಸುವುದನ್ನು ನಿಲ್ಲಿಸಿ.", suffix
                )
            if any(kw in q for kw in ["ಇಳುವರಿ", "yield"]):
                return (
                    "📋 **ರಾಗಿ ಇಳುವರಿ ಹೆಚ್ಚಿಸುವ ಕ್ರಮಗಳು (Ragi Yield Improvement)**:\n"
                    "• **ವಿಷಯ**: ಸುಧಾರಿತ ತಳಿಗಳ ಬಳಕೆ ಮತ್ತು ರಂಜಕದ ಸಕಾಲಿಕ ಪೂರೈಕೆ.\n"
                    "• **ಕ್ರಮಗಳು**: ಪ್ರತಿ ಎಕರೆಗೆ ಜಿಪ್ಸಮ್ (100 ಕೆಜಿ) ಬಳಸಿ ಮತ್ತು ಲಘು ಪೋಷಕಾಂಶಗಳನ್ನು ಪೂರೈಸಿ.\n"
                    "• **ಟಿಪ್**: ಸವರಿದ ಸಸ್ಯಗಳ ನಡುವೆ 10 ಸೆಂ.ಮೀ ಅಂತರವನ್ನು ಕಾಯ್ದುಕೊಳ್ಳಿ.", suffix
                )
            return ragi_fallback, suffix

        # Keyword mapping for Potato
        elif c == "potato":
            if any(kw in q for kw in ["ಅಂಗಮಾರಿ", "late blight", "blight"]):
                return potato_fallback, suffix
            if any(kw in q for kw in ["ಅಂತರವಿರಬೇಕು", "spacing"]):
                return (
                    "📋 **ಆಲೂಗಡ್ಡೆ ನಾಟಿಯ ಅಂತರ (Potato Tubers Spacing)**:\n"
                    "• **ವಿಷಯ**: ಸೂಕ್ತ ಸೂರ್ಯನ ಬೆಳಕು ಮತ್ತು ಗಾಳಿ ಸಂಚಾರಕ್ಕೆ ಅಂತರ ಅಗತ್ಯ.\n"
                    "• **ಕ್ರಮಗಳು**: ಸಾಲುಗಳ ನಡುವೆ 60 ಸೆಂ.ಮೀ ಮತ್ತು ಗಡ್ಡೆಗಳ ನಡುವೆ 20 ಸೆಂ.ಮೀ ಅಂತರವನ್ನು ಕಾಯ್ದುಕೊಳ್ಳಿ.\n"
                    "• **ಟಿಪ್**: ಗಡ್ಡೆಗಳನ್ನು 5-7 ಸೆಂ.ಮೀ ಆಳದಲ್ಲಿ ಮಣ್ಣಿನಲ್ಲಿ ನಾಟಿ ಮಾಡಿ.", suffix
                )
            if any(kw in q for kw in ["ನೀರಾವರಿ", "water", "ನೀರು"]):
                return (
                    "📋 **ಆಲೂಗಡ್ಡೆ ಕೊನೆಯ ನೀರಾವರಿ (Potato Final Watering)**:\n"
                    "• **ವಿಷಯ**: ಕೊನೆಯ ಹಂತದ ನೀರಿನ ನಿರ್ವಹಣೆ ಗಡ್ಡೆ ಕೊಳೆಯುವುದನ್ನು ತಡೆಯುತ್ತದೆ.\n"
                    "• **ಕ್ರಮಗಳು**: ಕಟಾವು ಮಾಡಲು 10 ರಿಂದ 12 ದಿನ ಮುಂಚಿತವಾಗಿ ಸಂಪೂರ್ಣವಾಗಿ ನೀರು ನಿಲ್ಲಿಸಿ.\n"
                    "• **ಎಚ್ಚರಿಕೆ**: ಮಣ್ಣಿನಲ್ಲಿ ಅತಿಯಾದ ತೇವಾಂಶವಿದ್ದರೆ ಗಡ್ಡೆಗಳ ಸಂಗ್ರಹಣಾ ಸಾಮರ್ಥ್ಯ ಕಡಿಮೆಯಾಗುತ್ತದೆ.", suffix
                )
            return potato_fallback, suffix

        # Keyword mapping for Brinjal
        elif c == "brinjal":
            if any(kw in q for kw in ["ಕೊರಕ", "borer", "ಕಾಂಡ"]):
                return brinjal_fallback, suffix
            if any(kw in q for kw in ["ಗೊಬ್ಬರ", "ರಸಗೊಬ್ಬರ", "fertilizer"]):
                return (
                    "📋 **ಬದನೆ ರಸಗೊಬ್ಬರ ನಿರ್ವಹಣೆ (Brinjal Fertilizer Dose)**:\n"
                    "• **ವಿಷಯ**: ಬದನೆಗೆ ಹೆಚ್ಚಿನ ಪ್ರಮಾಣದ ಸಾರಜನಕ ಮತ್ತು ಪೊಟ್ಯಾಶ್ ಬೇಕಾಗುತ್ತದೆ.\n"
                    "• **ಕ್ರಮಗಳು**: ಪ್ರತಿ ಎಕರೆಗೆ 60 ಕೆಜಿ ಸಾರಜನಕ, 30 ಕೆಜಿ ರಂಜಕ ಮತ್ತು 30 ಕೆಜಿ ಪೊಟ್ಯಾಶ್ ಒದಗಿಸಿ.\n"
                    "• **ಟಿಪ್**: ನಾಟಿ ಮಾಡಿದ 4-5 ವಾರಗಳಲ್ಲಿ ಎರಡನೇ ಕಂತಿನ ಗೊಬ್ಬರ ನೀಡಿ.", suffix
                )
            if any(kw in q for kw in ["ನುಸಿ", "ಸಣ್ಣ ಎಲೆ", "little leaf"]):
                return (
                    "📋 **ಬದನೆ ಸಣ್ಣ ಎಲೆ ರೋಗ ನಿಯಂತ್ರಣ (Brinjal Little Leaf Disease)**:\n"
                    "• **ವಿಷಯ**: ಮೈಕೋಪ್ಲಾಸ್ಮಾ ಎಂಬ ಸೂಕ್ಷ್ಮಾಣುಜೀವಿಯಿಂದ ಬರುವ ಹರಡುವ ರೋಗ.\n"
                    "• **ಕ್ರಮಗಳು**: ಪೀಡಿತ ಗಿಡಗಳನ್ನು ತಕ್ಷಣ ಕಿತ್ತು ಸುಟ್ಟು ಹಾಕಿ.\n"
                    "• **ಔಷಧಿ**: ರೋಗ ಹರಡುವ ಜಿಗಿಹುಳು ನಿಯಂತ್ರಿಸಲು ಡೈಮಿಥೋಯೇಟ್ (1.7ml/L) ಸಿಂಪಡಿಸಿ.", suffix
                )
            return brinjal_fallback, suffix

        # Keyword mapping for Marigold
        elif c == "marigold":
            if any(kw in q for kw in ["ಚುಕ್ಕೆ", "ಕೊಳೆ", "spot", "rot"]):
                return marigold_fallback, suffix
            if any(kw in q for kw in ["ಅಂತರವಿರಬೇಕು", "spacing", "ಅಂತರ"]):
                return (
                    "📋 **ಚೆಂಡುಹೂವಿನ ಸಾಲುಗಳ ಅಂತರ (Marigold Plant Spacing)**:\n"
                    "• **ವಿಷಯ**: ಚೆಂಡುಹೂವಿನಲ್ಲಿ ಗಿಡದಿಂದ ಗಿಡಕ್ಕೆ ಗಾಳಿ ಸಂಚಾರ ಚೆನ್ನಾಗಿರಲು ಅಂತರ ಮುಖ್ಯ.\n"
                    "• **ಕ್ರಮಗಳು**: ಸಾಲುಗಳ ನಡುವೆ 45 ಸೆಂ.ಮೀ ಮತ್ತು ಸಸಿಗಳ ನಡುವೆ 30 ಸೆಂ.ಮೀ ಅಂತರ ಕಾಯ್ದುಕೊಳ್ಳಿ.\n"
                    "• **ಟಿಪ್**: ಸಂಜೆ ವೇಳೆಯಲ್ಲಿ ತೇವಾಂಶ ಇರದಂತೆ ನಾಟಿ ಮಾಡಿ.", suffix
                )
            if any(kw in q for kw in ["ಇಳುವರಿ", "ಮೊಗ್ಗು", "yield", "nutrients"]):
                return (
                    "📋 **ಚೆಂಡುಹೂ ಇಳುವರಿ ಹೆಚ್ಚಿಸುವಿಕೆ (Marigold Yield Booster)**:\n"
                    "• **ವಿಷಯ**: ಹೆಚ್ಚಿನ ಮೊಗ್ಗು ಮತ್ತು ಹೂವಿನ ಆಕಾರಕ್ಕೆ ಪೋಷಕಾಂಶಗಳ ಕೊಡುಗೆ.\n"
                    "• **ಕ್ರಮಗಳು**: ನಾಟಿ ಮಾಡಿದ 30 ಮತ್ತು 45 ದಿನಗಳಲ್ಲಿ ಪೊಟ್ಯಾಶಿಯಂ ನೈಟ್ರೇಟ್ (5g/L) ಸಿಂಪಡಿಸಿ.\n"
                    "• **ಟಿಪ್**: ಹೆಚ್ಚಿನ ಕವಲುಗಳು ಬರಲು ನಾಟಿ ಮಾಡಿದ 25ನೇ ದಿನಕ್ಕೆ ತುದಿಯನ್ನು ಕತ್ತರಿಸಿ (Pinching).", suffix
                )
            return marigold_fallback, suffix

        return default_fallback, suffix

    else:
        suffix = "🌾 (Offline Advice)"
        # Default fallback messages per crop in English
        tomato_fallback = (
            "📋 **Tomato Crop Disease Management**:\n"
            "• **Issue**: Fruit rot and Late Blight due to high humidity/heavy rains.\n"
            "• **Actions**: Ensure proper soil drainage and remove infected plants/leaves immediately.\n"
            "• **Control**: Spray 1% Bordeaux mixture or Mancozeb (2g/L) as a preventive measure."
        )
        maize_fallback = (
            "📋 **Maize Nutrient & Pest Management**:\n"
            "• **Nutrients**: Apply Nitrogen and Urea in split doses (at 30 and 60 days post-sowing).\n"
            "• **Pest**: Fall Armyworm control. Pour water or standard biosprays directly into leaf whorls.\n"
            "• **Control**: Spray Emamectin Benzoate (0.4g/L) or Spinosad."
        )
        onion_fallback = (
            "📋 **Onion Bulb Rot & Purple Blotch Management**:\n"
            "• **Issue**: Purple blotch and neck/bulb rot due to damp conditions.\n"
            "• **Actions**: Build drainage channels to prevent water logging in fields.\n"
            "• **Control**: Spray Mancozeb or Saaf (2g/L) weekly."
        )
        potato_fallback = (
            "📋 **Potato Late Blight Disease Management**:\n"
            "• **Issue**: Late Blight appearing as water-soaked spots on leaves.\n"
            "• **Actions**: Use certified disease-free seed tubers and practice earthing-up.\n"
            "• **Control**: Spray Metalaxyl + Mancozeb (2.5g/L) before blight spreads."
        )
        ragi_fallback = (
            "📋 **Ragi Blast Disease & Yield Improvement**:\n"
            "• **Issue**: Finger/neck blast disease causing yield loss.\n"
            "• **Actions**: Avoid excessive nitrogen fertilizers. Apply biofertilizers like Azospirillum.\n"
            "• **Control**: Spray Tricyclazole (0.6g/L) at the beginning of disease manifestation."
        )
        brinjal_fallback = (
            "📋 **Brinjal Crop Pest Management**:\n"
            "• **Issue**: Shoot and fruit borer causing wilting of shoots and boreholes in fruits.\n"
            "• **Actions**: Remove and destroy infested shoots and fruits immediately.\n"
            "• **Control**: Spray Profenofos (2ml/L) or Chlorantraniliprole (0.3ml/L) weekly."
        )
        marigold_fallback = (
            "📋 **Marigold Crop Disease Management**:\n"
            "• **Issue**: Alternaria leaf spot and bud rot causing dark spots and decaying buds.\n"
            "• **Actions**: Improve drainage and remove decayed flowers to reduce inoculum.\n"
            "• **Control**: Spray Carbendazim (2g/L) or Mancozeb at first sight of spots."
        )
        default_fallback = "Provide timely irrigation and balanced fertilizer application. Use biopesticides if pests are detected."

        # Keyword mapping for Tomato
        if c == "tomato":
            if any(kw in q for kw in ["fertilizer", "dose", "nutrient"]):
                return (
                    "📋 **Tomato Fertilizer & Nutrition Guide**:\n"
                    "• **Overview**: Balanced NPK ratio ensures healthy vine and maximum fruit set.\n"
                    "• **Actionable Steps**: Apply 60kg Nitrogen, 50kg Phosphorus, and 50kg Potassium per acre.\n"
                    "• **Cautions**: Apply secondary nutrients (Calcium, Boron) during flowering to prevent blossom end rot."
                ), suffix
            if any(kw in q for kw in ["late blight", "blight"]):
                return (
                    "📋 **Tomato Late Blight Control**:\n"
                    "• **Overview**: High-humidity fungal disease that can destroy foliage in 48 hours.\n"
                    "• **Actionable Steps**: Prune lower leaves to improve airflow. Destroy infected materials.\n"
                    "• **Cautions**: Apply Metalaxyl-M or Cymoxanil + Mancozeb (2g/L) preventative sprays."
                ), suffix
            return tomato_fallback, suffix

        # Keyword mapping for Maize
        elif c == "maize":
            if any(kw in q for kw in ["armyworm", "pest"]):
                return maize_fallback, suffix
            if any(kw in q for kw in ["urea", "fertilizer"]):
                return (
                    "📋 **Maize Urea Application Schedule**:\n"
                    "• **Overview**: Maize is a heavy feeder of Nitrogen. Splitting urea is highly recommended.\n"
                    "• **Actionable Steps**: Top dress 35kg urea per acre at knee-height stage (30 days) and another 35kg before tasseling (60 days).\n"
                    "• **Cautions**: Never apply urea on completely dry soils; schedule after a light rainfall/irrigation."
                ), suffix
            if any(kw in q for kw in ["irrigation", "water"]):
                return (
                    "📋 **Maize Water Management Protocol**:\n"
                    "• **Overview**: Critical watering stages are tasseling, silking, and grain filling.\n"
                    "• **Actionable Steps**: Maintain soil moisture by watering every 10–12 days depending on heat index.\n"
                    "• **Cautions**: Water logging must be strictly avoided during early germination."
                ), suffix
            return maize_fallback, suffix

        # Keyword mapping for Onion
        elif c == "onion":
            if any(kw in q for kw in ["rot", "blotch"]):
                return onion_fallback, suffix
            if any(kw in q for kw in ["size", "bulb"]):
                return (
                    "📋 **Onion Bulb Expansion Techniques**:\n"
                    "• **Overview**: Balanced potash and mild soil aerations enhance bulb size and quality.\n"
                    "• **Actionable Steps**: Apply Potassium Nitrate (13:0:45) at 5g/L at 45 and 60 days post-transplantation.\n"
                    "• **Cautions**: Reduce nitrogen inputs after bulb initiation to prevent double bulbs."
                ), suffix
            if any(kw in q for kw in ["seed", "rate"]):
                return (
                    "📋 **Onion Seed Rate & Nursery Layout**:\n"
                    "• **Overview**: Seed rate determines spacing density and bulb uniformity.\n"
                    "• **Actionable Steps**: Use 3 to 4 kg of certified seed per acre. Grow seedlings on raised nursery beds for 45 days.\n"
                    "• **Cautions**: Treat seeds with Carbendazim (2g/kg seed) to prevent damping off."
                ), suffix
            return onion_fallback, suffix

        # Keyword mapping for Ragi
        elif c == "ragi":
            if any(kw in q for kw in ["blast", "disease"]):
                return ragi_fallback, suffix
            if any(kw in q for kw in ["harvest", "time"]):
                return (
                    "📋 **Ragi Harvesting Guidelines**:\n"
                    "• **Overview**: Harvesting at physiological maturity minimizes grain shattering.\n"
                    "• **Actionable Steps**: Cut earheads when grains turn brownish-golden. Sundry earheads for 3 days.\n"
                    "• **Cautions**: Stop irrigation 10 days prior to target harvest date to ease drying."
                ), suffix
            if any(kw in q for kw in ["yield", "increase"]):
                return (
                    "📋 **Ragi Yield Maximization Actions**:\n"
                    "• **Overview**: Line sowing, row spacing, and gypsum application improve root zone depth.\n"
                    "• **Actionable Steps**: Maintain 10cm plant spacing. Incorporate 100kg Gypsum per acre at final land preparation.\n"
                    "• **Cautions**: Supplement with Zinc Sulphate (10kg/acre) in zinc-deficient red soils."
                ), suffix
            return ragi_fallback, suffix

        # Keyword mapping for Potato
        elif c == "potato":
            if any(kw in q for kw in ["blight"]):
                return potato_fallback, suffix
            if any(kw in q for kw in ["spacing", "plant"]):
                return (
                    "📋 **Potato Spacing & Planting Method**:\n"
                    "• **Overview**: Correct depth and spacing facilitate optimal tuber growth and prevent greening.\n"
                    "• **Actionable Steps**: Keep a row spacing of 60cm and plant seed tubers at 20cm intervals.\n"
                    "• **Cautions**: Plant tubers at a depth of 5-7 cm and earth-up ridges when plants are 15-20cm tall."
                ), suffix
            if any(kw in q for kw in ["water", "irrigation"]):
                return (
                    "📋 **Potato Tuber Irrigation Termination**:\n"
                    "• **Overview**: Tuber shelf life is heavily dependent on final stage dryness.\n"
                    "• **Actionable Steps**: Completely stop watering 10 to 12 days before harvesting to allow skin curing.\n"
                    "• **Cautions**: Wet harvesting leads to immediate soft rot and storage decomposition."
                ), suffix
            return potato_fallback, suffix

        # Keyword mapping for Brinjal
        elif c == "brinjal":
            if any(kw in q for kw in ["borer", "pest", "fruit borer"]):
                return brinjal_fallback, suffix
            if any(kw in q for kw in ["fertilizer", "dose", "nutrient"]):
                return (
                    "📋 **Brinjal Fertilizer & Nutrition Guide**:\n"
                    "• **Overview**: High nutrient feeder requiring balanced NPK and organic manures.\n"
                    "• **Actionable Steps**: Apply 60kg Nitrogen, 30kg Phosphorus, and 30kg Potassium per acre.\n"
                    "• **Cautions**: Apply top dressing of Nitrogen 4–5 weeks after transplantation."
                ), suffix
            if any(kw in q for kw in ["little leaf", "disease"]):
                return (
                    "📋 **Brinjal Little Leaf Disease Control**:\n"
                    "• **Overview**: Phytoplasmal disease spread by leafhopper vectors.\n"
                    "• **Actionable Steps**: Promptly uproot and destroy infected, bushy plants.\n"
                    "• **Cautions**: Spray Dimethoate (1.7ml/L) to control leafhopper vectors."
                ), suffix
            return brinjal_fallback, suffix

        # Keyword mapping for Marigold
        elif c == "marigold":
            if any(kw in q for kw in ["spot", "rot", "disease"]):
                return marigold_fallback, suffix
            if any(kw in q for kw in ["spacing", "plant"]):
                return (
                    "📋 **Marigold Plant Spacing Protocol**:\n"
                    "• **Overview**: Air circulation is vital to prevent fungal foliar diseases.\n"
                    "• **Actionable Steps**: Maintain 45cm spacing between rows and 30cm spacing between seedlings.\n"
                    "• **Cautions**: Transplant in the evening to avoid stress."
                ), suffix
            if any(kw in q for kw in ["yield", "flower", "increase"]):
                return (
                    "📋 **Marigold Flower Yield Maximization**:\n"
                    "• **Overview**: Pinching and nutrient sprays promote profuse lateral branching.\n"
                    "• **Actionable Steps**: Pinch the terminal shoots 25 days after transplanting. Spray Potassium Nitrate (5g/L) at bud stage.\n"
                    "• **Cautions**: Avoid overhead watering during peak flowering to prevent rot."
                ), suffix
            return marigold_fallback, suffix

        return default_fallback, suffix


async def embed_text(text: str) -> list[float] | None:
    """
    Generate embedding vector for a given text query using the active embeddings model.
    """
    if _embeddings is None:
        return None
    try:
        return await _embeddings.aembed_query(text)
    except Exception as e:
        logger.error(f"Error embedding text: {e}")
        return None


async def get_agronomy_advice(query: str, db: AsyncSession, crop: str | None = None, phone_number: str | None = None) -> str:
    """
    Upgraded RAG pipeline for handling agronomy queries with multi-turn session memory context.
    1. Detects query language (English/Kannada).
    2. Embeds the user query and searches PostgreSQL using pgvector.
    3. Retrieves recent conversation history if phone_number is provided.
    4. Prompts Gemini 1.5 Pro with context and dialogue history.
    """
    is_kn = is_kannada(query)

    if _embeddings is None or _llm is None:
        fallback_msg, suffix = get_offline_fallback(query, crop)
        return f"{fallback_msg}\n\n— KisanMitra {suffix}"

    try:
        # Fetch conversation history for multi-turn context
        history_str = "No prior history."
        if phone_number:
            from backend.services import context_service
            recent_turns = await context_service.get_recent_history(phone_number, db, limit=4)
            if recent_turns:
                history_formatted = [f"{t['role'].upper()}: {t['content']}" for t in recent_turns]
                history_str = "\n".join(history_formatted)

        chunks = []
        if _embeddings is not None:
            try:
                query_embedding = await _embeddings.aembed_query(query)
                stmt = select(KnowledgeChunk.content)
                if crop:
                    stmt = stmt.where(KnowledgeChunk.crop.in_([crop, "All", "General"]))
                stmt = stmt.order_by(KnowledgeChunk.embedding.cosine_distance(query_embedding)).limit(5)
                result = await db.execute(stmt)
                chunks = result.scalars().all()
            except Exception as emb_err:
                logger.warning(f"RAG embedding lookup bypassed: {emb_err}")

        if not chunks:
            context = "No specific local database context found. Supply standard agronomy best practices for Karnataka."
        else:
            context = "\n\n".join(chunks)

        # 3. Generate structured response via LLM
        prompt = ChatPromptTemplate.from_messages([
            ("system", 
             "You are an expert, empathetic agronomist for KisanMitra helping farmers in Karnataka.\n"
             "Your goal is to provide highly precise, practical, and structured agronomic advice.\n\n"
             "Strict Guidelines:\n"
             "1. Respond in the language of the query. If the query is in English, reply in English. "
             "   If the query is in Kannada or a mix of Kannada/English, reply in clean, simple Kannada.\n"
             "2. Format your answer with clean headers and bullet points for scan-readability:\n"
             "   • 📋 **ವಿಷಯದ ಅವಲೋಕನ (Overview)**: Brief diagnosis of the problem/topic.\n"
             "   • 🛠️ **ಪರಿಹಾರ ಕ್ರಮಗಳು (Actionable Steps)**: Step-by-step guidance (fertilizer dosage, land prep, watering).\n"
             "   • ⚠️ **ಮುನ್ನೆಚ್ಚರಿಕೆಗಳು (Cautions & Prevention)**: Prevention tips or chemical safety instructions.\n"
             "3. Rely on the provided Context and Recent Conversation History to understand follow-up questions.\n"
             "4. Do not invent any unverified figures or chemical recommendations."
            ),
            ("user", 
             "Knowledge Base Context:\n{context}\n\nRecent Conversation History:\n{history}\n\nTarget Crop: {crop}\nQuestion: {query}\n\nResponse:"
            )
        ])
        
        chain = prompt | _llm | StrOutputParser()
        answer = await chain.ainvoke({
            "context": context,
            "history": history_str,
            "query": query, 
            "crop": crop or "General"
        })
        
        return f"{answer}\n\n— KisanMitra 🌾"

    except Exception as exc:
        logger.error(f"RAG Error: {exc}")
        fallback_msg, suffix = get_offline_fallback(query, crop)
        return f"{fallback_msg}\n\n— KisanMitra {suffix}"
