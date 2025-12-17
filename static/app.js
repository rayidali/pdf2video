// DOM Elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileInfo = document.getElementById('file-info');
const fileName = document.getElementById('file-name');
const removeFileBtn = document.getElementById('remove-file');
const uploadBtn = document.getElementById('upload-btn');
const uploadSection = document.getElementById('upload-section');
const processingSection = document.getElementById('processing-section');
const resultsSection = document.getElementById('results-section');
const jobIdEl = document.getElementById('job-id');
const jobStatusEl = document.getElementById('job-status');
const processBtn = document.getElementById('process-btn');
const processingSpinner = document.getElementById('processing-spinner');
const markdownPreview = document.getElementById('markdown-preview');
const markdownRaw = document.getElementById('markdown-raw');
const copyBtn = document.getElementById('copy-btn');
const newUploadBtn = document.getElementById('new-upload-btn');
const tabBtns = document.querySelectorAll('.tab-btn');
const planBtn = document.getElementById('plan-btn');
const planSection = document.getElementById('plan-section');
const planSpinner = document.getElementById('plan-spinner');
const planContent = document.getElementById('plan-content');
const planTitle = document.getElementById('plan-title');
const planSummary = document.getElementById('plan-summary');
const planDuration = document.getElementById('plan-duration');
const planSlidesCount = document.getElementById('plan-slides-count');
const slidesContainer = document.getElementById('slides-container');
const planJson = document.getElementById('plan-json');
const copyPlanBtn = document.getElementById('copy-plan-btn');
const newUploadBtnResults = document.getElementById('new-upload-btn-results');
const manimBtn = document.getElementById('manim-btn');
const manimSection = document.getElementById('manim-section');
const manimSpinner = document.getElementById('manim-spinner');
const manimContent = document.getElementById('manim-content');
const manimSlidesCount = document.getElementById('manim-slides-count');
const manimSlidesContainer = document.getElementById('manim-slides-container');
const voiceoverBtn = document.getElementById('voiceover-btn');
const voiceoverSection = document.getElementById('voiceover-section');
const voiceoverSpinner = document.getElementById('voiceover-spinner');
const voiceoverContent = document.getElementById('voiceover-content');
const voiceoverSlidesCount = document.getElementById('voiceover-slides-count');
const voiceoverSlidesContainer = document.getElementById('voiceover-slides-container');

// State
let selectedFile = null;
let currentJobId = null;

// File Selection
dropZone.addEventListener('click', (e) => {
    // Only trigger if clicking the drop zone itself, not the label/button inside
    if (e.target === dropZone || e.target.closest('.drop-zone-content') && !e.target.closest('label')) {
        fileInput.click();
    }
});

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');

    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0].type === 'application/pdf') {
        handleFileSelect(files[0]);
    } else {
        showToast('Please select a PDF file', 'error');
    }
});

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFileSelect(e.target.files[0]);
    }
});

function handleFileSelect(file) {
    selectedFile = file;
    fileName.textContent = file.name;
    dropZone.classList.add('hidden');
    fileInfo.classList.remove('hidden');
    uploadBtn.disabled = false;
}

removeFileBtn.addEventListener('click', () => {
    selectedFile = null;
    fileInput.value = '';
    dropZone.classList.remove('hidden');
    fileInfo.classList.add('hidden');
    uploadBtn.disabled = true;
});

// Upload
uploadBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Uploading...';

    try {
        const formData = new FormData();
        formData.append('file', selectedFile);

        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload failed');
        }

        const data = await response.json();
        currentJobId = data.job_id;

        // Show processing section
        jobIdEl.textContent = currentJobId;
        updateStatus('uploaded');
        uploadSection.classList.add('hidden');
        processingSection.classList.remove('hidden');

        showToast('PDF uploaded successfully!', 'success');
    } catch (error) {
        showToast(error.message, 'error');
        uploadBtn.disabled = false;
        uploadBtn.textContent = 'Upload PDF';
    }
});

// Process OCR
processBtn.addEventListener('click', async () => {
    if (!currentJobId) return;

    processBtn.classList.add('hidden');
    processingSpinner.classList.remove('hidden');
    updateStatus('processing');

    try {
        const response = await fetch(`/api/process/${currentJobId}`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Processing failed');
        }

        const data = await response.json();

        // Fetch full markdown
        const mdResponse = await fetch(`/api/markdown/${currentJobId}`);
        const mdData = await mdResponse.json();

        // Display results
        displayMarkdown(mdData.markdown);
        updateStatus('complete');

        processingSection.classList.add('hidden');
        resultsSection.classList.remove('hidden');

        showToast('OCR completed successfully!', 'success');
    } catch (error) {
        showToast(error.message, 'error');
        updateStatus('failed');
        processBtn.classList.remove('hidden');
        processingSpinner.classList.add('hidden');
    }
});

