// YGO Card Overlay - WebSocket client with auto-reconnect and card queue

const HOLD_MS = 5000;       // How long to display each card
const FADE_MS = 300;        // Fade transition duration
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;

let ws = null;
let reconnectAttempt = 0;
let reconnectTimeout = null;
const queue = [];
let displaying = false;

// WebSocket connection with auto-reconnect (exponential backoff)
function connect() {
    const wsUrl = `ws://${window.location.hostname}:${window.location.port}/ws`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempt = 0; // Reset on successful connection
    };

    ws.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleMessage(message);
        } catch (e) {
            console.error('Failed to parse message:', e);
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        scheduleReconnect();
    };
}

function scheduleReconnect() {
    if (reconnectTimeout) return; // Already scheduled

    const delay = Math.min(
        RECONNECT_BASE_MS * Math.pow(2, reconnectAttempt),
        RECONNECT_MAX_MS
    );
    reconnectAttempt++;

    console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempt})`);
    reconnectTimeout = setTimeout(() => {
        reconnectTimeout = null;
        connect();
    }, delay);
}

function handleMessage(message) {
    const { action } = message;

    if (action === 'showCard') {
        queue.push(message);
        if (!displaying) {
            showNext();
        }
    } else if (action === 'hideCard') {
        // For Part 1, we don't implement selective hiding
        // Just let cards auto-hide after HOLD_MS
    } else if (action === 'clear') {
        clearAll();
    }
}

function showNext() {
    if (queue.length === 0) {
        displaying = false;
        return;
    }

    displaying = true;
    const card = queue.shift();
    const cardElement = createCardElement(card);

    const container = document.getElementById('card-container');
    container.appendChild(cardElement);

    // Trigger fade-in
    requestAnimationFrame(() => {
        cardElement.classList.add('visible');
    });

    // Schedule hide and next card
    setTimeout(() => {
        cardElement.classList.remove('visible');

        setTimeout(() => {
            cardElement.remove();
            showNext(); // FIXED: Call showNext AFTER removing element
        }, FADE_MS);
    }, HOLD_MS);
}

function createCardElement(card) {
    const { cardId, cardName, imageUrl } = card;

    const wrapper = document.createElement('div');
    wrapper.className = 'card-display';
    wrapper.dataset.cardId = cardId;

    const img = document.createElement('img');
    img.className = 'card-image';
    img.src = imageUrl;
    img.alt = cardName;

    const nameDiv = document.createElement('div');
    nameDiv.className = 'card-name';
    nameDiv.textContent = cardName;

    wrapper.appendChild(img);
    wrapper.appendChild(nameDiv);

    return wrapper;
}

function clearAll() {
    queue.length = 0; // Clear queue
    displaying = false;

    // Remove all card elements
    const container = document.getElementById('card-container');
    while (container.firstChild) {
        container.removeChild(container.firstChild);
    }
}

// Start connection
connect();
