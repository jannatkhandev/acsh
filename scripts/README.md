# Atlan Documentation Scraper + Ingestor

TBVH used majorly Claude Code to write these scripts

## Overview

This scraper targets two Atlan documentation sites:
- **docs.atlan.com** (Docusaurus framework) - Product documentation
- **developer.atlan.com** (MkDocs Material) - Developer documentation

The scraper creates optimally chunked documents with rich metadata, designed for Pinecone vector database storage and AI-powered support ticket routing.

The ingestor is meant to ingest the scraped data into Pinecone.

## Quick Start

### Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

```bash
# Run the complete scraper
python atlan_docs_crawler.py

# Ingest into Pinecone
python ingest_to_pinecone.py

```