// Display Markdown
function displayMarkdown(markdown) {
    markdownRaw.textContent = markdown;
    // Simple markdown to HTML conversion
    markdownPreview.innerHTML = simpleMarkdownToHtml(markdown);
}

function simpleMarkdownToHtml(md) {
    let html = md
        // Escape HTML
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        // Headers
        .replace(/^### (.*$)/gm, '<h3>$1</h3>')
        .replace(/^## (.*$)/gm, '<h2>$1</h2>')
        .replace(/^# (.*$)/gm, '<h1>$1</h1>')
        // Bold and Italic
        .replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        // Code blocks
        .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
        // Inline code
        .replace(/`(.*?)`/g, '<code>$1</code>')
        // Blockquotes
        .replace(/^> (.*$)/gm, '<blockquote>$1</blockquote>')
        // Unordered lists
        .replace(/^\s*[-*] (.*$)/gm, '<li>$1</li>')
        // Paragraphs
        .replace(/\n\n/g, '</p><p>')
        // Line breaks
        .replace(/\n/g, '<br>');

    // Wrap in paragraph
    html = '<p>' + html + '</p>';

    // Clean up empty paragraphs
    html = html.replace(/<p><\/p>/g, '');
    html = html.replace(/<p>(<h[123]>)/g, '$1');
    html = html.replace(/(<\/h[123]>)<\/p>/g, '$1');
    html = html.replace(/<p>(<pre>)/g, '$1');
    html = html.replace(/(<\/pre>)<\/p>/g, '$1');
    html = html.replace(/<p>(<blockquote>)/g, '$1');
    html = html.replace(/(<\/blockquote>)<\/p>/g, '$1');

    // Wrap consecutive li elements in ul
    html = html.replace(/(<li>.*?<\/li>)+/gs, '<ul>$&</ul>');

    return html;
}

// Tabs
tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;

        tabBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
            content.classList.add('hidden');
        });

        const activeTab = document.getElementById(`${tab}-tab`);
        activeTab.classList.remove('hidden');
        activeTab.classList.add('active');
    });
});

// Copy Markdown
copyBtn.addEventListener('click', async () => {
    try {
        await navigator.clipboard.writeText(markdownRaw.textContent);
        showToast('Markdown copied to clipboard!', 'success');
    } catch (error) {
        showToast('Failed to copy', 'error');
    }
});

// Generate Plan (or view cached plan)
planBtn.addEventListener('click', async () => {
    if (!currentJobId) {
        console.error('No job ID found');
        return;
    }

    console.log('=== Plan Generation/View ===');
    console.log('Job ID:', currentJobId);

    planBtn.disabled = true;
    planBtn.textContent = 'Checking...';

    try {
        // First check if plan already exists (cached)
        console.log('Checking for cached plan...');
        const cacheResponse = await fetch(`/api/plan/${currentJobId}`);

        if (cacheResponse.ok) {
            const cacheData = await cacheResponse.json();

            // If we have a cached plan, show it directly
            if (cacheData.plan && cacheData.plan.slides && cacheData.plan.slides.length > 0) {
                console.log('Found cached plan:', cacheData.plan.slides.length, 'slides');
                displayPlan(cacheData.plan);

                planSection.classList.remove('hidden');
                planSpinner.classList.add('hidden');
                planContent.classList.remove('hidden');
                resultsSection.classList.add('hidden');

                planSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

                showToast(`Loaded cached plan with ${cacheData.plan.slides.length} slides`, 'success');
                planBtn.disabled = false;
                planBtn.textContent = 'View Plan';

                // Also check if videos exist to update that button
                checkVideosExist();
                return;
            }
        }

        // No cached plan - generate new one
        console.log('No cached plan found, generating...');
        planBtn.textContent = 'Generating...';

        // Show plan section with spinner
        planSection.classList.remove('hidden');
        planSpinner.classList.remove('hidden');
        planContent.classList.add('hidden');

        // Scroll to plan section so user can see the spinner
        planSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

        console.log('Calling API: POST /api/plan/' + currentJobId);

        const response = await fetch(`/api/plan/${currentJobId}`, {
            method: 'POST'
        });

        console.log('Response status:', response.status);

        if (!response.ok) {
            const error = await response.json();
            console.error('API Error:', error);
            throw new Error(error.detail || 'Planning failed');
        }

        const data = await response.json();
        console.log('Plan received:', data);
        console.log('Number of slides:', data.plan?.slides?.length);

        displayPlan(data.plan);

        planSpinner.classList.add('hidden');
        planContent.classList.remove('hidden');
        resultsSection.classList.add('hidden');

        showToast('Plan generated successfully!', 'success');
        planBtn.disabled = false;
        planBtn.textContent = 'View Plan';
        console.log('=== Plan Generation Complete ===');
    } catch (error) {
        console.error('Planning failed:', error);
        showToast(error.message, 'error');
        planSpinner.classList.add('hidden');
        planSection.classList.add('hidden');
        planBtn.disabled = false;
        planBtn.textContent = 'Generate Plan';
    }
});

