# RAG (Retrieval-Augmented Generation) Architecture

BubbleBrain uses the RAG pattern to provide accurate answers based on the store's own data.

## How does it work?

1. **Ingestion**:
   - Product data is loaded into the system.
   - The text is converted into vectors using OpenAI Embeddings.
   - Vectors are stored in a vector database (Pinecone).

2. **Retrieval**:
   - When a user asks a question, their query is also converted into a vector.
   - Pinecone finds the most relevant pieces of information (nearest vectors).

3. **Generation**:
   - The retrieved context is appended to the user's initial query.
   - The augmented prompt is sent to the language model (LLM), which generates an accurate response based on the provided facts.

This approach ensures no "hallucinations" from the AI, as it always relies on strict factual context.
