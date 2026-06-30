// State Management
const state = {
    taskId: null,
    filename: null,
    musicFilename: null,
    analysis: null,
    commands: null,
    preferences: {
        workout_type: '',
        mood: 'energetic',
        platform: 'instagram-reels',
        add_music: false,
        music_volume: 15,
        add_text: true,
        add_fade: true,
        auto_brightness: true
    },
    currentStep: 1,
    statusInterval: null
};

// DOM Elements
const elements = {
    claudeResponse: document.getElementById('claudeResponse'),
    runClaudeCmdsBtn: document.getElementById('runClaudeCmdsBtn'),
    uploadZone: document.getElementById('uploadZone'),
    videoInput: document.getElementById('videoInput'),
    previewContainer: document.getElementById('previewContainer'),
    videoPreview: document.getElementById('videoPreview'),
    fileInfo: document.getElementById('fileInfo'),
    removeFile: document.getElementById('removeFile'),
    musicToggle: document.getElementById('musicToggle'),
    musicContent: document.getElementById('musicContent'),
    musicZone: document.getElementById('musicZone'),
    musicInput: document.getElementById('musicInput'),
    musicInfo: document.getElementById('musicInfo'),
    analyzeBtn: document.getElementById('analyzeBtn'),
    analysisSection: document.getElementById('analysisSection'),
    uploadSection: document.getElementById('uploadSection'),
    analysisProgress: document.getElementById('analysisProgress'),
    analysisResults: document.getElementById('analysisResults'),
    analysisFill: document.getElementById('analysisFill'),
    analysisText: document.getElementById('analysisText'),
    toEditBtn: document.getElementById('toEditBtn'),
    editSection: document.getElementById('editSection'),
    workoutType: document.getElementById('workoutType'),
    customWorkout: document.getElementById('customWorkout'),
    moodType: document.getElementById('moodType'),
    platformType: document.getElementById('platformType'),
    musicVolume: document.getElementById('musicVolume'),
    volumeValue: document.getElementById('volumeValue'),
    addText: document.getElementById('addText'),
    addFade: document.getElementById('addFade'),
    autoBrightness: document.getElementById('autoBrightness'),
    generateCmdBtn: document.getElementById('generateCmdBtn'),
    commandsList: document.getElementById('commandsList'),
    generatePromptBtn: document.getElementById('generatePromptBtn'),
    claudePrompt: document.getElementById('claudePrompt'),
    copyPromptBtn: document.getElementById('copyPromptBtn'),
    processBtn: document.getElementById('processBtn'),
    exportSection: document.getElementById('exportSection'),
    processProgress: document.getElementById('processProgress'),
    processFill: document.getElementById('processFill'),
    processText: document.getElementById('processText'),
    processStep: document.getElementById('processStep'),
    exportComplete: document.getElementById('exportComplete'),
    exportError: document.getElementById('exportError'),
    errorMessage: document.getElementById('errorMessage'),
    outputPreview: document.getElementById('outputPreview'),
    downloadBtn: document.getElementById('downloadBtn'),
    startOverBtn: document.getElementById('startOverBtn'),
    retryBtn: document.getElementById('retryBtn'),
    helpBtn: document.getElementById('helpBtn'),
    helpModal: document.getElementById('helpModal'),
    closeHelp: document.getElementById('closeHelp'),
    toast: document.getElementById('toast'),
    toastMessage: document.getElementById('toastMessage'),
    motionTimeline: document.getElementById('motionTimeline'),
    segmentsList: document.getElementById('segmentsList'),
    suggestionsList: document.getElementById('suggestionsList'),
    statDuration: document.getElementById('statDuration'),
    statResolution: document.getElementById('statResolution'),
    statBrightness: document.getElementById('statBrightness'),
    statReps: document.getElementById('statReps')
};

// Format time helper
function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// Show toast notification
function showToast(message) {
    elements.toastMessage.textContent = message;
    elements.toast.classList.remove('hidden');
    setTimeout(() => {
        elements.toast.classList.add('hidden');
    }, 3000);
}

// Update step indicator
function updateSteps(step) {
    state.currentStep = step;
    document.querySelectorAll('.step').forEach((el, i) => {
        const stepNum = i + 1;
        el.classList.remove('active', 'completed');
        if (stepNum === step) el.classList.add('active');
        else if (stepNum < step) el.classList.add('completed');
    });
}