// Helper to check if videos exist and update button
async function checkVideosExist() {
    try {
        const response = await fetch(`/api/kodisc/${currentJobId}/progress`);
        if (response.ok) {
            const data = await response.json();
            if (data.status === 'complete' && data.results && data.results.length > 0) {
                manimBtn.textContent = 'View Videos';
            }
        }
    } catch (e) {
        // Ignore errors
    }
}

// Display Plan
function displayPlan(plan) {
    planTitle.textContent = plan.paper_title;
    planSummary.textContent = plan.paper_summary;
    planDuration.textContent = plan.target_duration_minutes;
    planSlidesCount.textContent = plan.slides.length;
    planJson.textContent = JSON.stringify(plan, null, 2);

    slidesContainer.innerHTML = '';
    plan.slides.forEach((slide, index) => {
        const slideEl = document.createElement('div');
        slideEl.className = 'slide-card';
        slideEl.innerHTML = `
            <div class="slide-header">
                <span class="slide-num">${slide.slide_number}</span>
                <h4>${slide.title}</h4>
                <span class="slide-type">${slide.visual_type}</span>
            </div>
            <div class="slide-body">
                <p class="slide-visual"><strong>Visual:</strong> ${slide.visual_description}</p>
                <div class="slide-points">
                    <strong>Key Points:</strong>
                    <ul>${slide.key_points.map(p => `<li>${p}</li>`).join('')}</ul>
                </div>
                <p class="slide-script"><strong>Narration:</strong> ${slide.voiceover_script}</p>
                <p class="slide-duration">${slide.duration_seconds}s</p>
            </div>
        `;
        slidesContainer.appendChild(slideEl);
    });
}

// Copy Plan JSON
copyPlanBtn.addEventListener('click', async () => {
    try {
        await navigator.clipboard.writeText(planJson.textContent);
        showToast('Plan JSON copied to clipboard!', 'success');
    } catch (error) {
        showToast('Failed to copy', 'error');
    }
});

// Generate Videos - USING KODISC API
manimBtn.addEventListener('click', async () => {
    if (!currentJobId) {
        console.error('No job ID found');
        return;
    }

    console.log('=== Video Generation via Kodisc API ===');
    console.log('Job ID:', currentJobId);

    manimBtn.disabled = true;
    manimBtn.textContent = 'Checking...';

    try {
        // First check if videos already exist (cached)
        console.log('Checking for cached videos...');
        const cacheResponse = await fetch(`/api/kodisc/${currentJobId}/progress`);

        if (cacheResponse.ok) {
            const cacheData = await cacheResponse.json();

            // If we have cached results, show them directly
            if (cacheData.status === 'complete' && cacheData.results && cacheData.results.length > 0) {
                console.log('Found cached videos:', cacheData.results.length);
                displayVideoResults(cacheData.results);

                manimSection.classList.remove('hidden');
                manimSpinner.classList.add('hidden');
                manimContent.classList.remove('hidden');
                planSection.classList.add('hidden');

                manimSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

                showToast(`Loaded ${cacheData.successful} cached videos`, 'success');
                manimBtn.disabled = false;
                manimBtn.textContent = 'Generate Videos';
                return;
            }
        }

        // No cached videos - start generation
        console.log('No cached videos found, starting generation...');

        // Show manim section with spinner
        manimSection.classList.remove('hidden');
        manimSpinner.classList.remove('hidden');
        manimContent.classList.add('hidden');

        // Scroll to manim section so user can see the spinner
        manimSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

        // Start background generation via Kodisc API
        console.log('Calling API: POST /api/kodisc/' + currentJobId + '/start');
        const response = await fetch(`/api/kodisc/${currentJobId}/start`, {
            method: 'POST'
        });

        console.log('Response status:', response.status);

        if (!response.ok) {
            const error = await response.json();
            console.error('API Error:', error);
            throw new Error(error.detail || 'Failed to start video generation');
        }

        const data = await response.json();
        console.log('Generation started:', data);
        console.log('Estimated cost:', data.estimated_cost);

        // Poll for progress
        manimBtn.textContent = `Generating 0/${data.total_slides}...`;
        await pollKodiscProgress(currentJobId, data.total_slides);

    } catch (error) {
        console.error('Video generation failed:', error);
        showToast(error.message, 'error');
        manimSpinner.classList.add('hidden');
        manimSection.classList.add('hidden');
        manimBtn.disabled = false;
        manimBtn.textContent = 'Generate Videos';
    }
});

