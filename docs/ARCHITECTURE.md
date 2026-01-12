# LumiClaim Architecture Diagram

A comprehensive view of the LumiClaim Healthcare Prior Authorization & Claims Platform architecture, showing all tool connections and data flows.

---

## High-Level Architecture Overview

```mermaid
flowchart TB
    subgraph UI["🖥️ Frontend Layer"]
        ST[Streamlit App<br/>app.py]
        P1[Upload Dashboard]
        P2[Explain Bill]
        P3[Simulate Costs]
        P4[Compare Docs]
        P5[Generate Appeal]
        P6[Benefits Profile]
        P7[Ask Lumi]
    end

    subgraph API["⚡ API Layer"]
        FA[FastAPI Server<br/>main.py]
    end

    subgraph CORE["🧠 Core Processing"]
        RAG[RAG Engine<br/>rag.py]
        HYBS[Hybrid Search<br/>hybrid_local.py]
        SESS[Session Manager<br/>session.py]
        EXTR[Document Extractors<br/>extractors.py]
        UEOB[EOB Upload Handler<br/>upload_eob.py]
    end

    subgraph LLM["🤖 LLM Adapters"]
        GROQ[Groq Adapter<br/>Llama 3.2/3.3]
        GEMINI[Gemini Adapter<br/>Gemini 2.0 Flash]
        VERTEX[Vertex Adapter]
    end

    subgraph DATA["💾 Data Layer"]
        FS[File System<br/>data/user_sessions/]
        CLAIMS[Claims JSON]
        PROFILE[Profile JSON]
        RAW[Raw Documents]
        EXTRACTED[Extracted Data]
    end

    subgraph EXTERNAL["☁️ External Services"]
        GROQ_API[Groq Cloud API]
        GEMINI_API[Google Gemini API]
        VERTEX_API[Vertex AI API]
    end

    ST --> P1 & P2 & P3 & P4 & P5 & P6 & P7
    P1 & P2 & P3 & P4 & P5 & P6 & P7 --> FA
    FA --> RAG & SESS & UEOB & EXTR
    RAG --> HYBS
    UEOB --> EXTR
    UEOB --> GROQ
    EXTR --> GROQ
    RAG --> GEMINI & VERTEX
    HYBS --> SESS
    SESS --> FS
    FS --> CLAIMS & PROFILE & RAW & EXTRACTED
    GROQ --> GROQ_API
    GEMINI --> GEMINI_API
    VERTEX --> VERTEX_API
```

---

## Detailed Component Connections & Data Flows

### 1. Document Upload Flow

```mermaid
sequenceDiagram
    participant User
    participant Frontend as 🖥️ Upload Dashboard
    participant API as ⚡ FastAPI /upload_eob
    participant Handler as 📄 upload_eob.py
    participant Extractor as 🔍 extractors.py
    participant Groq as 🤖 Groq Adapter
    participant GroqAPI as ☁️ Groq API
    participant Session as 💾 Session Manager
    participant FS as 📁 File System

    User->>Frontend: Upload PDF/DOCX/Image
    Frontend->>API: POST /upload_eob (multipart file)
    API->>Handler: handle_upload_file(filename, content)
    
    alt PDF Document
        Handler->>Extractor: _extract_from_pdf_bytes()
        Extractor-->>Handler: raw_text, page_count
    else DOCX Document
        Handler->>Extractor: _extract_from_docx_bytes()
        Extractor-->>Handler: raw_text, paragraphs
    else Image (PNG/JPG)
        Handler->>Groq: extract_text_from_image(bytes)
        Groq->>GroqAPI: Vision API (Llama 3.2 11B)
        Note over GroqAPI: OCR Processing
        GroqAPI-->>Groq: Extracted Text
        Groq-->>Handler: raw_text
    end

    Handler->>Groq: extract_structured_eob_text(raw_text)
    Groq->>GroqAPI: Chat Completion (Llama 3.3 70B)
    Note over GroqAPI: JSON Extraction
    GroqAPI-->>Groq: Structured Claims JSON
    Groq-->>Handler: claim_rows[]

    Handler->>Session: append_claim_rows(session_id, rows)
    Handler->>Session: append_raw_pages(session_id, pages)
    Session->>FS: Write claims.json, raw_pages.json
    Handler-->>API: {session_id, doc_id, pages, claims}
    API-->>Frontend: Upload Result
    Frontend-->>User: Display Claims Table
```