// Switch section
function showSection(sectionId) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.getElementById(sectionId).classList.add('active');
}

// File size formatter
function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ============= UPLOAD HANDLERS =============

// Click to upload
elements.uploadZone.addEventListener('click', () => {
    elements.videoInput.click();
});

elements.videoInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleVideoFile(e.target.files[0]);
    }
});

// Drag and drop
elements.uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    elements.uploadZone.classList.add('dragover');
});

elements.uploadZone.addEventListener('dragleave', () => {
    elements.uploadZone.classList.remove('dragover');
});

elements.uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    elements.uploadZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
        handleVideoFile(e.dataTransfer.files[0]);
    }
});

// Handle video file
function handleVideoFile(file) {
    // Validate
    const validTypes = ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/x-matroska', 'video/webm'];
    if (!validTypes.includes(file.type) && !file.name.match(/\.(mp4|mov|avi|mkv|webm)$/i)) {
        showToast('Invalid video format');
        return;
    }

    // Show preview
    const url = URL.createObjectURL(file);
    elements.videoPreview.src = url;
    elements.fileInfo.innerHTML = `
        <i class="fas fa-video"></i>
        <span>${file.name}</span>
        <span class="file-size">${formatFileSize(file.size)}</span>
    `;
    elements.previewContainer.classList.remove('hidden');
    elements.uploadZone.classList.add('hidden');
    elements.analyzeBtn.disabled = false;
    state.filename = file.name;

    // Upload to server
    uploadFile(file);
}

// Upload to server
async function uploadFile(file) {
    const formData = new FormData();
    formData.append('video', file);

    // Add music if selected
    if (state.musicFilename) {
        const musicFile = elements.musicInput.files[0];
        if (musicFile) {
            formData.append('music', musicFile);
        }
    }

    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        if (data.task_id) {
            state.taskId = data.task_id;
            console.log('Uploaded:', data);
        } else {
            showToast('Upload failed: ' + data.error);
        }
    } catch (error) {
        console.error('Upload error:', error);
        showToast('Upload failed');
    }
}

// Remove file
elements.removeFile.addEventListener('click', () => {
    elements.previewContainer.classList.add('hidden');
    elements.uploadZone.classList.remove('hidden');
    elements.videoPreview.src = '';
    elements.analyzeBtn.disabled = true;
    state.filename = null;
    state.taskId = null;
    elements.videoInput.value = '';
});

// Music toggle
elements.musicToggle.addEventListener('click', () => {
    elements.musicContent.classList.toggle('hidden');
    elements.musicToggle.classList.toggle('expanded');
    state.preferences.add_music = !elements.musicContent.classList.contains('hidden');
});

// Music upload
elements.musicZone.addEventListener('click', () => {
    elements.musicInput.click();
});

elements.musicInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        const file = e.target.files[0];
        state.musicFilename = file.name;
        elements.musicInfo.innerHTML = `
            <i class="fas fa-music"></i>
            <span>${file.name}</span>
            <span class="file-size">${formatFileSize(file.size)}</span>
        `;
        elements.musicInfo.classList.remove('hidden');
        elements.musicZone.classList.add('hidden');
        
        // Re-upload with music
        if (state.filename && elements.videoInput.files[0]) {
            uploadFile(elements.videoInput.files[0]);
        }
    }
});

// ============= ANALYSIS =============

elements.analyzeBtn.addEventListener('click', async () => {
    if (!state.taskId) {
        showToast('Please wait for upload to complete');
        return;
    }

    showSection('analysisSection');
    updateSteps(2);
    elements.analysisProgress.classList.remove('hidden');
    elements.analysisResults.classList.add('hidden');

    try {
        // Start analysis
        await fetch(`/api/analyze/${state.taskId}`, { method: 'POST' });

        // Poll for status
        state.statusInterval = setInterval(checkAnalysisStatus, 500);
    } catch (error) {
        showToast('Failed to start analysis');
    }
});