// Poll for Kodisc generation progress
async function pollKodiscProgress(jobId, totalSlides) {
    const pollInterval = 3000; // 3 seconds (Kodisc takes a bit longer)

    while (true) {
        try {
            const response = await fetch(`/api/kodisc/${jobId}/progress`);
            const progress = await response.json();

            console.log('Progress:', progress);

            // Update button with progress
            manimBtn.textContent = `Generating ${progress.completed_slides}/${totalSlides}...`;

            // Update spinner text if it exists
            const spinnerText = manimSpinner.querySelector('p');
            if (spinnerText) {
                spinnerText.textContent = `Generating slide ${progress.current_slide}: ${progress.current_title || '...'}`;
            }

            if (progress.status === 'complete') {
                // Generation complete - show results
                displayVideoResults(progress.results);
                manimSpinner.classList.add('hidden');
                manimContent.classList.remove('hidden');
                planSection.classList.add('hidden');

                showToast(`Videos generated! ${progress.successful} successful, ${progress.failed} failed`, 'success');
                console.log('=== Kodisc Video Generation Complete ===');
                manimBtn.textContent = 'Generate Videos';
                return;
            }

            if (progress.status === 'error' || progress.status === 'cancelled') {
                throw new Error(progress.error || `Generation ${progress.status}`);
            }

            // Wait before polling again
            await new Promise(resolve => setTimeout(resolve, pollInterval));

        } catch (error) {
            console.error('Progress polling error:', error);
            throw error;
        }
    }
}

// Display Video Results (instead of just code)
function displayVideoResults(results) {
    manimSlidesCount.textContent = results.length;

    manimSlidesContainer.innerHTML = '';
    results.forEach((slide) => {
        const slideEl = document.createElement('div');
        slideEl.className = 'slide-card manim-slide';

        const statusBadge = slide.status === 'success'
            ? '<span class="status-badge complete">✓ Video Ready</span>'
            : `<span class="status-badge failed">✗ Failed</span>`;

        const videoSection = slide.status === 'success' && slide.video_url
            ? `<div class="video-container">
                <video controls width="100%">
                    <source src="${slide.video_url}" type="video/mp4">
                    Your browser does not support video playback.
                </video>
                <a href="${slide.video_url}" target="_blank" class="btn-small">Open Video</a>
               </div>`
            : slide.error
                ? `<p class="error-msg">Error: ${slide.error}</p>`
                : '';

        slideEl.innerHTML = `
            <div class="slide-header">
                <span class="slide-num">${slide.slide_id}</span>
                <h4>${slide.title}</h4>
                ${statusBadge}
            </div>
            <div class="slide-body">
                ${videoSection}
                ${slide.render_time ? `<p class="slide-duration">Rendered in ${slide.render_time.toFixed(1)}s</p>` : ''}
            </div>
        `;
        manimSlidesContainer.appendChild(slideEl);
    });
}

