# AI-Powered RAG Chatbot

An AI-powered chatbot designed to provide contextual and accurate responses using Retrieval-Augmented Generation (RAG). The chatbot is intended to be deployable as a reusable widget that can be integrated into websites that require an intelligent knowledge-based assistant.

The project is currently under development.

## Project Overview

This project aims to develop a reusable AI chatbot powered by Retrieval-Augmented Generation (RAG).

Instead of relying solely on the language model's pre-trained knowledge, the system will retrieve relevant information from a designated knowledge base and provide that information to the AI model as context before generating a response.

The planned AI infrastructure will use **Amazon Bedrock** to access and manage the foundation model used by the chatbot.

## Current Progress

### Completed

- [x] Designed the initial RAG workflow
- [x] Planned the overall chatbot architecture
- [x] Created the initial chatbot widget/icon
- [x] Designed the chatbot to be reusable and embeddable across websites

### In Progress

- [ ] Implement the RAG pipeline
- [ ] Set up Amazon Bedrock
- [ ] Select and configure the foundation model
- [ ] Develop the chatbot backend
- [ ] Implement the knowledge base and retrieval system
- [ ] Connect the chatbot widget to the backend
- [ ] Implement context-aware responses
- [ ] Test response accuracy and relevance

### Planned

- [ ] Website-embeddable chatbot widget
- [ ] Knowledge base management
- [ ] Document ingestion and processing
- [ ] Vector search / semantic retrieval
- [ ] Conversation history
- [ ] Error handling and fallback responses
- [ ] Deployment
- [ ] Performance and response evaluation

## RAG Workflow

The initial RAG workflow was designed around the following process:

```text
User
  ↓
Chatbot Widget
  ↓
User Query
  ↓
Query Processing
  ↓
Knowledge Base Retrieval
  ↓
Relevant Information
  ↓
Amazon Bedrock / Foundation Model
  ↓
Context + User Query
  ↓
Generated Response
  ↓
Chatbot Widget
  ↓
User