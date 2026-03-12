# YGO Commentary Card Overlay — Viability Research

> **Goal**: Build a livestream overlay that listens to Yu-Gi-Oh! tournament commentary audio
> and displays the card image whenever a card is mentioned — including when commentators
> use nicknames, abbreviations, or slang.

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Speech-to-Text (STT)](#3-speech-to-text-stt)
4. [Card Name Resolution (Alias Matching)](#4-card-name-resolution-alias-matching)
5. [Card Data & Images (YGOProDeck API)](#5-card-data--images-ygoprodeck-api)
6. [Livestream Overlay Integration](#6-livestream-overlay-integration)
7. [End-to-End Latency Budget](#7-end-to-end-latency-budget)
8. [Recommended Tech Stack](#8-recommended-tech-stack)
9. [Cost Estimates](#9-cost-estimates)
10. [Risks & Mitigations](#10-risks--mitigations)
11. [Open Questions](#11-open-questions)
12. [Sources](#12-sources)

---

## 1. Executive Summary

**Verdict: This project is viable.** The core pipeline — real-time speech-to-text → card
name resolution → overlay display — can be built with existing tools and services to hit
the target of **under 2 seconds end-to-end latency**.

The key challenges are:

| Challenge | Difficulty | Solution |
|-----------|-----------|----------|
| Recognizing niche card names from speech | High | STT with custom vocabulary boosting (Deepgram/AssemblyAI) |
| Resolving nicknames/slang to official names | Medium | Curated alias dictionary + fuzzy/phonetic matching |
| Sub-2-second end-to-end latency | Medium | Streaming STT (~300ms) + local matching (~10ms) + pre-cached images (~0ms) |
| Handling varied audio quality across events | Medium | Noise reduction in STT, far-field audio mode |
| Maintaining the alias dictionary over time | Low | Quarterly updates aligned with banlist cycles (~4-6/year) |

The meta-relevant card pool at any time is roughly **15-20 distinct archetypes** with an
estimated **200-400 unique cards** across main decks, extra decks, and side decks. Adding
universal staples and hand traps brings the total alias dictionary to approximately
**300-500 entries** — a very manageable size for manual curation.

---

## 2. System Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Tournament      │     │  STT Service      │     │  Card Resolver    │     │  OBS Overlay     │
│  Audio Feed      │────▶│  (Deepgram /      │────▶│  (Alias Dict +   │────▶│  (Browser Source  │
│  (PCM 16kHz)     │ WS  │   AssemblyAI)     │ WS  │   Fuzzy Match)   │ WS  │   + WebSocket)   │
└─────────────────┘     └──────────────────┘     └──────────────────┘     └─────────────────┘
                                                          │
                                                          ▼
                                                  ┌──────────────────┐
                                                  │  Local Card DB    │
                                                  │  + Image Cache    │
                                                  │  (YGOProDeck)     │
                                                  └──────────────────┘
```

**Data flow:**
1. Tournament production audio is captured and streamed as 16kHz/16-bit/mono PCM over WebSocket
2. Cloud STT transcribes in real-time, returning partial/final transcript segments
3. Card resolver scans transcript text against an alias dictionary, then fuzzy/phonetic matching
4. Matched card ID triggers a WebSocket event to the overlay
5. Overlay (running as an OBS Browser Source) displays the pre-cached card image with a CSS animation

---

## 3. Speech-to-Text (STT)

### 3.1 Requirements

- **Streaming**: Must accept live audio, not batch files
- **Latency**: Partial results within ~300ms of speech
- **Custom vocabulary**: Must support boosting Yu-Gi-Oh! card names (e.g., "Nibiru", "Kashtira", "Tearlaments")
- **Audio format**: 16kHz PCM mono over WebSocket
- **Noise handling**: Venue commentary has variable background noise

### 3.2 Cloud Service Comparison

| Service | Streaming Latency | Custom Vocab | Pricing | Yu-Gi-Oh! Fit |
|---------|------------------|-------------|---------|---------------|
| **Deepgram Nova-3** | Sub-300ms | Keyterm Prompting: 100 terms, multi-word, dynamic | $0.0077/min ($0.46/hr) | **Excellent** — best balance of features, price, latency |
| **AssemblyAI Universal** | Sub-300ms | Keyterms: 100 terms, two-stage boosting | $0.0025/min + $0.04/hr keyterms | **Excellent** — claims 21% better domain-term accuracy |
| **Google Cloud STT** | Sub-1s | Phrase hints with boost values | $0.016/min | **Very good** — mature, but slightly higher latency |
| **AWS Transcribe** | 300-500ms | Custom Vocabulary with IPA hints | $0.030/min (streaming) | **Good** — pronunciation hints help, more setup work |
| **Azure Speech** | 500ms-1s | Phrase lists (free) or Custom Models ($$) | $0.0167/min | **Decent** — higher latency than competitors |
| **OpenAI Realtime API** | Sub-1s | **None** | ~$32/hr input | **Poor** — no custom vocab, very expensive |

### 3.3 Self-Hosted Options

| Solution | Latency | GPU Required | Custom Vocab | Notes |
|----------|---------|-------------|-------------|-------|
| **faster-whisper + SimulStreaming** | ~2-3s | Yes (RTX 3070+) | **None** | Free, but no vocab boosting hurts accuracy on card names |
| **whisper.cpp** | ~2-3s | Optional (Metal/CUDA) | **None** | Best for Apple Silicon or edge; same vocab limitation |
| **Vosk** | ~1.2s (tuned) | No (CPU-only) | **Yes** (KenLM) | Lower baseline accuracy, but only local option with custom vocab |

### 3.4 STT Recommendation

**Primary: Deepgram Nova-3** — Sub-300ms latency, $0.46/hr, excellent keyterm prompting
(supply all meta-relevant card names per tournament), WebSocket streaming, per-second
billing. $200 free credits for prototyping.

**Alternative: AssemblyAI Universal-Streaming** — Comparable latency, potentially better
accuracy on domain-specific terms with keyterms prompting. Cheaper base rate but keyterms
add $0.04/hr.

**Budget/offline: faster-whisper + post-processing** — Free but requires GPU hardware and
relies entirely on fuzzy matching to fix card name transcription errors. Viable for
prototyping but not recommended for production.

### 3.5 Custom Vocabulary Strategy

Both Deepgram and AssemblyAI support **dynamic keyterm lists** (up to 100 terms) that can
be supplied at connection time and updated mid-session. The workflow:

1. Before a match, load the card names from both players' known deck archetypes
2. Combine with universal staples (hand traps, board breakers, generic extra deck)
3. Supply as keyterms when opening the STT WebSocket connection
4. This gives the STT model the best chance of correctly transcribing niche names

**Example keyterm list** (partial):
```
Ash Blossom, Nibiru, Infinite Impermanence, Effect Veiler, Maxx C,
Ghost Ogre, Droll Lock Bird, Called by the Grave, Crossout Designator,
Forbidden Droplet, Snake-Eye Ash, Flamberge Dragon, Kashtira Fenrir,
Tearlaments Kitkallos, Albion the Sanctifire Dragon, ...
```

---

## 4. Card Name Resolution (Alias Matching)

### 4.1 The Problem

Commentators rarely say full official card names. Common patterns:

| Pattern | Example (Spoken) | Official Name |
|---------|-----------------|---------------|
| Single-word shortening | "Ash" | Ash Blossom & Joyous Spring |
| Partial name | "Sanctifire" | Albion the Sanctifire Dragon |
| Abbreviation (spoken) | "Imperm" | Infinite Impermanence |
| Acronym (spoken) | "DRNM" | Dark Ruler No More |
| Community slang | "Salads" | Salamangreat (archetype) |
| Community slang | "Flunder" / "Floo" | Floowandereeze (archetype) |
| Archetype reference | "the Snake-Eye" | Snake-Eye Ash (context-dependent) |
| STT transcription error | "Nibirue" | Nibiru, the Primal Being |

**No existing API or database maps nicknames to official names.** This must be built manually.

### 4.2 Recommended Hybrid Resolution Pipeline

```
Transcript text
      │
      ▼
┌─────────────────────────┐
│ Tier 1: Alias Dictionary │  <1ms   — exact lookup in curated map
│ (~300-500 entries)        │         — covers nicknames, slang, acronyms
└───────────┬─────────────┘
            │ miss
            ▼
┌─────────────────────────┐
│ Tier 2: Fuzzy Matching   │  ~5ms   — rapidfuzz token_set_ratio against
│ (full card DB, 13k+)     │         — all official card names
└───────────┬─────────────┘
            │ ambiguous (score 60-85)
            ▼
┌─────────────────────────┐
│ Tier 3: Phonetic Match   │  ~2ms   — Double Metaphone encoding
│ (jellyfish / natural)    │         — catches STT spelling errors
└───────────┬─────────────┘
            │ multiple candidates
            ▼
┌─────────────────────────┐
│ Tier 4: Context Disambig │  optional — weight by known deck archetypes
│ (deck-aware / LLM)       │  200-500ms if LLM used
└─────────────────────────┘
```

### 4.3 Alias Dictionary Structure

```json
{
  "ash": { "id": 14558127, "name": "Ash Blossom & Joyous Spring" },
  "ash blossom": { "id": 14558127, "name": "Ash Blossom & Joyous Spring" },
  "nib": { "id": 27204311, "name": "Nibiru, the Primal Being" },
  "nibiru": { "id": 27204311, "name": "Nibiru, the Primal Being" },
  "imperm": { "id": 10045474, "name": "Infinite Impermanence" },
  "veiler": { "id": 97268402, "name": "Effect Veiler" },
  "droll": { "id": 94145021, "name": "Droll & Lock Bird" },
  "ogre": { "id": 59438930, "name": "Ghost Ogre & Snow Rabbit" },
  "belle": { "id": 73642296, "name": "Ghost Belle & Haunted Mansion" },
  "maxx c": { "id": 23434538, "name": "Maxx \"C\"" },
  "droplet": { "id": 31517684, "name": "Forbidden Droplet" },
  "called by": { "id": 24224830, "name": "Called by the Grave" },
  "cbtg": { "id": 24224830, "name": "Called by the Grave" },
  "crossout": { "id": 65681983, "name": "Crossout Designator" },
  "sanctifire": { "id": 38811586, "name": "Albion the Sanctifire Dragon" },
  "drnm": { "id": 1234567, "name": "Dark Ruler No More" },
  "salads": { "archetype": "Salamangreat" },
  "floo": { "archetype": "Floowandereeze" },
  "flunder": { "archetype": "Floowandereeze" }
}
```

### 4.4 Fuzzy Matching Details

**Python (recommended for backend):**
- `rapidfuzz` — 5-100x faster than fuzzywuzzy, MIT licensed
- `rapidfuzz.process.extractOne(query, card_names, scorer=fuzz.token_set_ratio)`
- Accept matches scoring >85; investigate 60-85 range with phonetic fallback

**JavaScript (for client-side search):**
- `fuse.js` — configurable threshold (0.3-0.4), weighted multi-field search
- Set `ignoreLocation: true` for card name substring matching

**Phonetic matching:**
- `jellyfish` (Python) — Double Metaphone + Soundex + distance metrics in one package
- `natural` (npm) — Metaphone, Soundex for JavaScript
- Encode card name tokens at startup; compare against encoded transcript tokens at runtime

### 4.5 Maintenance Cadence

- TCG banlist updates **3-4 times per year** (most recent: February 2, 2026)
- New card set releases introduce new meta-relevant cards every ~2-3 months
- **Estimated effort**: ~4-6 alias dictionary updates per year, each adding/removing 10-30 entries
- The full card database (YGOProDeck API) should be re-downloaded weekly or on each startup

---

## 5. Card Data & Images (YGOProDeck API)

### 5.1 API Overview

The YGOProDeck API is **free, requires no authentication**, and provides complete card data.

| Endpoint | URL | Purpose |
|----------|-----|---------|
| All cards | `https://db.ygoprodeck.com/api/v7/cardinfo.php` | Full database (~13k cards) |
| Fuzzy search | `...cardinfo.php?fname=Magician` | Substring match on name |
| By archetype | `...cardinfo.php?archetype=Blue-Eyes` | All cards in an archetype |
| Archetypes list | `...api/v7/archetypes.php` | All archetype names |
| DB version | `...api/v7/checkDBVer.php` | Check for updates |

**Rate limit**: 20 requests/second. Exceeding = 1-hour ban.

### 5.2 Card Image CDN

| Size | URL Pattern | Dimensions |
|------|-------------|-----------|
| Full card | `https://images.ygoprodeck.com/images/cards/{id}.jpg` | 813 x 1185 px |
| Small | `https://images.ygoprodeck.com/images/cards_small/{id}.jpg` | ~168 x 245 px |
| Cropped art | `https://images.ygoprodeck.com/images/cards_cropped/{id}.jpg` | 624 x 624 px |

**Critical**: You must **download and self-host** images. Hotlinking is prohibited and will
result in IP blacklisting.

### 5.3 Useful Extra Fields

With `&misc=yes`:
- `beta_name` — previous/alternate card names
- `treated_as` — cards treated as other cards (e.g., Harpie Lady variants)
- `archetype` — each card's archetype grouping

### 5.4 Data Strategy

1. **On startup**: Download the full card database (~13k cards) and cache as local JSON
2. **On setup**: Pre-download all card images for meta-relevant cards (~300-500 images, ~200MB)
3. **Per match**: Pre-load images for both players' known deck archetypes into browser cache
4. **Weekly**: Check `checkDBVer.php` and re-download if the database has been updated

---

## 6. Livestream Overlay Integration

### 6.1 Delivery Method: OBS Browser Source

The overlay is built as a **web page served from a local server** and added to OBS (or any
streaming software) as a Browser Source. This approach:

- Works in **OBS Studio, Streamlabs, XSplit, vMix, CasparCG, and Wirecast**
- Supports native transparency (no chroma key needed)
- Allows real-time updates via WebSocket
- Uses standard HTML/CSS/JS

### 6.2 OBS Browser Source Setup

```
URL:     http://localhost:9090/overlay
Width:   1920
Height:  1080
```

The overlay page CSS must include:
```css
html, body {
  margin: 0;
  padding: 0;
  background: transparent;
  overflow: hidden;
}
```

### 6.3 Real-Time Updates via WebSocket

The local server pushes card display events to the overlay via WebSocket:

```json
{ "action": "showCard", "cardId": 14558127, "imageUrl": "/cards/14558127.jpg" }
{ "action": "hideCard", "cardId": 14558127 }
{ "action": "clearAll" }
```

The overlay client connects and renders:
```javascript
const ws = new WebSocket('ws://localhost:9090');
ws.onmessage = (event) => {
  const { action, cardId, imageUrl } = JSON.parse(event.data);
  if (action === 'showCard') displayCard(imageUrl);
  if (action === 'hideCard') removeCard(cardId);
};
```

### 6.4 Card Display Recommendations

For a 1920x1080 canvas:
- **Featured card display**: ~250x364 px (13% of canvas width)
- **Position**: Bottom-right or right side (avoid covering the game camera in center)
- **Animation**: Slide-in from right edge, hold for 3-5 seconds, fade out
- **Queue**: If multiple cards are mentioned rapidly, queue them and display sequentially with slight overlap

### 6.5 Advanced OBS Integration (Optional)

OBS WebSocket v5 (built into OBS 28+) supports `CallVendorRequest` to `obs-browser` with
`emit_event`, allowing an external control app to dispatch JavaScript events directly into
browser sources. This enables scene-aware behavior and tighter integration.

---

## 7. End-to-End Latency Budget

| Stage | Expected Latency | Notes |
|-------|-----------------|-------|
| Audio capture & encoding | ~50ms | PCM chunking at 50-100ms intervals |
| Network to STT service | ~50ms | WebSocket to nearest region |
| STT processing | ~200-300ms | Deepgram/AssemblyAI partial results |
| Card name resolution | ~5-10ms | Alias dict + fuzzy match (local) |
| WebSocket to overlay | <5ms | Localhost |
| Image render | ~0ms | Pre-cached images |
| **Total** | **~350-450ms** | **Well under the 2-second target** |

Even accounting for worst-case scenarios (network jitter, noisy audio requiring more STT
processing time, Tier 3 phonetic matching), the system should comfortably stay **under 1
second** in most cases.

The latency budget has **significant headroom**, which means:
- We could add an LLM disambiguation step (200-500ms) for ambiguous cases and still hit <2s
- We could use slightly cheaper/slower STT options and still meet the target
- We could add additional processing (sentiment, game state tracking) without concern

---

## 8. Recommended Tech Stack

### 8.1 Backend (Node.js / TypeScript)

Node.js is the best fit because:
- Native WebSocket support for both STT client and overlay server
- Excellent library ecosystem for fuzzy matching (`fuse.js`), phonetic matching (`natural`)
- Single language for both server and overlay client
- Strong async I/O model for handling multiple WebSocket connections

However, **Python is equally viable** and has advantages for the matching pipeline:
- `rapidfuzz` is the fastest fuzzy matching library available (any language)
- `jellyfish` provides comprehensive phonetic algorithms
- Better ML/NLP ecosystem if Tier 3 LLM disambiguation is needed

**Recommendation**: Python backend for the STT + matching pipeline, with a lightweight
Node.js or Python HTTP server for the overlay and WebSocket events. The overlay itself is
plain HTML/CSS/JS.

### 8.2 Full Stack

| Component | Technology | Role |
|-----------|-----------|------|
| STT Client | Python (`websockets`) | Streams audio to Deepgram, receives transcripts |
| Card Resolver | Python (`rapidfuzz`, `jellyfish`) | Alias dict + fuzzy + phonetic matching |
| Overlay Server | Python or Node.js (`ws`) | Serves overlay HTML, pushes card events via WS |
| Overlay UI | HTML + CSS + vanilla JS | Renders card images in OBS Browser Source |
| Card Database | Local JSON (from YGOProDeck API) | Card names, IDs, archetypes |
| Card Images | Local files (downloaded from YGOProDeck) | Self-hosted, pre-cached |
| Audio Capture | FFmpeg | Captures tournament audio feed → 16kHz PCM mono |

### 8.3 Key Libraries

| Library | Purpose |
|---------|---------|
| `deepgram-sdk` (Python) | Deepgram STT client with streaming support |
| `rapidfuzz` | Fast fuzzy string matching (5-100x faster than fuzzywuzzy) |
| `jellyfish` | Phonetic encoding (Double Metaphone, Soundex) + string distance |
| `websockets` (Python) | WebSocket client/server |
| `fuse.js` (optional, JS) | Client-side fuzzy search if search UI is needed |

---

## 9. Cost Estimates

### 9.1 Per-Tournament Cost (Cloud STT)

Assuming a typical tournament day = 8 hours of streamed commentary:

| Service | Hourly Cost | 8-Hour Day | Notes |
|---------|------------|-----------|-------|
| **Deepgram Nova-3** | $0.46/hr | **$3.70** | Best value; includes keyterms at no extra cost |
| **AssemblyAI** | $0.15 + $0.04/hr | **$1.52** | Cheapest with keyterms |
| Google Cloud STT | $0.96/hr | $7.68 | More expensive, mature service |
| AWS Transcribe | $1.80/hr | $14.40 | Most expensive streaming option |
| OpenAI Realtime | ~$32/hr | ~$256 | Not recommended |
| Self-hosted (GPU) | $0 (+ hardware) | $0 | Requires RTX 3070+ ($500-700 upfront) |

### 9.2 Infrastructure Costs

- **YGOProDeck API**: Free
- **Card image storage**: ~200MB for meta-relevant cards (negligible)
- **Server**: Runs locally on the tournament production machine (no cloud hosting needed)
- **Domain/SSL**: Not needed (localhost only)

### 9.3 Total Estimated Cost

For a cloud STT approach: **$2-4 per tournament day** (Deepgram or AssemblyAI).
Self-hosted: **$0/day** after initial GPU hardware investment.

---

## 10. Risks & Mitigations

### 10.1 High Risk: STT Misrecognition of Card Names

**Risk**: Even with keyterm boosting, the STT may misrecognize unusual card names,
especially in noisy environments or with accented commentators.

**Mitigations**:
- Keyterm prompting boosts recognition by 20-30% (per Deepgram benchmarks)
- Fuzzy + phonetic matching in the resolver catches most STT spelling errors
- The alias dictionary catches the most common card references regardless of STT accuracy
- Far-field noise reduction mode in STT services

### 10.2 Medium Risk: Rapid Card Mentions During Combos

**Risk**: During combo sequences, commentators may name 5+ cards in 10 seconds. The
overlay could become cluttered or show outdated cards.

**Mitigations**:
- Queue system: display cards sequentially with 2-3 second hold times
- "Latest card wins" mode: immediately replace the displayed card with the newest mention
- Configurable display duration per tournament preference

### 10.3 Medium Risk: Ambiguous Archetype References

**Risk**: Commentator says "the Snake-Eye" without specifying which Snake-Eye card.

**Mitigations**:
- Default to the archetype's most commonly played card (configurable)
- If deck lists are known, use game context to pick the most likely card
- Display the archetype logo/icon as a fallback
- Tier 4 LLM disambiguation for truly ambiguous cases

### 10.4 Low Risk: Player Audio Crosstalk

**Risk**: Players verbalizing their moves could trigger card displays from the wrong
context (e.g., reading opponent's card text).

**Mitigations**:
- Audio mixing: tournament production should prioritize commentator audio
- Volume threshold: only process audio above a certain level
- Speaker diarization (available in Deepgram/AssemblyAI) to distinguish commentators from players

### 10.5 Low Risk: YGOProDeck API Downtime

**Risk**: The free API could be down or rate-limited when you need to refresh card data.

**Mitigations**:
- Cache the full card database locally; only refresh weekly
- Pre-download all card images at setup time
- The overlay works entirely offline once initialized

---

## 11. Open Questions

1. **Deck list availability**: Can tournament organizers provide deck lists before matches?
   If so, the system can pre-filter the alias dictionary and keyterm list for maximum
   accuracy. YGOProDeck tracks tournament results but has no public API for deck lists.

2. **Audio source**: What's the exact audio capture method? Options include:
   - Direct audio feed from the commentator mixer (ideal — clean, isolated)
   - Screen/desktop audio capture from the streaming PC
   - Microphone capture in the production area

3. **Multiple overlays**: Should the system support showing cards for both Player 1 and
   Player 2 simultaneously, or just one card at a time?

4. **Manual override**: Should tournament staff have the ability to manually trigger a
   card display (e.g., via a control panel), overriding or supplementing the automated
   system?

5. **Card display duration**: How long should each card stay on screen? Configurable?
   Should it auto-dismiss after a timeout or wait for the next card mention?

6. **Genesys format**: The current meta includes the new Genesys format. Does the alias
   dictionary need to cover Genesys-specific cards/archetypes as well?

---

## 12. Sources

### Speech-to-Text
- [OpenAI Speech-to-Text Guide](https://developers.openai.com/api/docs/guides/speech-to-text/)
- [OpenAI Realtime Transcription](https://platform.openai.com/docs/guides/realtime-transcription)
- [Google Cloud STT Pricing](https://cloud.google.com/speech-to-text/pricing)
- [Google Cloud Speech Adaptation](https://docs.cloud.google.com/speech-to-text/docs/adaptation-model)
- [AWS Transcribe Pricing](https://aws.amazon.com/transcribe/pricing/)
- [AWS Transcribe Custom Vocabularies](https://docs.aws.amazon.com/transcribe/latest/dg/custom-vocabulary.html)
- [Azure Speech Pricing](https://azure.microsoft.com/en-us/pricing/details/speech/)
- [Deepgram Pricing](https://deepgram.com/pricing)
- [Deepgram Keyterm Prompting](https://developers.deepgram.com/docs/keyterm)
- [AssemblyAI Pricing](https://www.assemblyai.com/pricing)
- [AssemblyAI Streaming STT](https://www.assemblyai.com/products/streaming-speech-to-text)
- [AssemblyAI Keyterms Prompting](https://www.assemblyai.com/blog/streaming-keyterms-prompting)
- [faster-whisper (GitHub)](https://github.com/SYSTRAN/faster-whisper)
- [whisper-streaming (GitHub)](https://github.com/ufal/whisper_streaming)
- [Vosk](https://alphacephei.com/vosk/)

### Card Data
- [YGOProDeck API Guide](https://ygoprodeck.com/api-guide/)
- [YGOProDeck Premium](https://ygoprodeck.com/premium/)
- [YGOProDeck Top Archetypes](https://ygoprodeck.com/tournaments/top-archetypes/)
- [YGOProDeck Tournament Meta Decks](https://ygoprodeck.com/category/format/tournament%20meta%20decks)

### Card Nicknames & Aliases
- [Yu-Gi-Oh! Slang — Fandom Wiki](https://yugioh.fandom.com/wiki/Yu-Gi-Oh!_slang)
- [Shortened Card Names — Fandom Wiki](https://yugioh.fandom.com/wiki/Shortened_and_abbreviated_card_names_and_terms)
- [Unofficial Terms — Yugipedia](https://yugipedia.com/wiki/Slang)
- [Fan Nicknames — TV Tropes](https://tvtropes.org/pmwiki/pmwiki.php/FanNickname/YuGiOhCardGame)
- [Abbreviation List — Card Maker Forum](https://www.cardmaker.net/forums/topic/241843-list-of-commonly-used-abbreviations/)
- [TCGPlayer Common Terms](https://www.tcgplayer.com/content/article/Common-Terms-You-Need-To-Know-In-Yu-Gi-Oh/2a13d4f4-c6f3-4182-b712-41cc29a03d5e/)

### Fuzzy Matching & Phonetics
- [RapidFuzz (GitHub)](https://github.com/rapidfuzz/RapidFuzz)
- [Jellyfish (GitHub)](https://github.com/jamesturk/jellyfish)
- [Fuse.js](https://www.fusejs.io/)

### Overlay & Streaming
- [OBS Browser Source](https://obsproject.com/kb/browser-source)
- [obs-websocket (GitHub)](https://github.com/obsproject/obs-websocket)
- [obs-browser JS API](https://github.com/obsproject/obs-browser/blob/master/README.md)
- [YuGiBoard — YGO Life Points Overlay](https://github.com/ZTF666/YuGiBoard)
- [pkmn-tournament-overlay-tool](https://github.com/FomTarro/pkmn-tournament-overlay-tool)
- [Untapped.gg Twitch Extension (YGO Master Duel)](https://articles.mtga.untapped.gg/untappedgg-twitch-extension-mtga-marvel-snap-yu-gi-oh-master-duel/)

### Tournament Meta
- [Yu-Gi-Oh! Meta](https://www.yugiohmeta.com/)
- [YGO Banlist — Wargamer](https://www.wargamer.com/yugioh-trading-card-game/yu-gi-oh-banlist)
