# TranscribeAI

<!-- impeccable:product-schema 1 -->

## Platform
web

## Users
Personal meeting archive for a developer looking up past technical discussions.

## Product Purpose
Import Microsoft Teams WebVTT transcripts and answer questions across meetings, with verifiable speaker and timestamp references.

## Operating Context
Runs locally in Docker. Uses OpenRouter for inexpensive language and embedding models. User supplies existing VTT exports and can upload more later.

## Capabilities and Constraints
Upload, transcript reader, hybrid search, persistent conversations, clickable citations. Backend owns all durable state. Each browser session supplies its own OpenRouter key; credentials are temporary backend memory, not shared environment secrets. The archive remains shared on this local installation. No Microsoft Graph integration in this first version. Personal local use, not a shared enterprise deployment.

## Evidence on Hand
Synthetic WebVTT example in examples/demo.vtt and synthetic test fixtures. Private source files are ignored by Git. Meeting dates must be supplied by the user when not present in the VTT.

## Product Principles
Preserve the original words and timestamps. Distinguish evidence from inference. Keep inference costs small. Never return provider credentials in API responses or persist them in browser storage.