### 2. RAG Query Flow (Ask Lumi / Explain Bill)

```mermaid
sequenceDiagram
    participant User
    participant Frontend as 🖥️ Ask Lumi Page
    participant API as ⚡ FastAPI /chat
    participant RAG as 🧠 rag.py
    participant Search as 🔍 Hybrid Search
    participant Session as 💾 Session Manager
    participant LLM as 🤖 Gemini/Groq
    participant ExtAPI as ☁️ LLM API

    User->>Frontend: "Why was my claim denied?"
    Frontend->>API: POST /chat {question, doc_id, session_id}
    API->>RAG: answer_with_citations(question, doc_id)
    
    RAG->>Session: _load_profile(session_id)
    Session-->>RAG: Profile Data (deductible, OOP max)
    
    RAG->>Search: local_search(question, doc_id, session_id)
    Search->>Search: BM25 Scoring
    Search->>Search: Sentence Transformer Embeddings
    Search->>Session: load_claim_rows(session_id)
    Session-->>Search: Claim Documents
    Search-->>RAG: Top-K Hits [{doc_id, line_id, score}]

    RAG->>RAG: _normalize_hits(), _to_citations()
    RAG->>LLM: verbalize(persona, level, payload)
    LLM->>ExtAPI: Generate Response
    ExtAPI-->>LLM: Natural Language Answer
    LLM-->>RAG: Verbalized Answer

    RAG-->>API: {answer, citations, verifiability_score}
    API-->>Frontend: Response with Sources
    Frontend-->>User: Display Answer + Citations
```

### 3. Bill Simulation Flow

```mermaid
sequenceDiagram
    participant User
    participant Frontend as 🖥️ Simulate Costs
    participant API as ⚡ FastAPI /simulate
    participant PolicySim as 📊 policy_sim.py
    participant MathGuard as 🔢 math_guard.py
    participant Session as 💾 Session Manager

    User->>Frontend: Set deductible=$500, coinsurance=20%
    Frontend->>API: POST /simulate {session_id, policy_params}
    
    API->>Session: load_claim_rows_for_doc(session_id, doc_id)
    Session-->>API: [claim_rows]
    
    API->>PolicySim: simulate(claims, policy_params)
    PolicySim->>MathGuard: validate_amounts()
    MathGuard-->>PolicySim: validated_data
    
    PolicySim->>PolicySim: Calculate allowed amounts
    PolicySim->>PolicySim: Apply deductible
    PolicySim->>PolicySim: Apply coinsurance
    PolicySim->>PolicySim: Cap at OOP maximum
    
    PolicySim-->>API: {simulated_resp, actual_resp, delta}
    API-->>Frontend: Simulation Results
    Frontend-->>User: Side-by-side Comparison
```

### 4. Appeal Generation Flow

```mermaid
sequenceDiagram
    participant User
    participant Frontend as 🖥️ Generate Appeal
    participant API as ⚡ FastAPI /appeal
    participant Appeal as 📝 appeal.py
    participant Copywriter as ✍️ copywriter.py
    participant Groq as 🤖 Groq Adapter
    participant GroqAPI as ☁️ Groq API
    participant Exporter as 📄 exporter.py

    User->>Frontend: Request denial appeal
    Frontend->>API: POST /appeal/ai {session_id, doc_id, user_context}
    
    API->>Appeal: generate_appeal(claim_data, context)
    Appeal->>Copywriter: draft_appeal_letter()
    Copywriter->>Groq: complete_text(appeal_prompt)
    Groq->>GroqAPI: Llama 3.3 70B
    GroqAPI-->>Groq: Draft Letter
    Groq-->>Copywriter: appeal_text
    
    Copywriter-->>Appeal: Formatted Letter
    Appeal-->>API: Appeal Content
    
    alt Export as PDF
        API->>Exporter: generate_pdf()
        Exporter-->>API: PDF Bytes
    else Export as DOCX
        API->>Exporter: generate_docx()
        Exporter-->>API: DOCX Bytes
    end
    
    API-->>Frontend: Downloadable Document
    Frontend-->>User: Download Appeal Letter
```

