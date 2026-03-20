/**
 * app.js — Client-side JavaScript for Robot Mind UI
 *
 * Handles: robot face state animations, voice input (Web Speech API),
 * text-to-speech playback (Gemini TTS), and progress bar control.
 */

// ── Robot Face State ────────────────────────────────────────────
let _voiceRecognition = null;
let _voiceIsListening = false;
let _voiceGotResult = false;
let _voiceSilenceTimer = null;
let _voiceAccumulatedTranscript = '';

function setRobotFaceState(state) {
    const container = document.getElementById('robot-face-outer');
    if (!container) return;
    container.classList.remove('robot-face-idle', 'robot-face-listening', 'robot-face-thinking', 'robot-face-talking');
    container.classList.add('robot-face-' + state);
    const label = document.getElementById('face-state-text');
    if (label) {
        if (state === 'listening') label.textContent = '🎙️ Listening…';
        else if (state === 'thinking') label.textContent = '🧠 Thinking…';
        else if (state === 'talking') label.textContent = '🔊 Speaking…';
        else label.textContent = '😊 Ready to chat!';
    }
}

// ── Voice Input (Web Speech API) ────────────────────────────────
function _submitVoiceTranscript() {
    if (_voiceGotResult) return;               // already submitted
    const transcript = _voiceAccumulatedTranscript.trim();
    if (!transcript) return;
    _voiceGotResult = true;

    // Store transcript and click hidden button to notify Python
    window._voiceTranscript = transcript;
    const btn = document.getElementById('voice-hidden-submit');
    if (btn) btn.click();

    // Stop recognition now that we have a complete sentence
    if (_voiceRecognition) _voiceRecognition.stop();
}

function toggleVoiceInput() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        window.__voiceNotSupported = true;
        return 'unsupported';
    }

    if (_voiceIsListening && _voiceRecognition) {
        // Manual stop: submit whatever we have so far
        if (_voiceSilenceTimer) { clearTimeout(_voiceSilenceTimer); _voiceSilenceTimer = null; }
        _submitVoiceTranscript();
        _voiceRecognition.stop();
        return 'stopped';
    }

    _voiceRecognition = new SpeechRecognition();
    _voiceRecognition.lang = 'en-US';
    _voiceRecognition.interimResults = false;
    _voiceRecognition.maxAlternatives = 1;
    _voiceRecognition.continuous = true;           // keep listening through pauses
    _voiceGotResult = false;
    _voiceAccumulatedTranscript = '';

    _voiceRecognition.onstart = function() {
        _voiceIsListening = true;
        _voiceGotResult = false;
        _voiceAccumulatedTranscript = '';
        const btn = document.getElementById('mic-toggle-btn');
        if (btn) btn.classList.add('mic-btn-recording');
        const status = document.getElementById('voice-status-label');
        if (status) { status.textContent = '🎙️ Listening…'; status.style.display = 'block'; }
        setRobotFaceState('listening');
    };

    _voiceRecognition.onresult = function(event) {
        if (_voiceGotResult) return;

        // Rebuild the full transcript from all final results so far
        let fullTranscript = '';
        for (let i = 0; i < event.results.length; i++) {
            if (event.results[i].isFinal) {
                fullTranscript += event.results[i][0].transcript;
            }
        }
        _voiceAccumulatedTranscript = fullTranscript;

        // Reset the silence timer — submit after 1.5 s of silence
        if (_voiceSilenceTimer) clearTimeout(_voiceSilenceTimer);
        _voiceSilenceTimer = setTimeout(function() {
            _voiceSilenceTimer = null;
            _submitVoiceTranscript();
        }, 1500);
    };

    _voiceRecognition.onerror = function(event) {
        console.warn('Speech recognition error:', event.error);
        if (_voiceSilenceTimer) { clearTimeout(_voiceSilenceTimer); _voiceSilenceTimer = null; }
        _voiceIsListening = false;
        _voiceGotResult = false;
        _voiceAccumulatedTranscript = '';
        const btn = document.getElementById('mic-toggle-btn');
        if (btn) btn.classList.remove('mic-btn-recording');
        const status = document.getElementById('voice-status-label');
        if (status) { status.textContent = ''; status.style.display = 'none'; }
        setRobotFaceState('idle');
    };

    _voiceRecognition.onend = function() {
        _voiceIsListening = false;
        if (_voiceSilenceTimer) { clearTimeout(_voiceSilenceTimer); _voiceSilenceTimer = null; }
        const btn = document.getElementById('mic-toggle-btn');
        if (btn) btn.classList.remove('mic-btn-recording');
        const status = document.getElementById('voice-status-label');
        if (status) { status.textContent = ''; status.style.display = 'none'; }
        // If we haven't submitted yet, submit whatever we have
        if (!_voiceGotResult && _voiceAccumulatedTranscript.trim()) {
            _submitVoiceTranscript();
        }
        if (_voiceGotResult) {
            setRobotFaceState('thinking');
        } else {
            setRobotFaceState('idle');
        }
    };

    _voiceRecognition.start();
    return 'started';
}