async function checkAnalysisStatus() {
    try {
        const response = await fetch(`/api/status/${state.taskId}`);
        const data = await response.json();

        // Update progress
        elements.analysisFill.style.width = data.progress + '%';
        elements.analysisText.textContent = `Analyzing... ${Math.round(data.progress)}%`;

        if (data.status === 'analyzed') {
            clearInterval(state.statusInterval);
            state.analysis = data.analysis;
            displayAnalysis(data.analysis);
        } else if (data.status === 'error') {
            clearInterval(state.statusInterval);
            showToast('Analysis error: ' + data.error);
            showSection('uploadSection');
            updateSteps(1);
        }
    } catch (error) {
        console.error('Status check error:', error);
    }
}

function displayAnalysis(analysis) {
    elements.analysisProgress.classList.add('hidden');
    elements.analysisResults.classList.remove('hidden');

    // Stats
    elements.statDuration.textContent = formatTime(analysis.duration);
    elements.statResolution.textContent = `${analysis.resolution.width}x${analysis.resolution.height}`;
    elements.statBrightness.textContent = Math.round(analysis.brightness);
    elements.statReps.textContent = analysis.estimated_reps || '--';

    // Timeline
    let timelineHTML = '';
    analysis.motion_segments.forEach((seg, i) => {
        const left = (seg.start_time / analysis.duration) * 100;
        const width = (seg.duration / analysis.duration) * 100;
        timelineHTML += `<div class="timeline-segment" style="left:${left}%;width:${width}%" title="Segment ${i+1}: ${formatTime(seg.start_time)} - ${formatTime(seg.end_time)}"></div>`;
    });
    analysis.quiet_segments.forEach((q, i) => {
        const left = (q.start_time / analysis.duration) * 100;
        const width = (q.duration / analysis.duration) * 100;
        timelineHTML += `<div class="timeline-quiet" style="left:${left}%;width:${width}%" title="Rest: ${q.duration.toFixed(1)}s"></div>`;
    });
    elements.motionTimeline.innerHTML = timelineHTML;

    // Segments
    let segmentsHTML = '';
    analysis.motion_segments.forEach((seg, i) => {
        segmentsHTML += `
            <div class="segment-item">
                <div class="segment-number">${i + 1}</div>
                <div class="segment-info">
                    <div class="segment-time">${formatTime(seg.start_time)} - ${formatTime(seg.end_time)}</div>
                    <div class="segment-details">${seg.duration.toFixed(1)}s duration</div>
                </div>
                ${seg.estimated_reps ? `<div class="segment-reps">~${seg.estimated_reps} reps</div>` : ''}
            </div>
        `;
    });
    elements.segmentsList.innerHTML = segmentsHTML || '<p class="empty-text">No segments detected</p>';

    // Suggestions
    let suggestionsHTML = '';
    analysis.suggestions.forEach(sug => {
        suggestionsHTML += `
            <div class="suggestion-item">
                <div class="suggestion-icon">${sug.icon}</div>
                <div class="suggestion-content">
                    <h4>${sug.title}</h4>
                    <p>${sug.description} → ${sug.fix}</p>
                </div>
            </div>
        `;
    });
    elements.suggestionsList.innerHTML = suggestionsHTML || '<p class="empty-text">No suggestions</p>';
}

// Continue to edit
elements.toEditBtn.addEventListener('click', () => {
    showSection('editSection');
    updateSteps(3);
});

// ============= EDIT OPTIONS =============

// Pill selectors
document.querySelectorAll('.pill-selector').forEach(selector => {
    selector.querySelectorAll('.pill').forEach(pill => {
        pill.addEventListener('click', () => {
            selector.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');

            const id = selector.id;
            const value = pill.dataset.value;

            if (id === 'workoutType') {
                if (value === 'custom') {
                    elements.customWorkout.classList.remove('hidden');
                } else {
                    elements.customWorkout.classList.add('hidden');
                    state.preferences.workout_type = value;
                }
            } else if (id === 'moodType') {
                state.preferences.mood = value;
            }
        });
    });
});

// Custom workout input
elements.customWorkout.addEventListener('input', (e) => {
    state.preferences.workout_type = e.target.value;
});

// Platform selector
elements.platformType.querySelectorAll('.platform-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        elements.platformType.querySelectorAll('.platform-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.preferences.platform = btn.dataset.value;
    });
});