---

## Component Data Exchange Summary

| Source Component | Target Component | Data Type | Description |
|-----------------|------------------|-----------|-------------|
| **Frontend** | FastAPI | HTTP Requests | JSON payloads, multipart files |
| **upload_eob.py** | Groq Adapter | Image bytes | For OCR processing |
| **upload_eob.py** | Groq Adapter | Raw text | For structured JSON extraction |
| **Groq Adapter** | Groq API | Base64 image + prompt | Vision model request |
| **Groq Adapter** | Groq API | Text prompt | Chat completion request |
| **Gemini Adapter** | Gemini API | Image + prompt | Vision extraction |
| **Gemini Adapter** | Gemini API | JSON payload | Verbalization request |
| **rag.py** | hybrid_local.py | Query string | Search request |
| **hybrid_local.py** | Session Manager | Session ID | Load claims data |
| **Session Manager** | File System | JSON data | Persist session state |
| **extractors.py** | upload_eob.py | Parsed rows, raw text | Document content |
| **RAG Engine** | LLM Adapters | Payload + citations | Generate response |

---

## Technology Stack Summary

```mermaid
mindmap
  root((LumiClaim))
    Frontend
      Streamlit
      Python 3.11+
      HTTP Requests
    Backend
      FastAPI
      Pydantic
      CORS Middleware
    LLM Layer
      Groq Cloud
        Llama 3.2 11B Vision
        Llama 3.3 70B Versatile
      Google Gemini
        Gemini 2.0 Flash
      Vertex AI
        Optional
    Search
      BM25 Algorithm
      Sentence Transformers
      all-MiniLM-L6-v2
    Document Processing
      pdfplumber PDF
      python-docx DOCX
      Pillow Images
      Tesseract OCR backup
    Data Storage
      JSON Files
      Session-based
      Per-user isolation
```

---

## API Endpoints Reference

| Endpoint | Method | Purpose | Data In | Data Out |
|----------|--------|---------|---------|----------|
| `/upload_eob` | POST | Upload EOB document | Multipart file | session_id, doc_id, claims |
| `/chat` | POST | RAG Q&A | question, doc_id | answer, citations |
| `/explain/{doc_id}` | GET | Bill explanation | persona, level | breakdown, narrative |
| `/simulate` | POST | Cost simulation | policy_params | simulated vs actual |
| `/appeal/pdf` | POST | Generate appeal PDF | doc_id, context | PDF bytes |
| `/profile/set` | POST | Save user profile | profile_data | success status |
| `/profile/get` | GET | Get user profile | session_id | profile_data |
| `/session/start` | POST | Create session | optional session_id | session_id |
| `/sbc/parse` | POST | Parse SBC document | PDF file | plan attributes |

---

## Environment Variables

| Variable | Purpose | Used By |
|----------|---------|---------|
| `GROQ_API_KEY` | Groq Cloud authentication | groq_adapter.py |
| `GEMINI_API_KEY` | Google AI authentication | gemini_adapter.py |
| `USE_VERTEX` | Enable Vertex AI | config.py, rag.py |
| `USE_ELASTIC` | Enable Elasticsearch | config.py, rag.py |

---

## Key Data Flows Summary

1. **Document Upload → OCR → Structured Extraction → Storage**
   - Files go through format-specific extractors
   - Groq Vision handles image OCR
   - Groq LLM converts text to structured JSON claims
   - Session manager persists to file system

2. **User Query → Hybrid Search → RAG → LLM Response**
   - BM25 + vector embeddings find relevant claims
   - Context assembled with profile data
   - LLM generates natural language answer with citations

3. **Simulation → Policy Rules → Comparison**
   - User's policy parameters applied to actual claims
   - Mathematical calculation of expected vs actual responsibility
   - Delta analysis for potential savings/issues

4. **Appeal → AI Copywriting → Export**
   - Claim data assembled with denial context
   - LLM generates professional appeal letter
   - Exported as PDF or DOCX for submission
