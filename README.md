# YGO Commentary Card Overlay

Real-time card overlay for Yu-Gi-Oh! tournament livestreams. Listens to commentary audio, identifies mentioned cards, and displays them in OBS.

**Current Status**: Part 3 — Full Live Pipeline

## Features

### Part 1 ✅
- ✅ Alias dictionary with ~80 curated entries (hand traps, staples, meta cards)
- ✅ Text extraction with n-gram candidate generation
- ✅ HTTP + WebSocket overlay server
- ✅ OBS Browser Source integration
- ✅ Manual card trigger API for testing
- ✅ Structured JSON logging

### Part 2 ✅
- ✅ Fuzzy string matching with rapidfuzz (13k+ card names)
- ✅ Phonetic matching with Double Metaphone for STT error correction
- ✅ Context-aware disambiguation using deck archetypes
- ✅ 4-tier resolution pipeline (alias → fuzzy → phonetic → context)
- ✅ STT client scaffolding (Deepgram + AssemblyAI)

### Part 3 ✅
- ✅ Live audio capture via ffmpeg (macOS, Linux, Windows)
- ✅ Full async pipeline (audio → STT → resolver → overlay)
- ✅ Interim transcript debouncing
- ✅ Graceful shutdown and error handling
- ✅ Real-time card display from live commentary

**Coming in Part 4**: LLM disambiguation fallback, VOD dry-run mode, telemetry analytics

## Installation

### Prerequisites

- Python 3.10+
- pip

### Setup

```bash
# Clone the repository
git clone https://github.com/xsaardo/ygo-captions-cards.git
cd ygo-captions-cards

# Install dependencies
pip install -r requirements.txt

# Download card database (optional for Part 1)
python scripts/download_cards.py
```

## Running

### Basic Mode (No STT)

Start the overlay server without live audio:

```bash
python main.py
```

The server will start on `http://localhost:9090` by default. Use the `/api/resolve` endpoint to test card resolution.

### Live Audio Mode (Part 3)

To enable live audio capture and STT:

```bash
# Set your STT API key (Deepgram or AssemblyAI)
export STT_API_KEY="your-api-key-here"

# Start with STT provider
python main.py --stt-provider deepgram
# or
python main.py --stt-provider assemblyai
```

Requirements for live audio:
- ffmpeg must be installed and in PATH
- System audio must be configured (see below)

### System Audio Setup

**macOS:**
- Install ffmpeg: `brew install ffmpeg`
- Install BlackHole or Loopback Audio to capture system audio
- Set BlackHole as the audio input in System Preferences

**Linux:**
- Install ffmpeg: `sudo apt install ffmpeg`
- Use PulseAudio monitor source (default configuration works)

**Windows:**
- Install ffmpeg and add to PATH
- Enable "Stereo Mix" in Sound settings

### Options

```bash
python main.py --overlay-port 8080  # Use a different port
python main.py --player1-deck "Snake-Eye" --player2-deck "Yubel"  # Set match context
python main.py --stt-provider deepgram --stt-api-key YOUR_KEY  # Enable live audio
```

## OBS Setup

1. Add a **Browser Source** in OBS
2. Set URL to: `http://localhost:9090/overlay`
3. Set Width: `1920`, Height: `1080`
4. Check "Shutdown source when not visible" (optional, saves resources)
5. Check "Refresh browser when scene becomes active"

The overlay is transparent and will display cards in the bottom-left corner.

## Testing

### Run All Tests

```bash
pytest tests/ -v
```

### Test the Overlay

Use the `/api/resolve` endpoint to test card resolution:

```bash
curl -X POST http://localhost:9090/api/resolve \
  -H "Content-Type: application/json" \
  -d '{"transcript": "he activates ash blossom"}'
```

The card should appear in the overlay (if OBS Browser Source is connected).

### Manually Show a Card

```bash
curl -X POST http://localhost:9090/api/show \
  -H "Content-Type: application/json" \
  -d '{"card_name": "Ash Blossom & Joyous Spring"}'
```

### Clear the Overlay

```bash
curl -X POST http://localhost:9090/api/clear
```

## API Reference

### POST /api/resolve

Resolve a transcript and show matched cards.

**Request:**
```json
{
  "transcript": "he activates ash blossom"
}
```