// Display Manim Code
function displayManimCode(slides) {
    manimSlidesCount.textContent = slides.length;

    manimSlidesContainer.innerHTML = '';
    slides.forEach((slide) => {
        const slideEl = document.createElement('div');
        slideEl.className = 'slide-card manim-slide';
        slideEl.innerHTML = `
            <div class="slide-header">
                <span class="slide-num">${slide.slide_id}</span>
                <h4>${slide.title}</h4>
                <span class="slide-type">${slide.class_name}</span>
            </div>
            <div class="slide-body">
                <div class="code-container">
                    <div class="code-header">
                        <span>${slide.slide_id}.py</span>
                        <button class="btn-copy-code" data-code="${encodeURIComponent(slide.code)}">Copy</button>
                    </div>
                    <pre class="code-block"><code>${escapeHtml(slide.code)}</code></pre>
                </div>
                <p class="slide-duration">Expected: ${slide.expected_duration}s</p>
            </div>
        `;
        manimSlidesContainer.appendChild(slideEl);
    });

    // Add copy handlers for code blocks
    document.querySelectorAll('.btn-copy-code').forEach(btn => {
        btn.addEventListener('click', async () => {
            const code = decodeURIComponent(btn.dataset.code);
            try {
                await navigator.clipboard.writeText(code);
                showToast('Code copied to clipboard!', 'success');
            } catch (error) {
                showToast('Failed to copy', 'error');
            }
        });
    });
}

// Escape HTML for code display
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// New Upload - shared reset function
function resetToUpload() {
    // Reset state
    selectedFile = null;
    currentJobId = null;
    fileInput.value = '';

    // Reset UI
    dropZone.classList.remove('hidden');
    fileInfo.classList.add('hidden');
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Upload PDF';
    processBtn.classList.remove('hidden');
    processingSpinner.classList.add('hidden');
    planBtn.disabled = false;
    planBtn.textContent = 'Generate Plan';
    manimBtn.disabled = false;
    manimBtn.textContent = 'Generate Videos';
    voiceoverBtn.disabled = false;
    voiceoverBtn.textContent = 'Generate Voiceovers';

    // Show upload section
    resultsSection.classList.add('hidden');
    processingSection.classList.add('hidden');
    planSection.classList.add('hidden');
    manimSection.classList.add('hidden');
    voiceoverSection.classList.add('hidden');
    uploadSection.classList.remove('hidden');
}

// New Upload button in plan section
newUploadBtn.addEventListener('click', resetToUpload);

// New Upload button in results section
newUploadBtnResults.addEventListener('click', resetToUpload);

// Back to Plan button (from videos section)
document.getElementById('back-to-plan-btn').addEventListener('click', async () => {
    manimSection.classList.add('hidden');
    planSection.classList.remove('hidden');
    planContent.classList.remove('hidden');
    planSpinner.classList.add('hidden');

    // Check if videos already exist - if so, show "View Videos" button
    manimBtn.disabled = false;
    try {
        const response = await fetch(`/api/kodisc/${currentJobId}/progress`);
        if (response.ok) {
            const data = await response.json();
            if (data.status === 'complete' && data.results && data.results.length > 0) {
                manimBtn.textContent = 'View Videos';
            } else {
                manimBtn.textContent = 'Generate Videos';
            }
        } else {
            manimBtn.textContent = 'Generate Videos';
        }
    } catch (e) {
        manimBtn.textContent = 'Generate Videos';
    }
});

// Back to OCR Results button (from plan section)
document.getElementById('back-to-results-btn').addEventListener('click', async () => {
    planSection.classList.add('hidden');
    resultsSection.classList.remove('hidden');

    // Check if plan already exists - if so, show "View Plan" button
    planBtn.disabled = false;
    try {
        const response = await fetch(`/api/plan/${currentJobId}`);
        if (response.ok) {
            const data = await response.json();
            if (data.plan && data.plan.slides && data.plan.slides.length > 0) {
                planBtn.textContent = 'View Plan';
            } else {
                planBtn.textContent = 'Generate Plan';
            }
        } else {
            planBtn.textContent = 'Generate Plan';
        }
    } catch (e) {
        planBtn.textContent = 'Generate Plan';
    }
});

// Status Update
function updateStatus(status) {
    jobStatusEl.textContent = status.charAt(0).toUpperCase() + status.slice(1);
    jobStatusEl.className = 'status-badge ' + status;
}

// Toast Notification
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    // Error toasts stay longer (8 seconds) so user can read them
    const duration = type === 'error' ? 8000 : 3000;

    setTimeout(() => {
        toast.remove();
    }, duration);
}

// ============================================
// JOB DISCOVERY & RESTORATION
// ============================================

const jobsList = document.getElementById('jobs-list');
const refreshJobsBtn = document.getElementById('refresh-jobs-btn');
const createFixtureBtn = document.getElementById('create-fixture-btn');
const jobsSection = document.getElementById('jobs-section');