// Volume slider
elements.musicVolume.addEventListener('input', (e) => {
    const value = e.target.value;
    elements.volumeValue.textContent = value + '%';
    state.preferences.music_volume = parseInt(value);
});

// Toggle switches
elements.addText.addEventListener('change', (e) => {
    state.preferences.add_text = e.target.checked;
});
elements.addFade.addEventListener('change', (e) => {
    state.preferences.add_fade = e.target.checked;
});
elements.autoBrightness.addEventListener('change', (e) => {
    state.preferences.auto_brightness = e.target.checked;
});

// ============= GENERATE COMMANDS =============

elements.generateCmdBtn.addEventListener('click', async () => {
    if (!state.analysis) {
        showToast('No analysis data');
        return;
    }

    try {
        const response = await fetch('/api/generate-commands', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                analysis: state.analysis,
                preferences: state.preferences,
                task_id: state.taskId
            })
        });

        const data = await response.json();
        if (data.commands) {
            state.commands = data.commands;
            displayCommands(data.commands);
            elements.processBtn.disabled = false;
        }
    } catch (error) {
        showToast('Failed to generate commands');
    }
});

function displayCommands(commands) {
    let html = '';
    commands.forEach((cmd, i) => {
        html += `
            <div class="command-item">
                <div class="command-icon">${cmd.icon}</div>
                <div class="command-name">${cmd.name}</div>
                <div class="command-status">Step ${i + 1}</div>
            </div>
        `;
    });
    elements.commandsList.innerHTML = html;
}

// ============= GENERATE CLAUDE PROMPT =============

elements.generatePromptBtn.addEventListener('click', async () => {
    if (!state.analysis) {
        showToast('No analysis data');
        return;
    }

    try {
        const response = await fetch('/api/generate-prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                analysis: state.analysis,
                preferences: state.preferences
            })
        });

        const data = await response.json();
        if (data.prompt) {
            elements.claudePrompt.value = data.prompt;
            elements.copyPromptBtn.classList.remove('hidden');
        }
    } catch (error) {
        showToast('Failed to generate prompt');
    }
});

// Copy prompt
elements.copyPromptBtn.addEventListener('click', () => {
    elements.claudePrompt.select();
    navigator.clipboard.writeText(elements.claudePrompt.value)
        .then(() => showToast('Prompt copied to clipboard!'))
        .catch(() => {
            document.execCommand('copy');
            showToast('Prompt copied!');
        });
});

// ============= PROCESS VIDEO (AUTO COMMANDS) =============

elements.processBtn.addEventListener('click', async () => {
    if (!state.commands || !state.taskId) {
        showToast('Generate commands first');
        return;
    }

    showSection('exportSection');
    updateSteps(4);
    elements.processProgress.classList.remove('hidden');
    elements.exportComplete.classList.add('hidden');
    elements.exportError.classList.add('hidden');

    try {
        await fetch('/api/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                task_id: state.taskId,
                commands: state.commands
            })
        });

        // Poll for processing status
        state.statusInterval = setInterval(checkProcessStatus, 500);
    } catch (error) {
        showToast('Failed to start processing');
    }
});

async function checkProcessStatus() {
    try {
        const response = await fetch(`/api/status/${state.taskId}`);
        const data = await response.json();

        elements.processFill.style.width = data.progress + '%';
        elements.processText.textContent = `Processing... ${Math.round(data.progress)}%`;
        if (data.current_step) {
            elements.processStep.textContent = data.current_step;
        }

        if (data.status === 'completed') {
            clearInterval(state.statusInterval);
            elements.processProgress.classList.add('hidden');
            elements.exportComplete.classList.remove('hidden');
            
            // Load output preview
            elements.outputPreview.src = `/api/download/${state.taskId}?preview=true`;
            showToast('Video processed successfully!');
        } else if (data.status === 'error') {
            clearInterval(state.statusInterval);
            elements.processProgress.classList.add('hidden');
            elements.exportError.classList.remove('hidden');
            elements.errorMessage.textContent = data.error;
        }
    } catch (error) {
        console.error('Status check error:', error);
    }
}

// ============= DOWNLOAD & RESET =============

elements.downloadBtn.addEventListener('click', () => {
    window.location.href = `/api/download/${state.taskId}`;
});