**Response:**
```json
{
  "status": "ok",
  "matched_cards": [
    {
      "card_id": 14558127,
      "card_name": "Ash Blossom & Joyous Spring",
      "match_source": "alias",
      "match_score": 1.0
    }
  ],
  "transcript": "he activates ash blossom"
}
```

### POST /api/show

Manually show a card.

**Request:**
```json
{
  "card_id": 14558127
}
```

or

```json
{
  "card_name": "Ash Blossom & Joyous Spring"
}
```

**Response:**
```json
{
  "status": "ok",
  "card_name": "Ash Blossom & Joyous Spring"
}
```

### POST /api/clear

Clear all displayed cards.

**Response:**
```json
{
  "status": "ok"
}
```

### POST /api/match

Set match context (player decks).

**Request:**
```json
{
  "player1_deck": "Snake-Eye",
  "player2_deck": "Yubel"
}
```

**Response:**
```json
{
  "status": "ok",
  "player1_deck": "Snake-Eye",
  "player2_deck": "Yubel"
}
```

### GET /api/status

Get current server status.

**Response:**
```json
{
  "status": "ok",
  "connected_clients": 1,
  "player1_deck": "Snake-Eye",
  "player2_deck": "Yubel"
}
```

## Project Structure

```
ygo-captions-cards/
├── main.py              # Entry point with full async pipeline
├── config.py            # Configuration dataclass
├── requirements.txt     # Python dependencies
├── audio/
│   └── capture.py       # Audio capture via ffmpeg
├── stt/
│   ├── base.py          # STT client interface
│   ├── deepgram_client.py   # Deepgram streaming client
│   └── assemblyai_client.py # AssemblyAI streaming client
├── data/
│   ├── aliases.json     # Alias dictionary (~80 entries)
│   ├── card_db.py       # Card database loader
│   └── image_cache.py   # Card image cache
├── resolver/
│   ├── alias_dict.py    # Tier 1: Alias lookup
│   ├── fuzzy.py         # Tier 2: Fuzzy matching
│   ├── phonetic.py      # Tier 3: Phonetic matching
│   ├── context.py       # Tier 4: Context disambiguation
│   ├── pipeline.py      # 4-tier resolution orchestration
│   └── text_extract.py  # N-gram candidate extraction
├── overlay/
│   ├── server.py        # HTTP + WebSocket server
│   └── static/
│       ├── overlay.html # OBS Browser Source page
│       ├── overlay.css  # Overlay styles
│       └── overlay.js   # WebSocket client
├── telemetry/
│   └── logger.py        # Structured JSON logging
├── scripts/
│   └── download_cards.py # Download card DB from YGOProDeck
└── tests/
    ├── conftest.py
    ├── test_alias_dict.py
    ├── test_fuzzy.py
    ├── test_phonetic.py
    ├── test_pipeline.py
    ├── test_text_extract.py
    ├── test_audio_capture.py
    ├── test_stt_clients.py
    ├── test_integration.py
    └── fixtures/
        ├── aliases_test.json
        └── sample_transcripts.json
```

## Alias Dictionary

The alias dictionary (`data/aliases.json`) contains ~80 curated entries covering:

- Universal hand traps (Ash, Nibiru, Imperm, Veiler, etc.)
- Board breakers (DRNM, Lightning Storm, Evenly, etc.)
- Search/utility staples (Called by, ROTA, Reborn, etc.)
- Meta archetypes (Snake-Eye, Yubel, etc.)
- Community slang (salads, floo, tenpai, etc.)
- Common STT errors (ash blossum, nibirue, impermanance, etc.)

Add new entries as needed following the schema in the spec.

## Telemetry

Resolution logs are written to `logs/resolver.jsonl` in JSONL format:

```json
{"event": "card_resolved", "timestamp": 1234567890, "transcript": "he activates ash", "card_name": "Ash Blossom & Joyous Spring", "card_id": 14558127, "match_source": "alias", "match_score": 1.0, "latency_ms": 0.5}
{"event": "unresolved_segment", "timestamp": 1234567891, "transcript": "unknown card", "candidates_tried": ["unknown", "unknown card"]}
```

Use these logs to identify gaps in the alias dictionary and improve coverage.

## Contributing

See [IMPLEMENTATION.md](./IMPLEMENTATION.md) and [RESEARCH.md](./RESEARCH.md) for full technical details.

## License

MIT
