import axios from 'axios';

const API_BASE = ""; // Handled by Vite proxy

export const fetchRAGHealth = async () => {
  try {
    const response = await axios.get(`${API_BASE}/analytics/rag-health`, {
      timeout: 5000 // 5s timeout
    });
    return response.data;
  } catch (error) {
    console.error("Failed to fetch RAG health:", error);
    throw error;
  }
};
