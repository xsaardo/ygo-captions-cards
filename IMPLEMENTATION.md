# YGO Commentary Card Overlay — Technical Implementation Plan

> **Audience**: Engineers building and maintaining this system.
> Companion to [RESEARCH.md](./RESEARCH.md), which covers viability. This document
> covers how to build it, what tradeoffs exist, and how to test it.

## Table of Contents

1. [Architecture Deep Dive](#1-architecture-deep-dive)
2. [Module Breakdown](#2-module-breakdown)
3. [Card Resolver: Implementation Detail](#3-card-resolver-implementation-detail)
4. [Alias Dictionary Design](#4-alias-dictionary-design)
5. [STT Integration](#5-stt-integration)
6. [Overlay Server & Client](#6-overlay-server--client)
7. [Data Pipeline & Caching](#7-data-pipeline--caching)
8. [Configuration & Runtime Controls](#8-configuration--runtime-controls)
9. [Tradeoff Analysis](#9-tradeoff-analysis)
10. [Testing Strategy](#10-testing-strategy)
11. [Deployment & Operations](#11-deployment--operations)
12. [Future Extensions](#12-future-extensions)

---

## 1. Architecture Deep Dive

### 1.1 Process Model

The system runs as a **single Python process** with three concurrent async tasks
communicating through in-memory queues:

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Main Process (asyncio event loop)                                        │
│                                                                           │
│  ┌──────────────┐    asyncio.Queue     ┌──────────────┐    asyncio.Queue  │
│  │ STT Client   │ ──────────────────▶  │ Card Resolver│ ──────────────▶   │
│  │ (WebSocket)  │   TranscriptEvent    │ (sync, runs  │   CardEvent      │
│  └──────────────┘                      │  in executor)│                   │
│                                        └──────────────┘                   │
│                                                                           │
│  ┌──────────────┐                                                         │
│  │ Overlay WS   │ ◀── reads from CardEvent queue                          │
│  │ Server       │     broadcasts to connected overlay clients              │
│  │ + HTTP       │                                                         │
│  └──────────────┘                                                         │
└────────────────────────────────────────────────────────────────────────────┘
```

**Why single-process?**
- All communication is in-memory (zero serialization overhead)
- Simpler deployment (one `python main.py` command)
- The resolver is CPU-bound but fast (~5ms); running in a thread executor avoids
  blocking the event loop without needing multiprocessing
- If latency profiling later shows the resolver is a bottleneck, it can be moved
  to a subprocess with minimal refactoring (swap Queue for multiprocessing.Queue)

### 1.2 Data Flow Types

```python
@dataclass
class TranscriptEvent:
    text: str           # The transcribed text segment
    is_final: bool      # True if this is a finalized transcript (not interim)
    timestamp: float    # Time of utterance (from STT or wall clock)
    confidence: float   # STT confidence score (0.0 - 1.0)

@dataclass
class CardEvent:
    action: str         # "show" | "hide" | "clear"
    card_id: int        # YGOProDeck card ID (passwd)
    card_name: str      # Official card name
    image_path: str     # Local path to cached card image
    match_source: str   # "alias" | "fuzzy" | "phonetic" | "context"
    match_score: float  # Confidence of the match (0.0 - 1.0)
    timestamp: float
```

### 1.3 Concurrency Model

| Task | Type | Runs In | Notes |
|------|------|---------|-------|
| STT WebSocket client | I/O-bound | Event loop | `websockets` or SDK async client |
| Transcript processing | CPU-bound (light) | `loop.run_in_executor(None, ...)` | Regex + string ops |
| Card resolution | CPU-bound (light) | `loop.run_in_executor(None, ...)` | rapidfuzz + jellyfish |
| Overlay HTTP server | I/O-bound | Event loop | `aiohttp` or `websockets` |
| Overlay WebSocket broadcast | I/O-bound | Event loop | Fan-out to connected clients |
| Card image prefetch | I/O-bound | Event loop | `aiohttp` downloads on startup |

---

## 2. Module Breakdown

```
ygo-captions-cards/
├── main.py                  # Entry point, wires up async tasks
├── config.py                # Runtime configuration (dataclass + env/CLI)
├── stt/
│   ├── __init__.py
│   ├── base.py              # Abstract STT client interface
│   ├── deepgram_client.py   # Deepgram streaming implementation
│   └── assemblyai_client.py # AssemblyAI streaming implementation
├── resolver/
│   ├── __init__.py
│   ├── pipeline.py          # Orchestrates Tier 1-4 resolution
│   ├── alias_dict.py        # Tier 1: exact alias lookup
│   ├── fuzzy.py             # Tier 2: rapidfuzz matching
│   ├── phonetic.py          # Tier 3: Double Metaphone matching
│   ├── context.py           # Tier 4: deck-aware disambiguation
│   └── text_extract.py      # Extract candidate card mentions from transcript text
├── overlay/
│   ├── __init__.py
│   ├── server.py            # HTTP + WebSocket server (aiohttp)
│   └── static/
│       ├── overlay.html      # OBS Browser Source page
│       ├── overlay.css
│       └── overlay.js
├── data/
│   ├── __init__.py
│   ├── card_db.py           # Card database loader + search index
│   ├── image_cache.py       # Card image downloader + local cache
│   └── aliases.json         # Curated alias dictionary
├── tests/
│   ├── conftest.py
│   ├── test_alias_dict.py
│   ├── test_fuzzy.py
│   ├── test_phonetic.py
│   ├── test_pipeline.py
│   ├── test_text_extract.py
│   ├── test_overlay_server.py
│   ├── test_integration.py
│   └── fixtures/
│       ├── sample_transcripts.json
│       ├── card_db_subset.json
│       └── aliases_test.json
└── scripts/
    ├── download_cards.py     # One-time card DB + image download
    ├── update_aliases.py     # Helper to add/validate alias entries
    └── benchmark_resolver.py # Performance benchmarking
```

### 2.1 Dependency List

```
# requirements.txt
rapidfuzz>=3.0.0
jellyfish>=1.0.0
websockets>=12.0
aiohttp>=3.9.0
deepgram-sdk>=3.0.0

# dev
pytest>=8.0
pytest-asyncio>=0.23
pytest-benchmark>=4.0
hypothesis>=6.0
```

---

## 3. Card Resolver: Implementation Detail

### 3.1 Text Extraction (Pre-resolution)

Before running the resolution pipeline, we need to extract **candidate card
mentions** from free-form transcript text. This is non-trivial because card names
range from one word ("Nibiru") to seven words ("Number 86: Heroic Champion
Rhongomyniad").

**Approach: sliding n-gram window**

```python
def extract_candidates(text: str, max_ngram: int = 6) -> list[str]:
    """
    Generate candidate phrases from transcript text.

    Given "he activates Ash Blossom in response to the Snake Eye play",
    yields: ["he", "he activates", "he activates ash", ...,
             "ash", "ash blossom", "ash blossom in", ...,
             "snake", "snake eye", "snake eye play", ...]

    The resolver tests each candidate against the alias dict and card DB.
    Short-circuits on alias dict hits to avoid unnecessary fuzzy matching.
    """
    tokens = normalize(text).split()
    candidates = []
    for i in range(len(tokens)):
        for j in range(i + 1, min(i + max_ngram + 1, len(tokens) + 1)):
            candidates.append(" ".join(tokens[i:j]))
    return candidates
```

**Optimization**: Check candidates against the alias dictionary longest-first.
If "ash blossom" matches, skip "ash" as a separate candidate to avoid duplicate
matches. Track matched token spans to prevent overlapping matches.

**Alternative considered**: Named Entity Recognition (NER). A fine-tuned NER model
could identify card name spans directly. However:
- No training data exists for YGO card names in commentary
- Creating labeled training data is more work than maintaining an alias dictionary
- The n-gram + alias dictionary approach achieves similar accuracy for known cards
- NER would help with *unknown* cards, but those are rare in tournament commentary
  (commentators discuss meta-relevant cards 95%+ of the time)

### 3.2 Tier 1: Alias Dictionary Lookup

```python
class AliasDictionary:
    def __init__(self, path: str = "data/aliases.json"):
        with open(path) as f:
            raw = json.load(f)
        # Build normalized lookup: lowercase, strip punctuation
        self._map: dict[str, AliasEntry] = {}
        for alias, entry in raw.items():
            self._map[normalize(alias)] = AliasEntry(**entry)

    def lookup(self, text: str) -> AliasEntry | None:
        return self._map.get(normalize(text))
```

**Time complexity**: O(1) per lookup (hash map).
**Space**: ~500 entries * ~100 bytes = ~50KB. Negligible.

### 3.3 Tier 2: Fuzzy String Matching

```python
from rapidfuzz import fuzz, process

class FuzzyMatcher:
    def __init__(self, card_names: list[str]):
        # Pre-compute lowercased names for matching
        self._names = card_names
        self._names_lower = [n.lower() for n in card_names]

    def match(self, query: str, threshold: int = 80) -> list[tuple[str, float]]:
        results = process.extract(
            query.lower(),
            self._names_lower,
            scorer=fuzz.token_set_ratio,
            limit=5,
            score_cutoff=threshold,
        )
        # Map back to original-cased names
        return [(self._names[idx], score) for _, score, idx in results]
```

**Scorer choice — `token_set_ratio` vs alternatives:**

| Scorer | What it does | Good for | Bad for |
|--------|-------------|----------|---------|
| `ratio` | Simple Levenshtein ratio | Typo correction ("Nibirue" → "Nibiru") | Partial names ("Ash" vs "Ash Blossom & Joyous Spring") |
| `partial_ratio` | Best substring match | Substrings ("Sanctifire" in "Albion the Sanctifire Dragon") | Short queries matching unrelated long names |
| `token_sort_ratio` | Sort tokens, then ratio | Word reordering | Partial matches |
| **`token_set_ratio`** | **Intersection of token sets** | **Partial names with shared tokens** | **Very short (1-token) queries** |
| `WRatio` | Weighted combination | General-purpose | Slower, less predictable |

**Recommendation**: Use `token_set_ratio` as primary scorer. For single-token
queries (e.g., "Ash"), also run `partial_ratio` and take the best result across
both scorers. This handles both partial names and substring matches well.

**Performance**: `rapidfuzz.process.extract` against 13,000 card names completes
in ~3-5ms on a modern CPU. This is fast enough for real-time use without
pre-filtering.

### 3.4 Tier 3: Phonetic Matching

```python
import jellyfish

class PhoneticMatcher:
    def __init__(self, card_names: list[str]):
        # Pre-encode all card name tokens with Double Metaphone
        self._index: dict[str, list[tuple[str, int]]] = {}  # phonetic_code -> [(card_name, token_pos)]
        for name in card_names:
            for i, token in enumerate(name.lower().split()):
                codes = jellyfish.metaphone(token)  # primary code
                if codes:
                    self._index.setdefault(codes, []).append((name, i))

    def match(self, query: str) -> list[str]:
        query_tokens = query.lower().split()
        candidates: dict[str, int] = {}  # card_name -> matching_token_count
        for token in query_tokens:
            code = jellyfish.metaphone(token)
            if code and code in self._index:
                for card_name, _ in self._index[code]:
                    candidates[card_name] = candidates.get(card_name, 0) + 1
        # Sort by number of matching phonetic tokens (descending)
        return sorted(candidates, key=candidates.get, reverse=True)
```

**When phonetic matching adds value:**
- STT produces "Nibirue" → Metaphone("Nibirue") ≈ Metaphone("Nibiru") → match
- STT produces "Ash Blossum" → "Blossum" ≈ "Blossom" phonetically → match
- Accented pronunciation: "Teerlaments" → "Tearlaments" → match

**When it doesn't help:**
- Slang ("Salads" → "Salamangreat") — phonetically unrelated
- Acronyms ("DRNM" → "Dark Ruler No More") — no phonetic similarity
- These cases must be handled by the alias dictionary (Tier 1)

### 3.5 Tier 4: Context-Aware Disambiguation

```python
class ContextResolver:
    def __init__(self):
        self._active_archetypes: list[str] = []  # Set per match

    def set_match_context(self, player1_deck: str, player2_deck: str):
        """Called at match start with known deck archetypes."""
        self._active_archetypes = [player1_deck, player2_deck]

    def disambiguate(self, candidates: list[tuple[str, float]], card_db) -> str:
        """
        Given multiple fuzzy match candidates with similar scores,
        prefer cards belonging to currently active archetypes.
        """
        for name, score in candidates:
            card = card_db.get_by_name(name)
            if card and card.archetype in self._active_archetypes:
                return name
        # No archetype match — return highest-scoring candidate
        return candidates[0][0] if candidates else None
```

**LLM fallback** (optional, adds 200-500ms):

Only invoke when:
1. Multiple candidates score within 5 points of each other
2. None belong to an active archetype
3. The commentary context is genuinely ambiguous

This should be rare (<1% of resolutions) in practice. An LLM call can be
dispatched asynchronously — show the best-guess card immediately, then correct
if the LLM disagrees.

### 3.6 Resolution Pipeline Orchestration

```python
class ResolutionPipeline:
    def __init__(self, alias_dict, fuzzy_matcher, phonetic_matcher, context_resolver):
        self.alias = alias_dict
        self.fuzzy = fuzzy_matcher
        self.phonetic = phonetic_matcher
        self.context = context_resolver
        self._recent: OrderedDict[str, float] = OrderedDict()  # dedup window

    def resolve(self, transcript: str) -> list[CardEvent]:
        events = []
        candidates = extract_candidates(transcript)
        matched_spans = set()

        # Sort candidates longest-first for greedy matching
        candidates_sorted = sorted(candidates, key=len, reverse=True)

        for candidate in candidates_sorted:
            # Skip if this span overlaps with an already-matched span
            if self._overlaps(candidate, matched_spans, transcript):
                continue

            # Tier 1: Alias dictionary
            alias_hit = self.alias.lookup(candidate)
            if alias_hit:
                events.append(self._make_event(alias_hit, "alias", 1.0))
                matched_spans.add(candidate)
                continue

            # Skip very short candidates for fuzzy/phonetic (too noisy)
            if len(candidate) < 4:
                continue

            # Tier 2: Fuzzy matching
            fuzzy_hits = self.fuzzy.match(candidate, threshold=80)
            if fuzzy_hits:
                if len(fuzzy_hits) == 1 or fuzzy_hits[0][1] - fuzzy_hits[1][1] > 10:
                    # Clear winner
                    events.append(self._make_event(fuzzy_hits[0], "fuzzy", fuzzy_hits[0][1] / 100))
                    matched_spans.add(candidate)
                    continue

                # Tier 4: Disambiguate among close candidates
                best = self.context.disambiguate(fuzzy_hits)
                if best:
                    events.append(self._make_event(best, "context", 0.75))
                    matched_spans.add(candidate)
                    continue

            # Tier 3: Phonetic fallback
            phonetic_hits = self.phonetic.match(candidate)
            if phonetic_hits:
                events.append(self._make_event(phonetic_hits[0], "phonetic", 0.6))
                matched_spans.add(candidate)

        return self._dedup(events)

    def _dedup(self, events: list[CardEvent]) -> list[CardEvent]:
        """Suppress duplicate card mentions within a cooldown window."""
        result = []
        now = time.time()
        for event in events:
            last_shown = self._recent.get(event.card_id)
            if last_shown and now - last_shown < 10.0:  # 10-second cooldown
                continue
            self._recent[event.card_id] = now
            result.append(event)
        # Evict old entries
        while self._recent and next(iter(self._recent.values())) < now - 30:
            self._recent.popitem(last=False)
        return result
```

---

## 4. Alias Dictionary Design

### 4.1 Schema

```jsonc
// data/aliases.json
{
  "_meta": {
    "version": "2026-03-01",
    "card_count": 342,
    "last_banlist": "2026-02-02",
    "notes": "Updated for February 2026 banlist + LEDE set release"
  },
  "entries": {
    // Hand traps & staples
    "ash": { "id": 14558127, "name": "Ash Blossom & Joyous Spring" },
    "ash blossom": { "id": 14558127, "name": "Ash Blossom & Joyous Spring" },
    "nib": { "id": 27204311, "name": "Nibiru, the Primal Being" },
    "nibiru": { "id": 27204311, "name": "Nibiru, the Primal Being" },
    "imperm": { "id": 10045474, "name": "Infinite Impermanence" },
    "infinite imperm": { "id": 10045474, "name": "Infinite Impermanence" },

    // Acronyms
    "drnm": { "id": 48382095, "name": "Dark Ruler No More" },
    "cbtg": { "id": 24224830, "name": "Called by the Grave" },
    "rota": { "id": 32807846, "name": "Reinforcement of the Army" },

    // Community slang (archetype-level)
    "salads": { "archetype": "Salamangreat", "default_id": 0 },
    "floo": { "archetype": "Floowandereeze", "default_id": 0 },
    "flunder": { "archetype": "Floowandereeze", "default_id": 0 },

    // STT error variants (phonetic near-misses the STT commonly produces)
    "ash blossum": { "id": 14558127, "name": "Ash Blossom & Joyous Spring" },
    "nibirue": { "id": 27204311, "name": "Nibiru, the Primal Being" }
  }
}
```

**Key design decisions:**

1. **Flat map, not nested**: One lookup key per entry. Multiple aliases for the
   same card are separate entries. This keeps lookup O(1) and makes it trivial
   to add/remove entries.

2. **Card ID as primary key**: The `id` field is the YGOProDeck card `id`
   (the card's password/passcode). This is stable across reprints and database
   updates.

3. **Archetype entries**: Some slang refers to an entire archetype, not a
   specific card. These have an `archetype` field instead of `id`. The resolver
   can either show a generic archetype image or pick the most commonly played
   card from that archetype.

4. **STT error variants**: Pre-seed the dictionary with common STT
   mistranscriptions observed during testing. This is the cheapest way to fix
   recurring STT errors — no ML required.

5. **Version metadata**: Track when the dictionary was last updated and against
   which banlist. This aids maintenance hygiene.

### 4.2 Maintenance Workflow

```
1. New banlist drops (quarterly)
   └─▶ Check newly meta-relevant decks on yugiohmeta.com / ygoprodeck.com
   └─▶ Add alias entries for new staples/archetypes
   └─▶ Remove entries for cards that fell out of meta (optional — extra entries are harmless)
   └─▶ Run `scripts/update_aliases.py --validate` to check all IDs still resolve
   └─▶ Bump version in _meta

2. New set release
   └─▶ Same as above, but only add cards that see competitive play
   └─▶ Wait 1-2 weeks after release to see what the meta settles on

3. After a tournament (continuous improvement)
   └─▶ Review resolver logs for unmatched transcript segments
   └─▶ Add aliases for any cards that were mentioned but not resolved
   └─▶ Add STT error variants for recurring mistranscriptions
```

### 4.3 Alias Validation Script

```python
# scripts/update_aliases.py --validate
# Checks that every alias entry's card ID exists in the local card DB
# and that the name matches. Reports orphaned entries.
```

---

## 5. STT Integration

### 5.1 Abstract Interface

```python
class STTClient(ABC):
    @abstractmethod
    async def connect(self, keyterms: list[str]) -> None: ...

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None: ...

    @abstractmethod
    async def receive_transcripts(self) -> AsyncIterator[TranscriptEvent]: ...

    @abstractmethod
    async def disconnect(self) -> None: ...
```

Both Deepgram and AssemblyAI implementations conform to this interface, making
the STT provider swappable via configuration.

### 5.2 Deepgram Implementation Notes

```python
class DeepgramClient(STTClient):
    async def connect(self, keyterms: list[str]):
        options = LiveOptions(
            model="nova-3",
            language="en",
            smart_format=True,
            interim_results=True,
            utterance_end_ms=1000,
            vad_events=True,
            keywords=keyterms,       # Keyterm prompting (up to 100 terms)
        )
        self._connection = await self._client.listen.asyncwebsocket.v("1")
        await self._connection.start(options)
```

**Keyterm strategy:**
- Dynamically compose the keyterm list per match
- Priority order: (1) both players' deck card names, (2) universal staples, (3) common side deck cards
- Limit: 100 terms. With ~50 cards per deck + ~30 staples, this fits comfortably.

### 5.3 Interim vs. Final Transcripts

STT services emit two types of results:

| Type | Stability | Use |
|------|----------|-----|
| **Interim** | May change as more audio arrives | Use for "speculative" resolution — show a card immediately but be prepared to replace it |
| **Final** | Locked, won't change | Use for "confirmed" resolution — log the match, update cooldown timers |

**Policy**: Resolve on interim results for minimum latency, but only log/count
matches from final results. If an interim result triggers a card display and the
final result changes the match, send a `hideCard` + new `showCard`.

### 5.4 Audio Capture

```bash
# Capture system audio and pipe as 16kHz PCM mono to the STT client
ffmpeg -f pulse -i default \           # PulseAudio (Linux)
       -ac 1 -ar 16000 -f s16le \      # mono, 16kHz, 16-bit signed little-endian
       pipe:1                           # stdout → Python reads via subprocess
```

On macOS, replace `-f pulse -i default` with `-f avfoundation -i ":0"`.
On Windows, use `-f dshow -i audio="Stereo Mix"`.

The Python process reads `stdout` of the ffmpeg subprocess in fixed-size chunks
(e.g., 4096 bytes = 128ms of 16kHz mono PCM) and feeds them to `send_audio()`.

---

## 6. Overlay Server & Client

### 6.1 Server (aiohttp)

```python
# overlay/server.py
app = web.Application()
app.router.add_static("/static", "overlay/static")
app.router.add_get("/overlay", serve_overlay_html)
app.router.add_get("/ws", websocket_handler)

# WebSocket handler fans out CardEvents to all connected overlay clients
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    clients.add(ws)
    try:
        async for msg in ws:
            pass  # Overlay client doesn't send messages
    finally:
        clients.discard(ws)
    return ws

async def broadcast_card_event(event: CardEvent):
    payload = json.dumps({
        "action": "showCard",
        "cardId": event.card_id,
        "cardName": event.card_name,
        "imageUrl": f"/cards/{event.card_id}.jpg",
        "matchSource": event.match_source,
        "matchScore": event.match_score,
    })
    await asyncio.gather(*(ws.send_str(payload) for ws in clients))
```

### 6.2 Overlay Client (Browser Source)

The overlay HTML/JS runs inside OBS Browser Source. Key considerations:

- **No framework** — vanilla JS to minimize load time and memory in OBS's
  embedded Chromium
- **requestAnimationFrame** for animations (CSS transitions preferred over JS animation)
- **Card queue**: If multiple cards arrive within the display window, queue them
  and cycle through with a configurable hold duration
- **Auto-hide**: Cards fade out after a configurable timeout (default: 5 seconds)

```javascript
// overlay/static/overlay.js (sketch)
const HOLD_MS = 5000;
const FADE_MS = 500;
const queue = [];
let displaying = false;

function onCardEvent(event) {
  queue.push(event);
  if (!displaying) showNext();
}

function showNext() {
  if (queue.length === 0) { displaying = false; return; }
  displaying = true;
  const card = queue.shift();
  const el = createCardElement(card);
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("visible"));
  setTimeout(() => {
    el.classList.remove("visible");
    setTimeout(() => { el.remove(); showNext(); }, FADE_MS);
  }, HOLD_MS);
}
```

### 6.3 Display Modes

| Mode | Behavior | Best For |
|------|----------|----------|
| **Latest wins** | New card immediately replaces current | Fast-paced commentary |
| **Queue** | Cards cycle through in order, each shown for N seconds | Slower commentary, educational content |
| **Stack** | Show up to N cards simultaneously in a column | Combo sequences where multiple cards matter |

Default to **latest wins** — it's the least cluttered and most responsive.
Configurable via `config.py`.

---

## 7. Data Pipeline & Caching

### 7.1 Card Database

```python
# data/card_db.py
class CardDatabase:
    def __init__(self, db_path: str = "data/cards.json"):
        self._cards: dict[int, Card] = {}        # id -> Card
        self._by_name: dict[str, Card] = {}      # lowercase name -> Card
        self._names: list[str] = []              # for fuzzy matching

    async def initialize(self):
        """Load from local cache or download from YGOProDeck."""
        if self._cache_is_stale():
            await self._download()
        self._load_from_cache()
        self._build_indexes()

    def _cache_is_stale(self) -> bool:
        """Check local DB version against YGOProDeck's checkDBVer endpoint."""
        ...

    async def _download(self):
        """
        GET https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes
        Save to data/cards.json (~25MB)
        """
        ...

    def get_by_id(self, card_id: int) -> Card | None: ...
    def get_by_name(self, name: str) -> Card | None: ...
    def all_names(self) -> list[str]: ...
    def cards_in_archetype(self, archetype: str) -> list[Card]: ...
```

### 7.2 Image Cache

```python
# data/image_cache.py
class ImageCache:
    def __init__(self, cache_dir: str = "data/card_images"):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def has(self, card_id: int) -> bool:
        return (self._cache_dir / f"{card_id}.jpg").exists()

    async def ensure_cached(self, card_ids: list[int]):
        """Download missing images, respecting rate limits."""
        missing = [cid for cid in card_ids if not self.has(cid)]
        semaphore = asyncio.Semaphore(10)  # Max 10 concurrent downloads
        async with aiohttp.ClientSession() as session:
            tasks = [self._download_one(session, cid, semaphore) for cid in missing]
            await asyncio.gather(*tasks)

    async def _download_one(self, session, card_id, semaphore):
        async with semaphore:
            url = f"https://images.ygoprodeck.com/images/cards_small/{card_id}.jpg"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    (self._cache_dir / f"{card_id}.jpg").write_bytes(data)
            await asyncio.sleep(0.05)  # Stay under 20 req/s rate limit
```

**Image sizing**: Use `cards_small` (168x245px) for the overlay. Full-size images
(813x1185px) are unnecessary for a ~250px on-screen display and would waste
bandwidth and disk.

### 7.3 Startup Sequence

```
1. Load config from env/CLI/config file
2. Load alias dictionary from data/aliases.json
3. Initialize card database (download if stale)
4. Build fuzzy matcher index from card names
5. Build phonetic index from card name tokens
6. Pre-cache card images for all alias dictionary entries
7. Start overlay HTTP + WebSocket server
8. Connect to STT service with keyterm list
9. Begin processing audio → transcripts → card events → overlay
```

---

## 8. Configuration & Runtime Controls

### 8.1 Configuration

```python
@dataclass
class Config:
    # STT
    stt_provider: str = "deepgram"          # "deepgram" | "assemblyai"
    stt_api_key: str = ""                   # From env: STT_API_KEY
    stt_model: str = "nova-3"

    # Resolver
    alias_path: str = "data/aliases.json"
    fuzzy_threshold: int = 80               # Minimum score for fuzzy match
    fuzzy_single_token_threshold: int = 90  # Higher threshold for 1-word queries
    phonetic_enabled: bool = True
    dedup_cooldown_s: float = 10.0          # Seconds before same card can re-trigger

    # Context
    player1_deck: str = ""                  # Archetype name, set per match
    player2_deck: str = ""

    # Overlay
    overlay_port: int = 9090
    display_mode: str = "latest"            # "latest" | "queue" | "stack"
    hold_duration_ms: int = 5000
    max_visible_cards: int = 3              # For "stack" mode

    # Audio
    audio_source: str = "default"           # PulseAudio source name
    audio_sample_rate: int = 16000
    audio_chunk_ms: int = 100               # Chunk size in milliseconds
```

### 8.2 Runtime Control API

A simple HTTP control API for tournament staff to adjust settings mid-stream:

```
POST /api/match     {"player1_deck": "Snake-Eye", "player2_deck": "Yubel"}
POST /api/clear     Clear all displayed cards
POST /api/show      {"card_id": 14558127}   Manual card trigger
POST /api/config    {"hold_duration_ms": 3000}   Live config update
GET  /api/status    Current state, recent matches, resolver stats
```

---

## 9. Tradeoff Analysis

### 9.1 Resolution Strategy: Dictionary-First vs. Fuzzy-First

| Approach | Pros | Cons |
|----------|------|------|
| **Dictionary-first (recommended)** | Instant for known cards; no false positives on slang; predictable | Requires manual curation; misses cards not in dict |
| **Fuzzy-first** | Zero maintenance; covers all 13k cards | False positives on common words; can't handle slang; slower |

**Decision**: Dictionary-first. The alias dictionary is small (~500 entries),
cheap to maintain (quarterly), and handles the hardest cases (slang, acronyms)
that fuzzy matching cannot. Fuzzy matching serves as a safety net for cards
missing from the dictionary.

### 9.2 Single Process vs. Microservices

| Approach | Pros | Cons |
|----------|------|------|
| **Single process (recommended)** | Simple deployment; zero-copy data sharing; easier debugging | Single point of failure; harder to scale (not needed) |
| **Microservices** | Independent scaling; language flexibility | Network overhead; deployment complexity; overkill for local tool |

**Decision**: Single process. This is a local tool running on one machine at a
tournament venue. There is no scaling requirement. The entire pipeline (STT
client + resolver + overlay server) fits comfortably in one Python process
using ~100MB RAM.

### 9.3 Python vs. Node.js vs. Both

| Approach | Pros | Cons |
|----------|------|------|
| **Python only (recommended)** | Best fuzzy/phonetic libraries (rapidfuzz, jellyfish); single language | Async ecosystem slightly less mature than Node |
| **Node.js only** | Native WebSocket ecosystem; same language as overlay | fuse.js is slower than rapidfuzz; no good phonetic library |
| **Python backend + Node overlay** | Best of both | Two runtimes to deploy and maintain |

**Decision**: Python only. `aiohttp` provides a mature WebSocket + HTTP server.
The overlay client is plain HTML/CSS/JS regardless of backend language.
`rapidfuzz` is significantly faster than `fuse.js` and `jellyfish` has no
JS equivalent of comparable quality.

### 9.4 Interim vs. Final Transcript Resolution

| Approach | Pros | Cons |
|----------|------|------|
| **Resolve on interim (recommended)** | Lowest latency (~200ms faster); feels responsive | May show wrong card briefly if interim changes |
| **Resolve on final only** | No false flashes | Adds 200-500ms latency waiting for finalization |

**Decision**: Resolve on interim. The risk of a brief wrong card is low (STT
interim results are usually close to final) and the latency benefit is
significant. If this causes issues in practice, add a configurable delay
before displaying (e.g., 200ms debounce).

### 9.5 Deduplication Window

If the commentator says "Ash" three times in 15 seconds, should we show the card
three times?

| Strategy | Behavior |
|----------|----------|
| **Cooldown per card (recommended)** | Same card suppressed for N seconds after display. Default: 10s. |
| **No dedup** | Every mention triggers a display. Cluttered. |
| **Only on new card** | Only show when a *different* card is mentioned. Misses re-emphasis. |

**Decision**: 10-second per-card cooldown, configurable. Long enough to avoid
spam, short enough that a re-mention after the card leaves the screen triggers
a fresh display.

---

## 10. Testing Strategy

### 10.1 Unit Tests

Each resolver tier gets its own test suite with known inputs and expected outputs.

**Alias Dictionary Tests** (`test_alias_dict.py`):
```python
def test_exact_match():
    d = AliasDictionary("tests/fixtures/aliases_test.json")
    assert d.lookup("ash").name == "Ash Blossom & Joyous Spring"

def test_case_insensitive():
    d = AliasDictionary("tests/fixtures/aliases_test.json")
    assert d.lookup("ASH") == d.lookup("ash")

def test_miss_returns_none():
    d = AliasDictionary("tests/fixtures/aliases_test.json")
    assert d.lookup("nonexistent card xyz") is None

def test_punctuation_normalized():
    d = AliasDictionary("tests/fixtures/aliases_test.json")
    # 'Maxx "C"' should match regardless of quote style
    assert d.lookup("maxx c").name == 'Maxx "C"'
```

**Fuzzy Matching Tests** (`test_fuzzy.py`):
```python
@pytest.mark.parametrize("query, expected, min_score", [
    ("Ash Blossom", "Ash Blossom & Joyous Spring", 85),
    ("Infinite Impermanence", "Infinite Impermanence", 100),
    ("Nibiru the Primal Being", "Nibiru, the Primal Being", 90),
    ("Effect Veiler", "Effect Veiler", 100),
])
def test_fuzzy_matches_partial_names(query, expected, min_score, fuzzy_matcher):
    results = fuzzy_matcher.match(query)
    assert results[0][0] == expected
    assert results[0][1] >= min_score

def test_fuzzy_rejects_low_similarity(fuzzy_matcher):
    results = fuzzy_matcher.match("the player activates", threshold=80)
    assert len(results) == 0  # Common words should not match any card

def test_fuzzy_short_query_needs_higher_threshold(fuzzy_matcher):
    # "Ash" is only 3 chars — should still match with the right scorer
    results = fuzzy_matcher.match("ash", threshold=50)
    names = [r[0] for r in results]
    assert "Ash Blossom & Joyous Spring" in names
```

**Phonetic Matching Tests** (`test_phonetic.py`):
```python
@pytest.mark.parametrize("misspelling, expected", [
    ("Nibirue", "Nibiru, the Primal Being"),
    ("Ash Blossum", "Ash Blossom & Joyous Spring"),
    ("Teerlaments", "Tearlaments Kitkallos"),
])
def test_phonetic_catches_stt_errors(misspelling, expected, phonetic_matcher):
    results = phonetic_matcher.match(misspelling)
    assert expected in results

def test_phonetic_no_match_for_unrelated_words(phonetic_matcher):
    results = phonetic_matcher.match("hamburger")
    # Should not confidently match any card
    assert len(results) == 0 or results[0] not in STAPLE_CARDS
```

**Text Extraction Tests** (`test_text_extract.py`):
```python
def test_extract_single_card():
    text = "he activates Ash Blossom in response"
    candidates = extract_candidates(text)
    assert "ash blossom" in candidates
    assert "ash" in candidates

def test_extract_multiple_cards():
    text = "chains Nibiru after the fifth summon and also has Imperm set"
    candidates = extract_candidates(text)
    assert "nibiru" in candidates
    assert "imperm" in candidates

def test_ngram_limit():
    text = " ".join(["word"] * 20)
    candidates = extract_candidates(text, max_ngram=6)
    # No candidate should be longer than 6 tokens
    assert all(len(c.split()) <= 6 for c in candidates)
```

### 10.2 Pipeline Integration Tests

Test the full resolution pipeline with realistic transcript fragments:

```python
# tests/fixtures/sample_transcripts.json
[
    {
        "transcript": "and he's going to activate Ash in response to the Branded Fusion",
        "expected_cards": ["Ash Blossom & Joyous Spring", "Branded Fusion"],
        "description": "Two cards mentioned in one sentence"
    },
    {
        "transcript": "oh he's got the Nib! Nibiru comes down and wipes the board",
        "expected_cards": ["Nibiru, the Primal Being"],
        "description": "Same card mentioned twice (alias + full name), should dedup"
    },
    {
        "transcript": "and that's going to be game, what a fantastic finals",
        "expected_cards": [],
        "description": "No card mentions — should produce zero events"
    },
    {
        "transcript": "activates the imperm from the backrow targeting the snake eye ash",
        "expected_cards": ["Infinite Impermanence", "Snake-Eye Ash"],
        "description": "Alias + partial official name"
    }
]
```

```python
# test_pipeline.py
@pytest.mark.parametrize("case", load_transcript_fixtures())
def test_pipeline_resolves_correctly(case, pipeline):
    events = pipeline.resolve(case["transcript"])
    resolved_names = {e.card_name for e in events}
    expected = set(case["expected_cards"])
    assert resolved_names == expected, (
        f"For '{case['description']}': "
        f"expected {expected}, got {resolved_names}"
    )
```

### 10.3 Property-Based Tests (Hypothesis)

Use Hypothesis to find edge cases in normalization and matching:

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=100))
def test_normalize_is_idempotent(text):
    assert normalize(normalize(text)) == normalize(text)

@given(st.text(min_size=1, max_size=50))
def test_alias_lookup_never_crashes(text, alias_dict):
    # Should return None or a valid entry, never raise
    result = alias_dict.lookup(text)
    assert result is None or isinstance(result, AliasEntry)

@given(st.text(min_size=1, max_size=50))
def test_fuzzy_match_never_crashes(text, fuzzy_matcher):
    results = fuzzy_matcher.match(text)
    assert isinstance(results, list)
    assert all(isinstance(r, tuple) and len(r) == 2 for r in results)
```

### 10.4 False Positive Tests

Explicitly test that common English words and commentary phrases do **not**
trigger card matches:

```python
FALSE_POSITIVE_PHRASES = [
    "and that's going to be game",
    "what a play by the champion",
    "he draws for turn",
    "passes to the battle phase",
    "let's go to game two",
    "the judge is called over",
    "activates the effect",
    "he special summons from the extra deck",
    "sets one and passes",
    "thinking about his options here",
]

@pytest.mark.parametrize("phrase", FALSE_POSITIVE_PHRASES)
def test_no_false_positives_on_common_commentary(phrase, pipeline):
    events = pipeline.resolve(phrase)
    assert len(events) == 0, f"False positive: '{phrase}' matched {events}"
```

### 10.5 Performance Benchmarks

```python
# tests/test_benchmark.py (pytest-benchmark)
def test_alias_lookup_speed(benchmark, alias_dict):
    benchmark(alias_dict.lookup, "ash")
    # Target: <0.01ms per lookup

def test_fuzzy_match_speed(benchmark, fuzzy_matcher):
    benchmark(fuzzy_matcher.match, "Ash Blossom")
    # Target: <10ms against full 13k card database

def test_full_pipeline_speed(benchmark, pipeline):
    text = "he activates Ash in response to the Branded Fusion and chains Imperm"
    benchmark(pipeline.resolve, text)
    # Target: <20ms for a typical commentary sentence

def test_phonetic_index_build_speed(benchmark, card_names):
    benchmark(PhoneticMatcher, card_names)
    # Target: <500ms for full 13k card database (one-time at startup)
```

### 10.6 End-to-End Smoke Test

A manual/semi-automated test using recorded tournament audio:

```
1. Record 60 seconds of YGO tournament commentary (or use a YouTube clip)
2. Run the full pipeline against this audio
3. Verify:
   - Cards appear within 2 seconds of being mentioned
   - No false positives from non-card speech
   - Duplicate mentions are deduplicated
   - The overlay displays and auto-hides correctly
```

This can be partially automated by feeding a pre-recorded WAV file through the
STT client instead of live audio, and comparing the output events against a
manually annotated expected list.

### 10.7 Test Coverage Targets

| Module | Target | Notes |
|--------|--------|-------|
| `resolver/alias_dict.py` | 100% | Simple module, easy to cover |
| `resolver/fuzzy.py` | 95%+ | Parametrized tests cover main paths |
| `resolver/phonetic.py` | 90%+ | Edge cases with unusual Unicode |
| `resolver/pipeline.py` | 95%+ | Integration tests + property tests |
| `resolver/text_extract.py` | 95%+ | N-gram generation is deterministic |
| `overlay/server.py` | 80%+ | WebSocket tests need async fixtures |
| `data/card_db.py` | 80%+ | Mock HTTP responses for download tests |

---

## 11. Deployment & Operations

### 11.1 Installation

```bash
git clone <repo>
cd ygo-captions-cards
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Download card database + images (one-time, ~5 min)
python scripts/download_cards.py

# Set STT API key
export STT_API_KEY="your-deepgram-key"
```

### 11.2 Running

```bash
# Start the full pipeline
python main.py

# With match context
python main.py --player1-deck "Snake-Eye" --player2-deck "Yubel"

# With custom overlay port
python main.py --overlay-port 8080
```

### 11.3 OBS Setup

1. Add Browser Source in OBS
2. URL: `http://localhost:9090/overlay`
3. Width: 1920, Height: 1080
4. Check "Shutdown source when not visible" (saves resources)
5. Check "Refresh browser when scene becomes active"

### 11.4 Logging & Observability

```python
# Structured logging for every resolution
logger.info("card_resolved", extra={
    "transcript": "he activates ash",
    "card_name": "Ash Blossom & Joyous Spring",
    "card_id": 14558127,
    "match_source": "alias",
    "match_score": 1.0,
    "latency_ms": 0.3,
})

# Log unresolved transcript segments for alias dictionary improvement
logger.info("unresolved_segment", extra={
    "transcript": "he flips up the anti spell",
    "candidates_tried": ["anti spell"],
    "best_fuzzy": ("Anti-Spell Fragrance", 72),
})
```

Review `unresolved_segment` logs after each tournament to identify missing
aliases and STT error patterns.

### 11.5 Graceful Degradation

| Failure | Behavior |
|---------|----------|
| STT connection drops | Retry with exponential backoff (2s, 4s, 8s, 16s). Overlay shows "Reconnecting..." |
| STT returns empty transcripts | Log warning, continue processing. May indicate audio issue. |
| Card image missing from cache | Show card name as text overlay instead of image |
| Alias dict file missing/corrupt | Fall back to fuzzy-only resolution with warning log |
| Overlay client disconnects | No impact on pipeline. Client reconnects automatically. |

---

## 12. Future Extensions

### 12.1 Game State Tracking

Track the game state (whose turn it is, what phase, LP changes) from commentary
to improve disambiguation. "He activates" + known turn player narrows card
candidates to that player's deck.

### 12.2 Deck List Integration

If tournament organizers provide deck lists (e.g., via Metagame or Neuron app
exports), the system can constrain resolution to only cards in the active
players' decks — dramatically reducing false positives.

### 12.3 Multi-Language Support

Tournament commentary happens in Japanese, Korean, German, Italian, etc.
Each language needs:
- An STT model supporting that language
- Translated/localized alias dictionary entries
- Card name data from YGOProDeck (which provides multi-language names)

### 12.4 Replay/VOD Mode

Process pre-recorded tournament VODs instead of live audio. Useful for content
creators who want to add card overlays to edited videos. Same pipeline, just
reading from a file instead of a live audio stream.

### 12.5 Analytics Dashboard

Track which cards are mentioned most frequently, build heatmaps of card mention
timing (early game vs. late game), and surface trends across tournaments. This
data has value for content creators and meta analysts.