// Load jobs on page load
async function loadJobs() {
    jobsList.innerHTML = '<p class="jobs-loading">Loading cached jobs...</p>';

    try {
        const response = await fetch('/api/jobs');
        const data = await response.json();

        if (data.jobs.length === 0) {
            jobsList.innerHTML = '<p class="no-jobs">No cached jobs found. Upload a PDF or create a test fixture.</p>';
            return;
        }

        jobsList.innerHTML = '';
        data.jobs.forEach(job => {
            const jobCard = document.createElement('div');
            jobCard.className = 'job-card';
            jobCard.onclick = () => restoreJob(job.job_id, job.completed_step);

            const badgeClass = job.completed_step === 'manim_complete' ? 'complete' : 'partial';
            const stepLabel = {
                'manim_complete': 'Complete',
                'plan_complete': 'Has Plan',
                'ocr_complete': 'Has OCR',
                'unknown': 'Unknown'
            }[job.completed_step] || job.completed_step;

            jobCard.innerHTML = `
                <span class="job-card-id">${job.job_id}</span>
                <div class="job-card-info">
                    <div class="job-card-name">${job.pdf_name || 'Unknown PDF'}</div>
                    <div class="job-card-status">
                        <span class="job-card-badge ${badgeClass}">${stepLabel}</span>
                        ${job.slides_count ? `<span>${job.slides_count} slides</span>` : ''}
                    </div>
                </div>
                <span class="job-card-arrow">→</span>
            `;

            jobsList.appendChild(jobCard);
        });
    } catch (error) {
        console.error('Failed to load jobs:', error);
        jobsList.innerHTML = '<p class="no-jobs">Failed to load jobs. Server may be offline.</p>';
    }
}

// Restore a job and navigate to the appropriate section
async function restoreJob(jobId, completedStep) {
    console.log(`Restoring job ${jobId} at step ${completedStep}`);

    try {
        // First restore the job on the server
        const response = await fetch(`/api/jobs/${jobId}/restore`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error('Failed to restore job');
        }

        const data = await response.json();
        console.log('Job restored:', data);

        // Set the current job ID
        currentJobId = jobId;

        // Hide all sections first
        uploadSection.classList.add('hidden');
        jobsSection.classList.add('hidden');
        processingSection.classList.add('hidden');
        resultsSection.classList.add('hidden');
        planSection.classList.add('hidden');
        manimSection.classList.add('hidden');

        // Navigate to the appropriate section based on completed step
        if (data.has_manim) {
            // Show Videos section with existing video results
            const videoResponse = await fetch(`/api/kodisc/${jobId}/progress`);
            const videoData = await videoResponse.json();
            if (videoData.results && videoData.results.length > 0) {
                displayVideoResults(videoData.results);
            }
            manimContent.classList.remove('hidden');
            manimSpinner.classList.add('hidden');
            manimSection.classList.remove('hidden');
            showToast(`Restored job ${jobId} - Videos ready!`, 'success');
        } else if (data.has_plan) {
            // Show Plan section with existing plan
            const planResponse = await fetch(`/api/plan/${jobId}`);
            const planData = await planResponse.json();
            displayPlan(planData.plan);
            planContent.classList.remove('hidden');
            planSpinner.classList.add('hidden');
            planSection.classList.remove('hidden');
            showToast(`Restored job ${jobId} - Ready to generate Manim code!`, 'success');
        } else if (data.has_markdown) {
            // Show Results section with existing markdown
            const mdResponse = await fetch(`/api/markdown/${jobId}`);
            const mdData = await mdResponse.json();
            displayMarkdown(mdData.markdown);
            resultsSection.classList.remove('hidden');
            showToast(`Restored job ${jobId} - Ready to generate plan!`, 'success');
        } else {
            // Show processing section
            jobIdEl.textContent = jobId;
            updateStatus('uploaded');
            processingSection.classList.remove('hidden');
            showToast(`Restored job ${jobId} - Ready to process OCR!`, 'success');
        }

        // Reset button states
        planBtn.disabled = false;
        planBtn.textContent = 'Generate Plan';
        manimBtn.disabled = false;
        manimBtn.textContent = 'Generate Videos';

    } catch (error) {
        console.error('Failed to restore job:', error);
        showToast(`Failed to restore job: ${error.message}`, 'error');
    }
}