// ── Text-to-Speech (Gemini TTS via server audio) ────────────────
let _ttsAudio = null;

function playGeminiAudio(url) {
    stopSpeaking();
    _ttsAudio = new Audio(url);
    _ttsAudio.onplay = function() {
        setRobotFaceState('talking');
    };
    _ttsAudio.onended = function() {
        setRobotFaceState('idle');
        _ttsAudio = null;
    };
    _ttsAudio.onerror = function() {
        setRobotFaceState('idle');
        _ttsAudio = null;
    };
    _ttsAudio.play().catch(function(e) {
        console.warn('Audio play failed:', e);
        setRobotFaceState('idle');
    });
}

function stopSpeaking() {
    if (_ttsAudio) {
        _ttsAudio.pause();
        _ttsAudio.currentTime = 0;
        _ttsAudio = null;
    }
}

// ── Progress Bar Control ────────────────────────────────────────
let _progressTimer = null;
let _progressStart = 0;
let _progressDuration = 0;

function startDeterminateProgress(durationSec) {
    stopProgressAnimation();
    _progressDuration = durationSec * 1000;
    _progressStart = performance.now();
    const area = document.getElementById('progress-bar-area');
    const fill = document.getElementById('progress-bar-fill');
    const label = document.getElementById('progress-bar-label');
    const stateText = document.getElementById('face-state-text');
    if (!area || !fill) return;
    fill.classList.remove('indeterminate');
    fill.style.width = '0%';
    area.classList.add('progress-active');
    if (stateText) stateText.textContent = '🚀 Moving — Ready to Chat!';
    _progressTimer = setInterval(() => {
        const elapsed = performance.now() - _progressStart;
        const ratio = Math.min(elapsed / _progressDuration, 1);
        fill.style.width = Math.round(ratio * 100) + '%';
        if (label) label.textContent = Math.round(ratio * 100) + '%';
        if (ratio >= 1) clearInterval(_progressTimer);
    }, 50);
}

function startIndeterminateProgress() {
    stopProgressAnimation();
    const area = document.getElementById('progress-bar-area');
    const fill = document.getElementById('progress-bar-fill');
    const label = document.getElementById('progress-bar-label');
    const stateText = document.getElementById('face-state-text');
    if (!area || !fill) return;
    fill.style.width = '';
    fill.classList.add('indeterminate');
    area.classList.add('progress-active');
    if (label) label.textContent = '';
    if (stateText) stateText.textContent = '🧭 Navigating — Ready to Chat!';
}

function stopProgressAnimation() {
    if (_progressTimer) { clearInterval(_progressTimer); _progressTimer = null; }
    const area = document.getElementById('progress-bar-area');
    const fill = document.getElementById('progress-bar-fill');
    const label = document.getElementById('progress-bar-label');
    const stateText = document.getElementById('face-state-text');
    if (area) area.classList.remove('progress-active');
    if (fill) { fill.classList.remove('indeterminate'); fill.style.width = '0%'; }
    if (label) label.textContent = '';
    if (stateText) stateText.textContent = '😊 Ready to chat!';
}
