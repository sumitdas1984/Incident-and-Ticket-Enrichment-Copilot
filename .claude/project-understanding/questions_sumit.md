1. Explain the postman collection provided for Alarm API
2. How the Streamlit FE is communicating with FastAPI BE?
3. What Are the BE API been developed? How to get that BE API list or details? Is Swagger documentation available for that?
4. What are the services been developed for this microservices based system? Explain those services and their role in this system from the top level?
5. LLM is used exactly in which service? For what purpose?
6. Is some LLM openai/claude currently getting used? Because I can see we are getting response instantly from the co-pilot. It seems like MockLLM is getting used in current run. Actual LLM calls are getting bypassed. Please verify and explain to me. 
7. In the RAG are you really using a vector db? In the RAG docuemnetation I got:

The RAG pipeline in three steps:

Ingest (one-time, offline): Read each markdown document → split into chunks → embed each chunk (turn text into a numeric vector) → save the vectors to an index file. Output: var/index/v1.pkl.
Retrieve (per-request, online): Take the operator's question → embed it the same way → find the top-N chunks with the closest vectors → run those chunks through a prompt-injection filter → return the survivors as citations.
Generate (per-request, online): Stick the question, the retrieved chunks, and the alarm-system data into a prompt → ask the LLM to write the answer in the required shape.

which vector DB, which embedding model, what chunking approach are used? Why those choices?
I can see pkl file used for indexing... whay .pkl file?
8. What prompt injection filter is use? why?
9. How the citations are generated?