// Create development fixture
async function createFixture() {
    createFixtureBtn.disabled = true;
    createFixtureBtn.textContent = 'Creating...';

    try {
        const response = await fetch('/api/dev/create-fixture', {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error('Failed to create fixture');
        }

        const data = await response.json();
        console.log('Fixture created:', data);

        showToast('Test fixture created! Refreshing job list...', 'success');

        // Reload jobs list
        await loadJobs();
    } catch (error) {
        console.error('Failed to create fixture:', error);
        showToast(`Failed to create fixture: ${error.message}`, 'error');
    } finally {
        createFixtureBtn.disabled = false;
        createFixtureBtn.textContent = 'Create Test Fixture';
    }
}

// Event listeners
refreshJobsBtn.addEventListener('click', loadJobs);
createFixtureBtn.addEventListener('click', createFixture);

// Update resetToUpload to also show jobs section again
const originalResetToUpload = resetToUpload;
function resetToUpload() {
    originalResetToUpload();
    jobsSection.classList.remove('hidden');
    loadJobs(); // Refresh the job list
}

// Reassign the event listeners with the updated function
newUploadBtn.removeEventListener('click', originalResetToUpload);
newUploadBtnResults.removeEventListener('click', originalResetToUpload);
newUploadBtn.addEventListener('click', resetToUpload);
newUploadBtnResults.addEventListener('click', resetToUpload);

// ============================================
// VOICEOVER GENERATION (ElevenLabs)
// ============================================

// Generate Voiceovers button click handler
voiceoverBtn.addEventListener('click', async () => {
    if (!currentJobId) {
        console.error('No job ID found');
        return;
    }

    console.log('=== Voiceover Generation via ElevenLabs ===');
    console.log('Job ID:', currentJobId);

    voiceoverBtn.disabled = true;
    voiceoverBtn.textContent = 'Checking...';

    try {
        // First check if voiceovers already exist (cached)
        console.log('Checking for cached voiceovers...');
        const cacheResponse = await fetch(`/api/voiceover/${currentJobId}/progress`);

        if (cacheResponse.ok) {
            const cacheData = await cacheResponse.json();

            // If we have cached results, show them directly
            if (cacheData.status === 'complete' && cacheData.results && cacheData.results.length > 0) {
                console.log('Found cached voiceovers:', cacheData.results.length);
                displayVoiceoverResults(cacheData.results);

                voiceoverSection.classList.remove('hidden');
                voiceoverSpinner.classList.add('hidden');
                voiceoverContent.classList.remove('hidden');
                manimSection.classList.add('hidden');

                voiceoverSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

                showToast(`Loaded ${cacheData.successful} cached voiceovers`, 'success');
                voiceoverBtn.disabled = false;
                voiceoverBtn.textContent = 'Generate Voiceovers';
                return;
            }
        }

        // No cached voiceovers - start generation
        console.log('No cached voiceovers found, starting generation...');

        // Show voiceover section with spinner
        voiceoverSection.classList.remove('hidden');
        voiceoverSpinner.classList.remove('hidden');
        voiceoverContent.classList.add('hidden');

        // Scroll to voiceover section so user can see the spinner
        voiceoverSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

        // Start background generation via ElevenLabs API
        console.log('Calling API: POST /api/voiceover/' + currentJobId + '/start');
        const response = await fetch(`/api/voiceover/${currentJobId}/start`, {
            method: 'POST'
        });

        console.log('Response status:', response.status);

        if (!response.ok) {
            const error = await response.json();
            console.error('API Error:', error);
            throw new Error(error.detail || 'Failed to start voiceover generation');
        }

        const data = await response.json();
        console.log('Generation started:', data);

        // Poll for progress
        voiceoverBtn.textContent = `Generating 0/${data.total_slides}...`;
        await pollVoiceoverProgress(currentJobId, data.total_slides);

    } catch (error) {
        console.error('Voiceover generation failed:', error);
        showToast(error.message, 'error');
        voiceoverSpinner.classList.add('hidden');
        voiceoverSection.classList.add('hidden');
        voiceoverBtn.disabled = false;
        voiceoverBtn.textContent = 'Generate Voiceovers';
    }
});

// Poll for Voiceover generation progress
async function pollVoiceoverProgress(jobId, totalSlides) {
    const pollInterval = 2000; // 2 seconds

    while (true) {
        try {
            const response = await fetch(`/api/voiceover/${jobId}/progress`);
            const progress = await response.json();

            console.log('Progress:', progress);

            // Update button with progress
            voiceoverBtn.textContent = `Generating ${progress.completed_slides}/${totalSlides}...`;

            // Update spinner text if it exists
            const spinnerText = voiceoverSpinner.querySelector('p');
            if (spinnerText) {
                spinnerText.textContent = `Generating voiceover ${progress.current_slide}: ${progress.current_title || '...'}`;
            }

            if (progress.status === 'complete') {
                // Generation complete - show results
                displayVoiceoverResults(progress.results);
                voiceoverSpinner.classList.add('hidden');
                voiceoverContent.classList.remove('hidden');
                manimSection.classList.add('hidden');

                showToast(`Voiceovers generated! ${progress.successful} successful, ${progress.failed} failed`, 'success');
                console.log('=== Voiceover Generation Complete ===');
                voiceoverBtn.textContent = 'Generate Voiceovers';
                voiceoverBtn.disabled = false;
                return;
            }

            if (progress.status === 'error' || progress.status === 'cancelled') {
                throw new Error(progress.error || `Generation ${progress.status}`);
            }

            // Wait before polling again
            await new Promise(resolve => setTimeout(resolve, pollInterval));

        } catch (error) {
            console.error('Progress polling error:', error);
            throw error;
        }
    }
}

// Display Voiceover Results
function displayVoiceoverResults(results) {
    voiceoverSlidesCount.textContent = results.length;

    voiceoverSlidesContainer.innerHTML = '';
    results.forEach((slide) => {
        const slideEl = document.createElement('div');
        slideEl.className = 'slide-card voiceover-slide';

        const statusBadge = slide.status === 'success'
            ? '<span class="status-badge complete">✓ Audio Ready</span>'
            : slide.status === 'skipped'
                ? '<span class="status-badge skipped">⊘ Skipped</span>'
                : `<span class="status-badge failed">✗ Failed</span>`;

        const audioSection = slide.status === 'success' && slide.audio_url
            ? `<div class="audio-container">
                <audio controls style="width: 100%;">
                    <source src="${slide.audio_url}" type="audio/mpeg">
                    Your browser does not support audio playback.
                </audio>
                <div class="audio-info">
                    <span class="audio-duration">${slide.audio_duration ? slide.audio_duration.toFixed(1) + 's' : ''}</span>
                    <a href="${slide.audio_url}" target="_blank" class="btn-small">Open Audio</a>
                    <button class="btn-small btn-copy-url" data-url="${slide.audio_url}">Copy URL</button>
                </div>
               </div>`
            : slide.error
                ? `<p class="error-msg">Error: ${slide.error}</p>`
                : '';

        slideEl.innerHTML = `
            <div class="slide-header">
                <span class="slide-num">${slide.slide_id}</span>
                <h4>${slide.title}</h4>
                ${statusBadge}
            </div>
            <div class="slide-body">
                ${audioSection}
            </div>
        `;
        voiceoverSlidesContainer.appendChild(slideEl);
    });

    // Add copy URL handlers
    document.querySelectorAll('.btn-copy-url').forEach(btn => {
        btn.addEventListener('click', async () => {
            const url = btn.dataset.url;
            try {
                await navigator.clipboard.writeText(url);
                showToast('URL copied to clipboard!', 'success');
            } catch (error) {
                showToast('Failed to copy', 'error');
            }
        });
    });
}

// Back to Videos button (from voiceover section)
document.getElementById('back-to-videos-btn').addEventListener('click', async () => {
    voiceoverSection.classList.add('hidden');
    manimSection.classList.remove('hidden');
    manimContent.classList.remove('hidden');
    manimSpinner.classList.add('hidden');

    // Check if voiceovers already exist - if so, show "View Voiceovers" button
    voiceoverBtn.disabled = false;
    try {
        const response = await fetch(`/api/voiceover/${currentJobId}/progress`);
        if (response.ok) {
            const data = await response.json();
            if (data.status === 'complete' && data.results && data.results.length > 0) {
                voiceoverBtn.textContent = 'View Voiceovers';
            } else {
                voiceoverBtn.textContent = 'Generate Voiceovers';
            }
        } else {
            voiceoverBtn.textContent = 'Generate Voiceovers';
        }
    } catch (e) {
        voiceoverBtn.textContent = 'Generate Voiceovers';
    }
});

// New Upload button in voiceover section
document.getElementById('new-upload-btn-voiceover').addEventListener('click', resetToUpload);

// Helper to check if voiceovers exist and update button
async function checkVoiceoversExist() {
    try {
        const response = await fetch(`/api/voiceover/${currentJobId}/progress`);
        if (response.ok) {
            const data = await response.json();
            if (data.status === 'complete' && data.results && data.results.length > 0) {
                voiceoverBtn.textContent = 'View Voiceovers';
            }
        }
    } catch (e) {
        // Ignore errors
    }
}

// Load jobs when the page loads
document.addEventListener('DOMContentLoaded', loadJobs);