elements.startOverBtn.addEventListener('click', () => {
    resetApp();
});

elements.retryBtn.addEventListener('click', () => {
    showSection('editSection');
    updateSteps(3);
});

function resetApp() {
    // Clear state
    state.taskId = null;
    state.filename = null;
    state.musicFilename = null;
    state.analysis = null;
    state.commands = null;
    state.preferences = {
        workout_type: '',
        mood: 'energetic',
        platform: 'instagram-reels',
        add_music: false,
        music_volume: 15,
        add_text: true,
        add_fade: true,
        auto_brightness: true
    };

    // Reset UI
    showSection('uploadSection');
    updateSteps(1);
    elements.previewContainer.classList.add('hidden');
    elements.uploadZone.classList.remove('hidden');
    elements.videoPreview.src = '';
    elements.analyzeBtn.disabled = true;
    elements.videoInput.value = '';
    elements.musicInput.value = '';
    elements.musicInfo.classList.add('hidden');
    elements.musicZone.classList.remove('hidden');
    elements.musicContent.classList.add('hidden');
    elements.commandsList.innerHTML = '<p class="empty-text">Click "Generate" to create FFmpeg commands</p>';
    elements.claudePrompt.value = '';
    elements.claudeResponse.value = ''; // Clear claude response box too
    elements.copyPromptBtn.classList.add('hidden');
    elements.runClaudeCmdsBtn.disabled = true; // Re-disable claude run button
    elements.processBtn.disabled = true;
    elements.exportComplete.classList.add('hidden');
    elements.exportError.classList.add('hidden');
    elements.processProgress.classList.add('hidden');

    // Reset selections
    document.querySelectorAll('.pill.active').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.platform-btn.active').forEach(p => p.classList.remove('active'));
    document.querySelector('.pill[data-value="energetic"]')?.classList.add('active');
    document.querySelector('.platform-btn[data-value="instagram-reels"]')?.classList.add('active');
    elements.musicVolume.value = 15;
    elements.volumeValue.textContent = '15%';
    elements.addText.checked = true;
    elements.addFade.checked = true;
    elements.autoBrightness.checked = true;
}

// ============= HELP MODAL =============

elements.helpBtn.addEventListener('click', () => {
    elements.helpModal.classList.remove('hidden');
});

elements.closeHelp.addEventListener('click', () => {
    elements.helpModal.classList.add('hidden');
});

elements.helpModal.addEventListener('click', (e) => {
    if (e.target === elements.helpModal) {
        elements.helpModal.classList.add('hidden');
    }
});


// ============= CLAUDE RESPONSE PASTE & EXECUTE =============

// Enable the run button only if there is text in the response box
elements.claudeResponse.addEventListener('input', (e) => {
    const hasText = e.target.value.trim().length > 10;
    elements.runClaudeCmdsBtn.disabled = !hasText;
});

// Send pasted text to backend to extract and run FFmpeg commands
elements.runClaudeCmdsBtn.addEventListener('click', async () => {
    const pastedText = elements.claudeResponse.value.trim();
    if (!pastedText || !state.taskId) {
        showToast('Please paste Claude\'s response');
        return;
    }

    if (!confirm('This will run the FFmpeg commands provided by Claude. Are you sure?')) {
        return;
    }

    showSection('exportSection');
    updateSteps(4);
    elements.processProgress.classList.remove('hidden');
    elements.exportComplete.classList.add('hidden');
    elements.exportError.classList.add('hidden');
    elements.processText.textContent = 'Sending Claude commands to server...';

    try {
        const response = await fetch('/api/run-claude-commands', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                task_id: state.taskId,
                claude_text: pastedText
            })
        });

        const data = await response.json();
        
        if (data.error) {
            elements.processProgress.classList.add('hidden');
            elements.exportError.classList.remove('hidden');
            elements.errorMessage.textContent = data.error;
        } else {
            // Start polling for progress
            state.statusInterval = setInterval(checkProcessStatus, 500);
        }
    } catch (error) {
        showToast('Failed to send commands');
        elements.processProgress.classList.add('hidden');
        showSection('editSection');
        updateSteps(3);
    }
});

// ============= INITIALIZATION =============
console.log('Workout Video Editor initialized');